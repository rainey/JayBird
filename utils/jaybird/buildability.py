#!/usr/bin/env python3
# JayBird standalone-buildability sweep.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Determine which plugins (and, on failure, which modules) build on their own.

For each selectable plugin (from kconfig/Kconfig.gen), a transient Kconfig is
generated with only that plugin (or module) enabled, then `make plugins` is
run from a clean plugins/ build dir. Results are logged and summarized.

Never runs the top-level `make clean` (that would wipe deps/ and dpf/);
only `make clean -C plugins`, which keeps src/Rack/dep intact.

Usage:
  python3 utils/jaybird/buildability.py                # sweep all plugins
  python3 utils/jaybird/buildability.py --filter 21kHz # sweep matching plugins
  python3 utils/jaybird/buildability.py --drilldown    # per-module retries for failures
  python3 utils/jaybird/buildability.py --list         # just enumerate plugins
  python3 utils/jaybird/buildability.py --restore      # restore default selection

Output:
  buildability-logs/<test>.log        full build log per test
  buildability-logs/results.json      machine-readable results (resumable)
  buildability-logs/buildability.md   human-readable report
"""

import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGDIR = os.path.join(REPO, "buildability-logs")
RESULTS = os.path.join(LOGDIR, "results.json")
REPORT = os.path.join(LOGDIR, "buildability.md")

POLICY_SYMBOLS = ("ALLOW_GPL3_ONLY", "ALLOW_NC_ARTWORK", "STRICT_NO_PHONE_HOME")
ERROR_RE = re.compile(
    r"error:|fatal error|Error [0-9]|undefined reference|No rule to make target"
    r"|cannot find|not found, needed|overriding recipe|recipe for target .* failed",
    re.I,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def warn(msg):
    print(f"buildability: WARNING: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Enumeration

def ensure_kconfig_gen():
    """Kconfig.gen must exist; generate it (build-all is fine) if not."""
    gen = os.path.join(REPO, "kconfig", "Kconfig.gen")
    if not os.path.isfile(gen):
        run_make(["CONFIG=default", "jaybird-gen"], None)


def enumerate_plugins():
    """Parse Kconfig.gen menus: {dirn: {"plug": sym, "mods": [sym, ...]}}.

    Menu headers look like: menu "21kHz (21kHz)"  (dir name before " (").
    Only plugins present here are selectable under the active policy.
    """
    ensure_kconfig_gen()
    path = os.path.join(REPO, "kconfig", "Kconfig.gen")
    plugins = {}
    cur = None
    for line in open(path, errors="replace"):
        line = line.strip()
        m = re.match(r'menu "([^"]+)"$', line)
        if m:
            cur = m.group(1).rsplit(" (", 1)[0]
            plugins[cur] = {"plug": None, "mods": []}
            continue
        m = re.match(r"config ((?:PLUG|MOD)_[A-Za-z0-9_]+)$", line)
        if m and cur is not None:
            if m.group(1).startswith("PLUG_"):
                plugins[cur]["plug"] = m.group(1)
            else:
                plugins[cur]["mods"].append(m.group(1))
    return {d: p for d, p in plugins.items() if p["plug"]}


# ---------------------------------------------------------------------------
# Config generation

def load_kconfig():
    sys.path.insert(0, os.path.join(REPO, "kconfig"))
    os.environ["KCONFIG_CONFIG"] = os.path.join(
        REPO, "kconfig", "configs", "default.config")
    os.environ["srctree"] = os.path.join(REPO, "kconfig")
    import kconfiglib
    kconf = kconfiglib.Kconfig("Kconfig")
    kconf.load_config(os.path.join(REPO, "kconfig", "configs", "default.config"))
    return kconf


def write_scratch_config(kconf, dirn, only_mod=None):
    """Write kconfig/configs/scratch-<dirn>.config with a minimal selection.

    All PLUG_* off except the target; target's modules on, or (when
    `only_mod` is set) just that one module with its siblings off.
    """
    name = "scratch-" + re.sub(r"[^A-Za-z0-9_.-]", "_", dirn)
    path = os.path.join(REPO, "kconfig", "configs", name + ".config")

    for pname, sym in kconf.syms.items():
        if pname in POLICY_SYMBOLS:
            continue
        if pname.startswith("PLUG_"):
            sym.set_value("n")
        elif pname.startswith("MOD_"):
            sym.set_value("n")

    plug = "PLUG_" + _sym_suffix(dirn)
    if plug not in kconf.syms:
        raise KeyError(f"no symbol {plug} (plugin '{dirn}' not selectable?)")
    kconf.syms[plug].set_value("y")
    for mod in PLUGIN_INFO[dirn]["mods"]:
        if only_mod is None or mod == only_mod:
            kconf.syms[mod].set_value("y")

    kconf.write_config(path)
    return name, path


def _sym_suffix(dirn):
    """Mirror gen.py's kconfig_symbol(): dir name to symbol suffix."""
    return re.sub(r"[^A-Za-z0-9]", "_", dirn).upper()


