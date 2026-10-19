#!/usr/bin/env python3
# JayBird manifest bootstrap: scrape per-plugin license metadata into a draft
# manifest for human curation. SPDX-License-Identifier: GPL-3.0-or-later
"""Generate a draft kconfig/manifest.yaml from submodule metadata.

Data sources, in priority order per field:
  code_license:  plugin.json "license" field, else LICENSE file sniff
  gpl3_only:     derived from code_license
  artwork_license: always left as TODO (needs human judgment; see docs/LICENSES.md)
  phone_home:    always left as TODO (needs human judgment)

Run from the repository root:
  python3 utils/jaybird/gen_manifest.py [--out kconfig/manifest.yaml]
"""

import configparser
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Submodules that are not plugins
NON_PLUGINS = ("src/Rack", "dpf", "carla")

LICENSE_SNIFFS = [
    (r"GNU General Public License.*version 3.*any later version", "GPL-3.0-or-later"),
    (r"GNU General Public License", "GPL-3.0-only?"),  # GPL text w/o or-later
    (r"Permission is hereby granted, free of charge", "MIT"),
    (r"Redistribution and use in source and binary forms", "BSD?"),
    (r"Apache License", "Apache-2.0"),
    (r"Creative Commons", "CC?"),
    (r"public domain", "Unlicense?"),
]


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


def find_plugin_json(plugin_dir):
    for cand in ("plugin.json", "res/plugin.json"):
        p = os.path.join(plugin_dir, cand)
        if os.path.isfile(p):
            return p
    return None


def sniff_license(plugin_dir):
    for name in sorted(os.listdir(plugin_dir)):
        if not re.match(r"LICENSE|LICENCE|COPYING", name, re.I):
            continue
        try:
            text = open(os.path.join(plugin_dir, name), errors="replace").read(4096)
        except OSError:
            continue
        for pat, lic in LICENSE_SNIFFS:
            if re.search(pat, text, re.S | re.I):
                return lic + f" (sniffed from {name})"
    return None


def normalize(license_str):
    """Classify a plugin.json license string; returns (spdx, gpl3_only)."""
    s = license_str.strip()
    is_or_later = bool(re.search(r"or[- ]later|\bGPL\+|\bGPL\d?\+", s, re.I))
    if re.search(r"GPL-?3|GPLv?3", s, re.I):
        return "GPL-3.0-or-later" if is_or_later else "GPL-3.0-only", not is_or_later
    if re.search(r"GPL-?2|GPLv?2", s, re.I):
        return ("GPL-2.0-or-later", False) if is_or_later else ("GPL-2.0-only", None)
    return s, None


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

        slug, modules, license_field = None, None, None
        pj = find_plugin_json(plugin_dir)
        if pj:
            j = json.load(open(pj))
            slug = j.get("slug")
            modules = len(j.get("modules", []))
            license_field = j.get("license")

        source = "plugin.json"
        if license_field:
            code_license, gpl3_only = normalize(license_field)
        else:
            code_license, gpl3_only = sniff_license(plugin_dir), None
            source = "LICENSE sniff"

        if code_license in (None, "GPL-3.0-only?"):
            n_fail += 1
        elif source == "LICENSE sniff":
            n_sniff += 1
        else:
            n_ok += 1

        art = artwork.get(os.path.basename(path), {})
        entries.append({
            "path": path,
            "slug": slug,
            "modules": modules,
            "code_license": code_license,
            "gpl3_only": gpl3_only,
            "artwork_license": art.get("default"),
            "artwork_exceptions": len(art.get("exceptions", [])),
            "phone_home": None,
            "license_source": source,
        })

    def y(v):
        """YAML-safe scalar: native null for None, repr for strings."""
        return "null" if v is None else repr(v)

    lines = [
        "# JayBird plugin license manifest — DRAFT, requires human curation.",
        "#",
        "# Fields:",
        "#   path:            submodule path (key; must cover every plugins/* submodule)",
        "#   slug:            plugin slug from plugin.json (reference)",
        "#   modules:         module count from plugin.json (reference, regenerated)",
        "#   code_license:    SPDX id of the plugin code",
        "#   gpl3_only:       true if GPL-3.0-only (needs ALLOW_GPL3_ONLY to include)",
        "#   artwork_license: SPDX id or description of panel art license (TODO: fill in)",
        "#   phone_home:      true if the module performs any online access (TODO: verify)",
        "#   license_source:  where code_license came from (auto-generated, keep for audit)",
        "#",
        "# Entries with null/TODO values or 'sniffed' license_source need review.",
    ]
    for e in entries:
        lines.append("")
        lines.append(f"# {e['path']}")
        if e["license_source"] != "plugin.json":
            lines.append(f"#   !! license_source: {e['license_source']} — REVIEW")
        if e["gpl3_only"] is None:
            lines.append("#   !! gpl3_only unknown — REVIEW")
        lines.append(f"{e['path']}:")
        lines.append(f"  slug: {y(e['slug'])}")
        lines.append(f"  code_license: {y(e['code_license'])}")
        lines.append(f"  gpl3_only: {y(e['gpl3_only'])}")
        lines.append(f"  artwork_license: {y(e['artwork_license'])}")
        if e["artwork_exceptions"]:
            lines.append(f"  # per-file artwork exceptions listed in docs/LICENSES.md: {e['artwork_exceptions']}")
        lines.append(f"  phone_home: null  # TODO")
        lines.append(f"  license_source: {y(e['license_source'])}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {out_path}")
    print(f"coverage: {n_ok} from plugin.json, {n_sniff} sniffed, {n_fail} unresolved")


if __name__ == "__main__":
    main()
