#!/usr/bin/env python3
# JayBird module-selection generator.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate Kconfig fragments and filtered build inputs from:
  - kconfig/manifest.yaml           (per-plugin license data, hand-curated)
  - plugins/*/plugin.json           (module slugs/names, live submodule data)
  - plugins/plugins.cpp             (upstream registration template)
  - the selected .config            (module selection)

Outputs:
  kconfig/Kconfig.gen               (per-plugin/per-module menu fragments)
  plugins/plugins-jaybird.cpp       (filtered registration file)
  kconfig/gen/stamp                 (build freshness marker)

Usage:
  python3 utils/jaybird/gen.py [CONFIG_PATH]     # default: kconfig/configs/default.config

If CONFIG_PATH does not exist, generation is build-all (upstream-equivalent).
"""

import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Plugins whose module collection must always be registered (host plumbing).
ALWAYS_ON = {"Cardinal", "Fundamental"}

# Dead registration blocks (commented out upstream) — never selectable.
# ParableInstruments: shares ArableInstruments sources with -DPARASITES
# (modelClouds -> "Neil"); registration left untouched in v1.
KNOWN_UNSELECTABLE = {"ZamAudio", "ParableInstruments"}

SPL_RE = re.compile(r'const StaticPluginLoader spl\(p, "([^"]+)"\);')
ADDMODEL_RE = re.compile(r'^\s*p->addModel\(([\w:]+)\);')
REMMODULE_RE = re.compile(r'spl\.removeModule\("([^"]+)"\)')

# `Model* name = createModel<..>("Slug")` — tolerates namespace-qualified
# (`bogaudio::createModel`), wrapper functions (`createSapphireModel`),
# multi-line definitions (`rack::Model *x =\n rack::createModel<..>(..)`),
# and captures the first string argument as the slug.
CREATEMODEL_RE = re.compile(
    r'Model\s*\*\s*(\w+)\s*=\s*[\w:]*create\w*Model\s*<[^;]*?>\s*\([^;]*?"([^"]+)"',
    re.S,
)


def warn(msg):
    print(f"jaybird: WARNING: {msg}", file=sys.stderr)


def load_manifest():
    sys.path.insert(0, os.path.join(REPO, "kconfig"))
    try:
        import yaml
    except ImportError:
        warn("PyYAML not available; manifest license filters disabled")
        return {}
    with open(os.path.join(REPO, "kconfig", "manifest.yaml")) as f:
        return yaml.safe_load(f) or {}


def load_plugin_info(path):
    """Returns (slug, [(module_slug, module_name), ...]) or None."""
    plugin_dir = os.path.join(REPO, path)
    for cand in ("plugin.json", "res/plugin.json"):
        pj = os.path.join(plugin_dir, cand)
        if os.path.isfile(pj):
            try:
                j = json.load(open(pj))
            except Exception as e:
                warn(f"{path}: plugin.json parse error: {e}")
                return None
            slug = j.get("slug") or os.path.basename(path)
            modules = [(m.get("slug"), m.get("name") or m.get("slug"))
                       for m in j.get("modules", []) if m.get("slug")]
            return slug, modules
    return None


def scan_model_slugs(path, prefer=()):
    """Scan plugin sources for `Model* x = createModel<..>("Slug")`.

    Returns {identifier: slug}. Namespaced identifiers are keyed by their
    final component (matches how plugins.cpp references them). Some plugins
    define the same symbol under #ifdef variants (#ifdef SM_PRO etc.) with
    different slugs; when that happens, a slug present in `prefer` (the
    plugin.json module list) wins, since that is the variant Cardinal
    actually builds.

    Slug arguments may be string constants (`#define SLUG "atoms"`,
    `constexpr auto SlugFolding {"ACFolding"}`); same-file definitions take
    precedence, then tree-wide ones.
    """
    plugin_dir = os.path.join(REPO, path)

    literal_re = re.compile(
        r'Model\s*\*\s*(\w+)\s*=\s*[\w:]*create\w*Model\s*<[^;]*?>\s*\(\s*"([^"]+)"',
        re.S,
    )
    const_re = re.compile(
        r'Model\s*\*\s*(\w+)\s*=\s*[\w:]*create\w*Model\s*<[^;]*?>\s*\(\s*([A-Za-z_]\w*)\s*[,)]',
        re.S,
    )
    define_re = [
        re.compile(r'#define\s+(\w+)\s+"([^"]+)"'),
        re.compile(r'constexpr\s+auto\s+(\w+)\s*\{\s*"([^"]+)"\s*\}'),
        re.compile(r'const\s+(?:char\s*\*|auto)\s+(\w+)\s*(?:\[\])?\s*=\s*"([^"]+)"'),
    ]

    matches = []          # (ident, slug_or_None, const_name, file_consts)
    consts = {}           # global constant map

    for root, dirs, files in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if d not in ("dep", "libs", ".git")]
        for fn in files:
            if not fn.endswith((".cpp", ".cc", ".hpp", ".h", ".c")):
                continue
            fp = os.path.join(root, fn)
            try:
                text = open(fp, errors="replace").read()
            except OSError:
                continue

            fconsts = {}
            for dr in define_re:
                for m in dr.finditer(text):
                    fconsts.setdefault(m.group(1), m.group(2))
            consts.update(fconsts)

            for m in literal_re.finditer(text):
                matches.append((m.group(1).split("::")[-1], m.group(2), None, fconsts))
            for m in const_re.finditer(text):
                matches.append((m.group(1).split("::")[-1], None, m.group(2), fconsts))

    out = {}
    for ident, slug, cname, fconsts in matches:
        if slug is None and cname is not None:
            # same-file definition first, then tree-wide
            slug = fconsts.get(cname) or consts.get(cname)
        if slug is None:
            continue
        prev = out.get(ident)
        if prev is not None and prev != slug:
            if slug in prefer:
                out[ident] = slug
            elif prev not in prefer:
                warn(f"{path}: symbol {ident} maps to multiple slugs "
                     f"({prev} vs {slug}); keeping first")
            continue
        out[ident] = slug

    out.update(scan_macro_tables(plugin_dir, prefer))
    return out


# Macro table pattern, e.g. surgext's:
#   #define FXMODEL(type, nm)  rack::Model *modelFX##nm = rack::createModel<..>(
#       std::string("SurgeXTFX") + #nm);
#   FXMODEL(fxt_reverb, Reverb);
MACRO_TABLE_RE = re.compile(
    r'#define\s+(\w+)\(([^)]*)\)\s*((?:.*\\\n)+.*)\n', re.S)
MACRO_MODEL_RE = re.compile(
    r'[\w:]*Model\s*\*\s*([\w#]+)##(\w+)\s*=\s*[\w:]*create\w*Model\s*<[^;]*?>\s*\('
    r'[^;]*?"([^"]+)"\s*\)?\s*\+\s*#(\w+)')


def scan_macro_tables(plugin_dir, prefer):
    """Resolve registration macros that instantiate models via ## concatenation."""
    out = {}
    for root, dirs, files in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if d not in ("dep", "libs", ".git")]
        for fn in files:
            if not fn.endswith((".cpp", ".cc", ".hpp", ".h", ".c")):
                continue
            fp = os.path.join(root, fn)
            try:
                text = open(fp, errors="replace").read()
            except OSError:
                continue
            for dm in MACRO_TABLE_RE.finditer(text):
                name, params, body = dm.group(1), dm.group(2), dm.group(3)
                mm = MACRO_MODEL_RE.search(body)
                if not mm:
                    continue
                ident_prefix, param_ident, slug_prefix, slug_param = \
                    mm.group(1), mm.group(2), mm.group(3), mm.group(4)
                if param_ident != slug_param:
                    continue
                for im in re.finditer(rf'\b{name}\(([^)]*)\)\s*;', text):
                    args = [a.strip() for a in im.group(1).split(",")]
                    pidx = next((i for i, p in enumerate(
                        [p.strip() for p in params.split(",")])
                        if p.split()[-1] == slug_param), None)
                    if pidx is None or pidx >= len(args):
                        continue
                    out[ident_prefix + args[pidx]] = slug_prefix + args[pidx]
    return out


def parse_plugins_cpp():
    """Parse upstream plugins.cpp into registration blocks.

    Returns (src_lines, blocks) where each block is:
      {slug, start, spl_line, adds: [(line_idx, symbol)], end}
    """
    src_path = os.path.join(REPO, "plugins", "plugins.cpp")
    with open(src_path) as f:
        lines = f.read().splitlines()

    blocks, cur = [], None
    for i, line in enumerate(lines):
        m = SPL_RE.search(line)
        if m:
            cur = {"slug": m.group(1), "spl_line": i, "adds": [], "end": i}
            blocks.append(cur)
            continue
        if cur is None:
            continue
        if re.match(r'static void initStatic__', line):
            cur["end"] = i - 1
            cur = None
            continue
        a = ADDMODEL_RE.match(line)
        if a:
            cur["adds"].append((i, a.group(1)))
    if cur is not None:
        cur["end"] = len(lines) - 1
    return lines, blocks


def kconfig_symbol(s):
    return re.sub(r"[^A-Za-z0-9]", "_", s).upper()


def generate_kconfig_gen(manifest, plugins, blocks_by_slug, model_slugs):
    """Emit kconfig/Kconfig.gen. plugins: {spl_slug: (dir, slug, modules)}."""
    out = ["# GENERATED by utils/jaybird/gen.py — do not edit by hand.",
           "# Regenerate via `make jaybird-gen`.",
           ""]
    stats, seen_dirs = [], set()
    for spl_slug in sorted(plugins):
        path, slug, modules = plugins[spl_slug]
        if spl_slug in ALWAYS_ON or path in seen_dirs:
            continue
        seen_dirs.add(path)
        block = blocks_by_slug.get(spl_slug)
        m = manifest.get("plugins/" + path, {})
        psym = "PLUG_" + kconfig_symbol(path.replace("plugins/", ""))
        deps = []
        if m.get("gpl3_only") is True:
            deps.append("ALLOW_GPL3_ONLY")
        art = m.get("artwork_license") or ""
        if "NC" in art or art == "Custom":
            deps.append("ALLOW_NC_ARTWORK")
        if m.get("phone_home") is True:
            deps.append("!STRICT_NO_PHONE_HOME")

        out.append(f'menu "{spl_slug} ({path})"')
        if m:
            out.append(f'\tcomment "code: {m.get("code_license")}  artwork: {art or "unlisted"}"')
        out.append(f"config {psym}")
        out.append(f'\tbool "{spl_slug}"')
        out.append("\tdefault y")
        for d in deps:
            out.append(f"\tdepends on {d}")
        if block is None:
            out.append("\t# registration block not parseable; plugin-level switch only")
        registered = set()
        if block:
            model_map = model_slugs.get(path) or scan_model_slugs(path)
            sym_to_slug = {}
            for _, sym in block["adds"]:
                s = model_map.get(sym.split("::")[-1])
                if s:
                    sym_to_slug[sym] = s
                    registered.add(s)
            # Selectable modules = resolved registrations; plugin.json
            # supplies display names (some registered models are absent
            # from plugin.json, e.g. Bogaudio test modules).
            json_names = {ms: n for ms, n in modules}
            used_syms = list(sym_to_slug)
            if len(used_syms) != len(block["adds"]):
                unmatched = [sym for _, sym in block["adds"] if sym not in sym_to_slug]
                warn(f"{path}: {len(unmatched)} addModel symbols unresolved "
                     f"({', '.join(unmatched[:5])}); those stay always-registered")
            if used_syms:
                out.append("if " + psym)
                for sym in used_syms:
                    ms = sym_to_slug[sym]
                    name = json_names.get(ms) or ms
                    fsym = f"MOD_{psym[5:]}_{kconfig_symbol(ms)}"
                    out.append(f"config {fsym}")
                    out.append(f'\tbool "{name}"')
                    out.append(f"\tdefault {psym}")
                    out.append(f"\tdepends on {psym}")
                out.append("endif")
        out.append("endmenu")
        stats.append((path, spl_slug, len(registered), len(modules)))

    with open(os.path.join(REPO, "kconfig", "Kconfig.gen"), "w") as f:
        f.write("\n".join(out) + "\n")
    return stats


def load_selection(config_path):
    """Returns {symbol: bool} using kconfiglib; None if no config (build-all)."""
    if not os.path.isfile(config_path):
        return None
    sys.path.insert(0, os.path.join(REPO, "kconfig"))
    os.environ["KCONFIG_CONFIG"] = os.path.abspath(config_path)
    os.environ["srctree"] = os.path.join(REPO, "kconfig")
    import kconfiglib
    kconf = kconfiglib.Kconfig("Kconfig")
    kconf.load_config(os.path.abspath(config_path))
    sel = {}
    for name, sym in kconf.syms.items():
        val = sym.str_value
        sel[name] = (val == "y" or val == "m")
    return sel


def generate_build_input(lines, blocks, plugins, sel):
    """Transform upstream plugins.cpp per selection. Returns new source text."""
    # Single ordered pass: for each original line index, either drop it,
    # keep it, or keep it with extra lines appended (removeModule calls).
    keep = {}       # line_idx -> True
    append = {}     # line_idx -> [extra lines]

    n_plugins_off = n_modules_off = 0
    for block in blocks:
        spl_slug = block["slug"]
        if spl_slug in ALWAYS_ON:
            continue
        entry = plugins.get(spl_slug)
        if entry is None:
            continue  # not selectable (no manifest/plugin.json) — leave as-is
        path, slug, modules = entry
        psym = "PLUG_" + kconfig_symbol(path.replace("plugins/", ""))
        model_map = plugins_model_slugs.get(path, {})
        if sel is None:
            plug_on, mod_on = True, {}
        else:
            plug_on = sel.get(psym, True)
            mod_on = {}
            for _, sym in block["adds"]:
                ms = model_map.get(sym.split("::")[-1])
                if ms:
                    fsym = f"MOD_{psym[5:]}_{kconfig_symbol(ms)}"
                    mod_on[sym] = sel.get(fsym, True)
        if plug_on:
            to_remove = {sym for sym, on in mod_on.items() if not on}
            if to_remove:
                n_modules_off += len(to_remove)
                slugs = []
                for i, sym in block["adds"]:
                    if sym in to_remove:
                        keep[i] = False
                        ms = model_map.get(sym.split("::")[-1])
                        if ms:
                            slugs.append(ms)
                if slugs:
                    append.setdefault(block["spl_line"], []).extend(
                        f'    spl.removeModule("{s}");' for s in slugs)

            # After a submodule pin bump the manifest (plugin.json) can list
            # modules the registration never addModel()s; Rack's
            # Plugin::modulesFromJson throws on unregistered manifest
            # entries. Emit removeModule for every manifest slug not covered
            # by a kept registration. Blocks with no direct addModel lines
            # register via helper-init functions and are skipped.
            if len(block["adds"]) > 0:
                kept_slugs = set()
                for i, sym in block["adds"]:
                    if keep.get(i, True) is False:
                        continue
                    ms = model_map.get(sym.split("::")[-1])
                    if ms:
                        kept_slugs.add(ms)
                known_slugs = {ms for ms, _ in modules}
                unregistered = known_slugs - kept_slugs
                if unregistered:
                    extra = [f'    spl.removeModule("{s}");'
                             for s in sorted(unregistered)]
                    existing = append.setdefault(block["spl_line"], [])
                    existing.extend(x for x in extra if x not in existing)
        else:
            n_plugins_off += 1
            for i, sym in block["adds"]:
                keep[i] = False
            # modulesFromJson requires a registered model per manifest
            # entry, so strip every mapped module of a deselected plugin.
            slugs = sorted({model_map[sym.split("::")[-1]]
                            for _, sym in block["adds"]
                            if sym.split("::")[-1] in model_map})
            if slugs:
                append.setdefault(block["spl_line"], []).extend(
                    f'    spl.removeModule("{s}");' for s in slugs)

    out = []
    for i, line in enumerate(lines):
        if keep.get(i, True) is False:
            continue
        out.append(line)
        if i in append:
            out.extend(append[i])

    header = [
        "/* GENERATED by utils/jaybird/gen.py — do not edit by hand.",
        f" * config: {'build-all (no selection config)' if sel is None else config_path}",
        f" * plugins deselected: {n_plugins_off}, modules deselected: {n_modules_off}",
        " */",
    ]
    return "\n".join(header + out) + "\n"