# ---------------------------------------------------------------------------
# Build execution

def run_make(args, log_file, timeout=None):
    cmd = ["make", "-j", str(JOBS)] + args
    env = dict(os.environ)
    env.pop("MAKEFLAGS", None)  # don't inherit -j from the sweep's own invocation
    try:
        proc = subprocess.run(
            cmd, cwd=REPO, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace")
        if log_file:
            with open(log_file, "w") as f:
                f.write(proc.stdout)
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as e:
        if log_file and e.output:
            with open(log_file, "w") as f:
                f.write(e.output if isinstance(e.output, str) else e.output.decode("utf-8", "replace"))
        return -9, ""


def extract_errors(log):
    hits = [l for l in log.splitlines() if ERROR_RE.search(l)]
    seen, uniq = set(), []
    for l in hits:
        k = l.strip()[:160]
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq[:15]


def test_selection(kconf, dirn, only_mod=None):
    """Generate config, regenerate build inputs, clean plugins/, build."""
    name, path = write_scratch_config(kconf, dirn, only_mod)
    label = f"{name}" + (f":{only_mod}" if only_mod else "")

    rc, _ = run_make([f"CONFIG={name}", "jaybird-gen"], None)
    if rc != 0:
        return {"result": "gen-failed", "name": name, "errors": ["jaybird-gen failed"]}

    rc, _ = run_make(["clean", "-C", "plugins"], None)
    if rc != 0:
        return {"result": "clean-failed", "name": name, "errors": ["make clean -C plugins failed"]}

    logfile = os.path.join(LOGDIR, name + ".log")
    t0 = time.monotonic()
    # Only the main archive: `make plugins` would additionally build
    # plugins-mini.a/-headless (upstream mini selection, never filtered),
    # which is irrelevant to per-plugin buildability.
    rc, out = run_make(["-C", "plugins", "plugins.a"], logfile, timeout=BUILD_TIMEOUT)
    dur = time.monotonic() - t0

    entry = {"name": name, "result": "ok" if rc == 0 else "failed",
             "time": round(dur, 1)}
    if rc != 0:
        entry["errors"] = extract_errors(out) or ["no recognizable error line; see log"]
    return entry


# ---------------------------------------------------------------------------
# Results / reporting

def load_results():
    if os.path.isfile(RESULTS):
        with open(RESULTS) as f:
            return json.load(f)
    return {"plugins": {}, "modules": {}}


def save_results(res):
    with open(RESULTS, "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)


def write_report(res, plugin_info):
    lines = ["# JayBird standalone buildability", "",
             f"Jobs: {JOBS} &middot; build target: `make CONFIG=scratch-* plugins`",
             ""]
    order = sorted(res["plugins"], key=lambda d: (res["plugins"][d]["result"], d))
    nok = sum(1 for d in order if res["plugins"][d]["result"] == "ok")
    lines += [f"**Plugins: {nok} ok, {len(order) - nok} failed**", "",
              "| plugin | result | time | errors |",
              "|---|---|---|---|"]
    for d in order:
        p = res["plugins"][d]
        errs = "<br>".join("`" + e.replace("|", "\\|").replace("`", "'") + "`"
                           for e in p.get("errors", [])) or ""
        lines.append(f"| {d} | {p['result']} | {p.get('time', '')} | {errs} |")

    if res["modules"]:
        lines += ["", "## Per-module drilldown (failing plugins)", ""]
        for d in sorted(res["modules"]):
            lines.append(f"### {d}", )
            lines += ["| module | result | time | errors |", "|---|---|---|---|"]
            mods = res["modules"][d]
            n_ok = sum(1 for m in mods.values() if m["result"] == "ok")
            lines.append(f"**{n_ok}/{len(mods)} modules ok**", "")
            for slug, m in sorted(mods.items()):
                errs = "<br>".join("`" + e.replace("|", "\\|").replace("`", "'") + "`"
                                   for e in m.get("errors", [])) or ""
                lines.append(f"| {slug} | {m['result']} | {m.get('time', '')} | {errs} |")
            lines.append("")
    with open(REPORT, "w") as f:
        f.write("\n".join(lines) + "\n")


def restore():
    for fn in os.listdir(os.path.join(REPO, "kconfig", "configs")):
        if fn.startswith("scratch-"):
            os.unlink(os.path.join(REPO, "kconfig", "configs", fn))
    run_make(["CONFIG=default", "jaybird-gen"], None)
    print("buildability: restored default selection")


# ---------------------------------------------------------------------------

def main():
    global JOBS, PLUGIN_INFO, BUILD_TIMEOUT
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--filter", help="regex on plugin dir name (sweep phase)")
    ap.add_argument("--drilldown", action="store_true",
                    help="for failed plugins, retest each module alone")
    ap.add_argument("--force", action="store_true",
                    help="retest plugins already recorded in results.json")
    ap.add_argument("--timeout", type=int, default=3600,
                    help="per-build timeout in seconds (default 3600)")
    ap.add_argument("--list", action="store_true", help="enumerate and exit")
    ap.add_argument("--keep", action="store_true",
                    help="keep scratch configs instead of restoring")
    ap.add_argument("--restore", action="store_true",
                    help="only restore the default selection and exit")
    args = ap.parse_args()

    JOBS = args.jobs
    BUILD_TIMEOUT = args.timeout

    if args.restore:
        restore()
        return

    PLUGIN_INFO = enumerate_plugins()

    if args.list:
        for d in sorted(PLUGIN_INFO):
            print(f"{d}  ({len(PLUGIN_INFO[d]['mods'])} modules)")
        return

    os.makedirs(LOGDIR, exist_ok=True)
    res = load_results()
    kconf = load_kconfig()
    flt = re.compile(args.filter) if args.filter else None

    # ---- sweep phase
    for dirn in sorted(PLUGIN_INFO):
        if flt and not flt.search(dirn):
            continue
        done = res["plugins"].get(dirn)
        if done and done["result"] == "ok" and not args.force:
            print(f"[skip] {dirn} (already ok)")
            continue
        print(f"[plugin] {dirn} ...", flush=True)
        entry = test_selection(kconf, dirn)
        res["plugins"][dirn] = entry
        save_results(res)
        print(f"         {entry['result']} ({entry.get('time', '?')}s)")

    # ---- drilldown phase
    if args.drilldown:
        for dirn, entry in sorted(res["plugins"].items()):
            if entry["result"] == "ok" or not PLUGIN_INFO.get(dirn, {}).get("mods"):
                continue
            if flt and not flt.search(dirn):
                continue
            mods = PLUGIN_INFO[dirn]["mods"]
            print(f"[drilldown] {dirn}: {len(mods)} modules", flush=True)
            for mod in mods:
                done = res["modules"].get(dirn, {}).get(mod)
                if done and done["result"] == "ok" and not args.force:
                    continue
                e = test_selection(kconf, dirn, only_mod=mod)
                res["modules"].setdefault(dirn, {})[mod] = e
                save_results(res)
                print(f"   {mod}: {e['result']} ({e.get('time', '?')}s)")

    write_report(res, PLUGIN_INFO)
    print(f"buildability: report written to {REPORT}")

    if not args.keep:
        restore()


if __name__ == "__main__":
    main()
