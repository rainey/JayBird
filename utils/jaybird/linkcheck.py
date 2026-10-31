#!/usr/bin/env python3
# JayBird plugins.a link checker.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Simulate the final Cardinal link against the plugins archive.

`make -C plugins plugins.a` only compiles and archives; ar does not resolve
symbols, so duplicate/missing cross-TU symbols (the CountModula class of
failures) surface only at the final Cardinal link — usually hours into a nix
build. This tool pulls the same analysis forward to right after the archive
build, in seconds.

Method: parse `nm -A` over plugins.a and classify every undefined reference:
  1. defined elsewhere in the archive          -> resolved
  2. matching a known-external pattern (libc,
     libstdc++, rack internals resolved at the
     Cardinal link, jansson, nanovg, gl*, …)   -> external, fine
  3. anything else                             -> MISSING: would break the link
Also reports duplicate strong definitions (same symbol defined in more than
one object), which ld rejects for non-weak/non-common symbols.

Weak (W/w/V/v) and common (C) definitions are treated as non-conflicting:
multiple weak defs are fine, and an undefined ref resolved by only a weak
def is reported (that is how the init__CountModula-style bug manifests when
a header declares but nothing defines).

Usage:
  python3 utils/jaybird/linkcheck.py [--archive plugins/plugins.a] [--json OUT]
  python3 utils/jaybird/linkcheck.py --filter <Name>   # report per-object info
  python3 utils/jaybird/linkcheck.py --list-extern     # dump resolved externs

Exit status: 0 clean, 1 missing symbols or duplicates found.