# Filled during main(): spl_slug path -> {ident: slug}
plugins_model_slugs = {}


def main():
    global config_path
    config_path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(REPO, "kconfig", "configs", "default.config")

    manifest = load_manifest()
    lines, blocks = parse_plugins_cpp()
    blocks_by_slug = {b["slug"]: b for b in blocks}

    # Join spl slugs (== submodule dir names) to manifest/plugin.json data.
    plugins = {}
    for path in sorted(manifest):
        if not path.startswith("plugins/"):
            continue
        info = load_plugin_info(path)
        if not info:
            warn(f"{path}: no plugin.json; not selectable")
            continue
        slug, modules = info
        dirn = path[len("plugins/"):]
        plugins.setdefault(dirn, (dirn, slug, modules))
        plugins_model_slugs[dirn] = scan_model_slugs(
            path, prefer={ms for ms, _ in modules})

    stats = generate_kconfig_gen(manifest, plugins, blocks_by_slug, plugins_model_slugs)
    sel = load_selection(config_path)
    text = generate_build_input(lines, blocks, plugins, sel)

    out_path = os.path.join(REPO, "plugins", "plugins-jaybird.cpp")
    with open(out_path, "w") as f:
        f.write(text)

    os.makedirs(os.path.join(REPO, "kconfig", "gen"), exist_ok=True)
    with open(os.path.join(REPO, "kconfig", "gen", "stamp"), "w") as f:
        f.write("generated\n")

    selectable = [b for b in blocks
                  if b["slug"] in plugins and b["slug"] not in ALWAYS_ON]
    mode = "build-all" if sel is None else "selected"
    n_mod = sum(len(b["adds"]) for b in selectable)
    print(f"jaybird: Kconfig.gen written ({len(stats)} selectable plugins, "
          f"{n_mod} registrable modules)")
    print(f"jaybird: {out_path} written ({mode})")

    # Coverage guard: every spl block should be joinable to the manifest.
    missing = [b["slug"] for b in blocks
               if b["slug"] not in plugins
               and b["slug"] not in ALWAYS_ON]
    missing = [m for m in missing if m not in KNOWN_UNSELECTABLE]
    if missing:
        warn("spl blocks without manifest/plugin.json entry "
             "(left unfiltered): " + ", ".join(missing))


if __name__ == "__main__":
    main()
