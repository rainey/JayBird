#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate a draft kconfig/manifest.yaml from submodule metadata.

Only the fields that need human judgment live in the manifest: artwork
license and phone-home. Code licenses are derived at generation time from
plugin.json (see licensing.py).

Run from the repository root:
  python3 utils/jaybird/gen_manifest.py [--out kconfig/manifest.yaml]
"""

import configparser
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from licensing import detect_code_license  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Submodules that are not plugins
NON_PLUGINS = ("src/Rack", "dpf", "carla")


def parse_artwork_licenses():
    """Parse docs/LICENSES.md artwork table into {plugin_dir_name: (default, notes, exceptions)}.

    Table rows look like: | AaronStatic/fonts/PixelOperator.ttf | CC0-1.0 | note |
    The first path component is the plugin directory name. The '<Plugin>/*' row
    (when present) is that plugin's default artwork license; other rows are
    per-file exceptions.
    """
    table = os.path.join(REPO, "docs", "LICENSES.md")
    plugins = {}
    try:
        lines = open(table, errors="replace").read().splitlines()
    except OSError:
        return plugins
    in_plugins = False
    for line in lines:
        if line.startswith("### Plugins"):
            in_plugins = True
            continue
        if in_plugins and line.startswith("### "):
            break
        if not in_plugins or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("Name", "") or set(cells[0]) <= {"-", " "}:
            continue
        path_cell, lic = cells[0], cells[1]
        parts = path_cell.split("/")
        if len(parts) < 2:
            continue
        name = parts[0]
        rest = "/".join(parts[1:])
        note = cells[2] if len(cells) > 2 else ""
        entry = plugins.setdefault(name, {"default": None, "exceptions": []})
        if rest == "*":
            if entry["default"] is None:
                entry["default"] = lic
        else:
            entry["exceptions"].append((rest, lic, note))
    return plugins


def submodules():
    cp = configparser.ConfigParser()
    cp.read(os.path.join(REPO, ".gitmodules"))
    for sec in cp.sections():
        path = cp.get(sec, "path", fallback=None)
        if path and path.startswith("plugins/") and path.count("/") == 1:
            yield path


def main():
    out_path = os.path.join(REPO, sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
        else os.path.join(REPO, "kconfig", "manifest.yaml")

    artwork = parse_artwork_licenses()
    entries, n_ok, n_sniff, n_fail = [], 0, 0, 0
    for path in sorted(submodules()):
        plugin_dir = os.path.join(REPO, path)
        if not os.path.isdir(plugin_dir):
            print(f"MISSING (submodule not checked out): {path}", file=sys.stderr)
            n_fail += 1
            continue

        code_license, _gpl3_only, source = detect_code_license(plugin_dir)
        if code_license in (None, "GPL-3.0-only?"):
            n_fail += 1
        elif source == "LICENSE sniff":
            n_sniff += 1
        else:
            n_ok += 1

        art = artwork.get(os.path.basename(path), {})
        entries.append({
            "path": path,
            "artwork_license": art.get("default"),
            "artwork_exceptions": len(art.get("exceptions", [])),
        })

    def y(v):
        """YAML-safe scalar: native null for None, repr for strings."""
        return "null" if v is None else repr(v)

    lines = [
        "# JayBird plugin license manifest — DRAFT, requires human curation.",
        "#",
        "# Fields:",
        "#   path:            submodule path (key; must cover every plugins/* submodule)",
        "#   artwork_license: SPDX id or description of panel art license (TODO: fill in)",
        "#   phone_home:      true if the module performs any online access (TODO: verify)",
        "#",
        "# Code licenses are derived from plugin.json at generation time, not stored here.",
        "# Entries with null/TODO values need review.",
    ]
    for e in entries:
        lines.append("")
        lines.append(f"# {e['path']}")
        lines.append(f"{e['path']}:")
        lines.append(f"  artwork_license: {y(e['artwork_license'])}")
        if e["artwork_exceptions"]:
            lines.append(f"  # per-file artwork exceptions listed in docs/LICENSES.md: {e['artwork_exceptions']}")
        lines.append("  phone_home: null  # TODO")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {out_path}")
    print(f"coverage: {n_ok} from plugin.json, {n_sniff} sniffed, {n_fail} unresolved")


if __name__ == "__main__":
    main()