External allowlist: patterns are tried in order; first match wins. Keep the
patterns tight — an over-broad allowlist hides real breakage. Anything that
does not match lands in the missing bucket with the referencing objects,
which is the actionable output.
"""

import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Known-external symbol patterns. Ordered; first match classifies the symbol.
# These are all provided at the final Cardinal link by libc/libstdc++/libs that
# Cardinal links, or by Cardinal's own objects (NOT in plugins.a).
# ---------------------------------------------------------------------------
EXTERNAL_PATTERNS = [
    # libstdc++ (all C++ manglings of std:: and its internals; the archive's
    # undefined _Z* refs to std are resolved by libstdc++.so at link time)
    r"^_Z.*St[0-9]",
    r"^_ZN?St",           # _ZNSt..., _ZNKSt... (std::)
    r"^_ZSt",             # std:: templates (operator<<? etc.)
    r"^_ZT[ISV]?St",      # typeinfo/vtables for std:: types
    r"^_ZT[ISV]S",        # typeinfo/vtables via std:: substitutions (S<IaIcE> etc.)
    r"^_ZT[ISV][a-z]$",   # typeinfo/vtables for builtin scalar types (i, f, d, v, ...)
    r"^_ZTh[0-9]",        # thunk stubs
    r"^_ZTv[0-9]",        # virtual thunks
    # operator new/delete families: special (non-length-prefixed) manglings —
    # `_Znwm`, `_ZnwmRK`, `_ZnaXm`, `_ZdlPv`, `_ZdlPvm`, `_ZdaPv`, `_ZdaPvmS_`.
    # IMPORTANT: lowercase after _Z. Length-prefixed USER symbols always go
    # `_ZN<digits>` / `_Z<digits>` (uppercase N or digit) — do NOT broaden
    # this to `_Z[A-Z]` again: that auto-classified every user-level C++
    # symbol (e.g. InfNoiseModuleWidget::step()) as external and hid real
    # missing-definition bugs from the final link.
    r"^_Zn[a-z]",
    r"^_Zd[a-z]",
                          # __throw_*, Rb_tree helpers, guards... but NOT
                          # _Z<digits> (those are user functions like
                          # _Z15getDefaultThemeb) — handled below
    # libgcc
    r"^_Unwind_",
    r"^__gxx_personality",
    r"^__cxa_",
    r"^__dynamic_cast$",   # libstdc++ helper
    r"^__errno_location$",
    r"^__stack_chk",
    r"^__tls_get_addr",
    r"^__popcount",
    r"^__once_proxy",
    r"^_GLOBAL_OFFSET_TABLE_$",
    r"^__dso_handle$",
    r"^__libc_single_threaded$",
    r"^__isoc",           # isoc23_sscanf &c (libc)
    r"^_ITM_",            # unused-slot markers
    # Cardinal core (resolved at the final link from Cardinal's own objects)
    r"^_ZN8Cardinal",     # CardinalPluginContext & friends
    r"^async_dialog_",
    r"^handleHostParameterDrag",
    r"async_dialog_",           # mangled: _Z20async_dialog_messagePKc ...
    r"handleHostParameterDrag",
    r"^_Z.*async_dialog", r"^_Z.*handleHostParameterDrag",
    r"^_Z.*nvglu", r"^_Z.*carla_getNative",
    r"^_Z.*spawn_(osc|effect)",
    # dpf_resources (DPF font/data objects Cardinal links)
    r"^dpf_resources",
    r"^_ZN13dpf_resources", r"^_ZT[ISV]N13dpf_resources",
    # libstdc++ C++-ABI internals (typeinfo/vtable of __cxxabiv1 classes)
    r"^_ZN10__cxxabiv1", r"^_ZT[ISV]N10__cxxabiv1",
    # surge library classes whose key functions live in surge objects outside
    # plugins.a (referenced via dynamic_cast from surgext's VCO/Looper TUs;
    # resolved by the surge archive at the final Cardinal link)
    r"^_ZT[ISV]10Oscillator$", r"^_ZT[ISV]15TwistOscillator$",
    r"^_ZTV10Oscillator$", r"^_ZTV15TwistOscillator$",
    r"^dejavusans_mono_ttf$",
    r"^dejavusans_ttf$",
    # rack internals Cardinal provides (subset not covered by data defs below)
    r"^_ZN4rack", r"^_ZNK4rack",
    r"^_ZT[ISV]N4rack",
    r"^rack::",
    # DGL's glow namespace (dpf objects Cardinal links)
    r"^_ZN4glow", r"^_ZNK4glow", r"^_ZT[ISV]N4glow", r"^glow::",
    # surge/sst/water/carla (surgext builds against Cardinal-provided deps at
    # the final link; surge objects live outside plugins.a too)
    r"^_ZN5surge", r"^_Z.*Surge", r"^_ZN9Parameter", r"^_Z.*Parameter",
    r"^_ZN19LFOModulationSource", r"^_ZN5water", r"^_Z.*water",
    r"^_ZN3sst", r"^_Z.*sst[0-9]", r"^_ZN16surgext",
    r"^_Z[0-9]*spawn_", r"^_Z.*SurgeStorage", r"^calculateFilterResponseCurve",
    r"^carla_", r"^_ZN25_CarlaPluginDiscovery",
    r"carla_getNative",     # mangled C++ wrappers
    r"^_ZN5carla",
    r"^_ZN3fmt",           # fmt lib (via Cardinal sysdeps)
    # quickjs (Cardinal sysdeps, JS_* / __JS_* symbols)
    r"^__?JS_", r"^JS_",
    # C/C++ runtime functions (libc + libstdc++ low level)
    r"^_Zda[Pm]", r"^_Zdl[Pm]", r"^_Zn[aw]m$", r"^_ZSt9terminate",
    # exp2/nextafterf/stpcpy: glibc
    r"^(exp2|nextafterf|stpcpy)$",
    # jsonp_* / nvglu internals come from jansson/nanovg Cardinal links
    r"^jsonp_",
    # nanovg / framebuffer
    r"^nvg", r"^nvglu", r"^nanovg",
    # Blendish (Cardinal provides bnd* at the final link)
    r"^bnd[A-Z]",
    # jansson
    r"^json_",
    # pffft, speex, samplerate (Cardinal sysdeps)
    r"^pffft_", r"^speex_", r"^src_(new|process|delete)",
    # aubio (Bidoo vendored)
    r"^aubio_", r"^(new|del)_(f?vec|aubio_pitch)$", r"^aubio",
    r"_aubio_pitch", r"^fvec_", r"^del_fvec$",
    # GL/glfw (only some plugins reference these under Cardinal's GL setup)
    r"^gl[A-Z]", r"^glfw",
    # nanosvg image loader
    r"^nsvg",
    # Optional C library calls: resolved by libc at the final link. The
    # archive cannot define these, so anything unresolved here is harmless.
    r"^(m|re)alloc$", r"^free$", r"^calloc$", r"^aligned_alloc$",
    r"^mem(cpy|move|set|cmp|chr)$", r"^str(len|cmp|cpy|cat|dup|chr|rchr|str|tod|tof|error|error_r|ncat|ncmp|ncpy|casestr|tok|ptime|pcpy)$",
    r"^(fopen|fclose|fread|fwrite|fseek|ftell|fgets|fgetc|fputs|fputc|fprintf|vfprintf|snprintf|sprintf|vsnprintf|printf|puts|putchar|fflush|feof|ferror|freopen|fseeko|ftello|rewind|remove|stat|lstat|mkdir|opendir|readdir|closedir|open|read|write|close|access|getenv|gettimeofday|time|localtime|mktime|nanosleep|usleep|rand|srand|qsort|exit|utime|clock|stderr|stdout|prctl|strftime|sysconf|__sysconf|socket|bind|listen|accept|setsockopt|shutdown|ldexp|expm1|exp2|exp2f|nextafterf|stpcpy)$",
    r"^(acos|asin|atan|atan2|cos|cosh|exp|fabs|floor|fmod|log|log10|log1p|log2|pow|sin|sinh|sqrt|tan|tanh|cbrt|hypot|fmin|fmax|fma|nearbyint|rint|round|roundeven|trunc|lgamma|tgamma|frexp|modf|sincos|csqrt|erf|j0|j1|y0|y1|acosh|asinh|atanh|expm1|ldexp)[hf]?$",
    r"^clogf$",
    r"^(isalnum|isalpha|isblank|iscntrl|isdigit|isgraph|islower|isprint|ispunct|isspace|isupper|isxdigit|tolower|toupper|localeconv)$",
    r"^__xpg_basename$", r"^dirname$",
    r"^wcsrtombs$", r"^strto(l|ul|ll|ull|d|f)$",
    # pthread
    r"^pthread_",
]

_EXTERNAL_RES = [re.compile(p) for p in EXTERNAL_PATTERNS]

# Symbols matching these patterns are *definitely* user-level and must be
# defined in the archive even though they start with _Z<digits> (the _Z[A-Z]
# external rule above would otherwise hide them, since user functions mangle
# as _Z<len><name> and len is a digit, e.g. _Z15getDefaultThemeb).
# C++-mangled USER-LEVEL symbols: the definition must exist in the archive
# (or in USER_MANGLED_EXTERNALS below) or the final link fails. Covers free
# functions (`_Z<digits><name>`), members/const-members/vtables/typeinfo of
# named classes (`_ZN<digits>...`, `_ZNK<digits>...`, `_ZT[ISV][0-9N]...`).
# NOTE: std::, rack::, glow:: etc. are matched EARLIER in is_external() via
# their specific namespace prefixes, so they never reach this check.
_MUST_CHECK_USER = re.compile(r"^_Z([0-9]|[NKL][0-9]|T[ISV][0-9N])")

# symbols the archive provides (any strong-ish def type)
DEF_TYPES = set("TWVBDRuCAiG")

# _Z<digits> symbols that are nevertheless Cardinal-provided (matched on the
# mangled form; the _MUST_CHECK_USER guard would otherwise force them into
# the missing bucket). Keep this list minimal and specific.
USER_MANGLED_EXTERNALS = re.compile(
    r"^_Z.*(async_dialog|nvglu|handleHostParameterDrag|carla_getNative|"
    r"spawn_(osc|effect)|CardinalPluginContext)"
)


def run_nm(archive):
    res = subprocess.run(
        ["nm", "-A", archive],
        capture_output=True, text=True, check=True,
    )
    undefined = {}   # symbol -> [objfiles]
    defined = {}     # symbol -> [(objfile, type)]
    for line in res.stdout.splitlines():
        if not line or line.endswith(":"):
            continue
        parts = line.split(":")
        # "plugins.a:file.cpp.o:0000000000000000 T symbol" (or "   U symbol")
        if len(parts) < 2:
            continue
        rest = parts[-1]
        objfile = parts[-2] if len(parts) >= 3 else parts[0]
        m = re.match(r"([0-9a-fA-F]*)\s+(.)\s+(\S+)$", rest)
        if not m:
            continue
        addr, t, sym = m.group(1), m.group(2), m.group(3)
        if t == "U":
            undefined.setdefault(sym, []).append(objfile)
        elif t in DEF_TYPES:
            defined.setdefault(sym, []).append((objfile, t))
    return undefined, defined


def is_external(sym):
    # 1. C++-mangled symbols provided by Cardinal at the final link
    if USER_MANGLED_EXTERNALS.match(sym):
        return True
    # 2. namespace/class-specific externals (std::, rack::, glow::, surge, …)
    for rex in _EXTERNAL_RES:
        if rex.match(sym):
            return True
    # 3. anything left that mangles as a length-prefixed USER symbol
    if _MUST_CHECK_USER.match(sym):
        return False
    # 4. legacy default: assume external unless proven user-level
    return True


def classify(undefined, defined):
    missing = {}     # sym -> [objs]
    resolved_extern = set()
    for sym, objs in undefined.items():
        if sym in defined:
            continue                       # resolved inside the archive
        if is_external(sym):
            resolved_extern.add(sym)
            continue
        missing[sym] = objs

    # duplicates: non-weak strong defs in >1 object (T/D/B/R). W/V (weak) and
    # C (common) merging is normal and fine.
    strong = "TDBR"
    dupes = {}
    for sym, locs in defined.items():
        strong_locs = [(o, t) for (o, t) in locs if t in strong]
        if len(strong_locs) > 1:
            # 'U'-resolved weak twins (W) alongside strong defs are normal
            # template instantiations? No — strong in 2 objects is an error.
            dupes[sym] = strong_locs
    return missing, dupes, len(resolved_extern)


def demangle_batch(syms):
    """Best-effort demangle via c++filt for readable output."""
    if not syms:
        return {}
    try:
        res = subprocess.run(["c++filt"], input="\n".join(syms),
                             capture_output=True, text=True, check=True)
        return dict(zip(syms, res.stdout.splitlines()))
    except (OSError, subprocess.CalledProcessError):
        return {s: s for s in syms}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive", default=os.path.join(REPO, "plugins", "plugins.a"))
    ap.add_argument("--json", help="write machine-readable report to this file")
    ap.add_argument("--filter", help="regex; show refs/dups involving matching objects only")
    ap.add_argument("--list-extern", action="store_true", help="dump classified-external syms")
    args = ap.parse_args()

    if not os.path.exists(args.archive):
        print(f"linkcheck: {args.archive} not found — run 'make -C plugins plugins.a' first",
              file=sys.stderr)
        return 2

    print(f"linkcheck: parsing {args.archive} …", file=sys.stderr)
    undefined, defined = run_nm(args.archive)
    print(f"linkcheck: {len(undefined)} undefined, {len(defined)} defined symbols",
          file=sys.stderr)

    missing, dupes, n_ext = classify(undefined, defined)

    filt = re.compile(args.filter) if args.filter else None

    if args.list_extern:
        for s in sorted(s for s in undefined if s not in defined and is_external(s)):
            print(s)
        return 0

    if filt:
        missing = {s: [o for o in objs if filt.search(o)] for s, objs in missing.items()}
        missing = {s: o for s, o in missing.items() if o}
        dupes = {s: l for s, l in dupes.items() if any(filt.search(o) for o, _ in l)}
        # for --filter, count refs only from matching objects
        for sym, objs in list(undefined.items()):
            if sym not in missing and sym not in defined:
                continue
        for sym in list(missing):
            if not missing[sym]:
                del missing[sym]

    ok = not missing and not dupes

    dem = demangle_batch(sorted(missing))

    if missing:
        print(f"\n== MISSING DEFINITIONS ({len(missing)}) — would fail the final link ==")
        for sym in sorted(missing, key=lambda s: (dem.get(s, s) or s).lower()):
            objs = sorted(set(missing[sym]))
            print(f"  {dem.get(sym, sym)}")
            for o in objs:
                print(f"      referenced from: {o}")

    if dupes:
        print(f"\n== DUPLICATE STRONG DEFINITIONS ({len(dupes)}) — would fail the final link ==")
        for sym in sorted(dupes, key=lambda s: (demangle_batch([s]).get(s, s) or s).lower()):
            print(f"  {dem.get(sym, sym)}")
            for o, t in sorted(dupes[sym]):
                print(f"      defined ({t}) in: {o}")

    if ok:
        print(f"\nlinkcheck: OK — archive is link-consistent "
              f"({n_ext} refs resolved externally, {len(defined)} defined)")
    else:
        print("\nlinkcheck: FAILED — see above; these will break the final Cardinal link")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({
                "ok": ok,
                "missing": {s: objs for s, objs in missing.items()},
                "duplicates": {s: [[o, t] for o, t in locs] for s, locs in dupes.items()},
                "external_count": n_ext,
                "undefined_count": len(undefined),
                "defined_count": len(defined),
            }, f, indent=2)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
