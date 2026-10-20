#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-plugin code-license detection (shared by gen.py and gen_manifest.py).

Code licenses are always derived from live submodule data (plugin.json, then
LICENSE file sniffing); the curated manifest only carries the artwork and
phone-home axes.
"""

import json
import os
import re

LICENSE_SNIFFS = [
    (r"GNU General Public License.*version 3.*any later version", "GPL-3.0-or-later"),
    (r"GNU General Public License", "GPL-3.0-only?"),  # GPL text w/o or-later
    (r"Permission is hereby granted, free of charge", "MIT"),
    (r"Redistribution and use in source and binary forms", "BSD?"),
    (r"Apache License", "Apache-2.0"),
    (r"Creative Commons", "CC?"),
    (r"public domain", "Unlicense?"),
]


def normalize_license(license_str):
    """Classify a plugin.json license string; returns (spdx, gpl3_only)."""
    s = license_str.strip()
    is_or_later = bool(re.search(r"or[- ]later|\bGPL\+|\bGPL\d?\+", s, re.I))
    if re.search(r"GPL-?3|GPLv?3", s, re.I):
        return "GPL-3.0-or-later" if is_or_later else "GPL-3.0-only", not is_or_later
    if re.search(r"GPL-?2|GPLv?2", s, re.I):
        return ("GPL-2.0-or-later", False) if is_or_later else ("GPL-2.0-only", None)
    return s, None


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


def detect_code_license(plugin_dir):
    """Returns (spdx, gpl3_only, source) for a checked-out plugin directory."""
    for cand in ("plugin.json", "res/plugin.json"):
        p = os.path.join(plugin_dir, cand)
        if os.path.isfile(p):
            try:
                j = json.load(open(p))
            except Exception:
                continue
            lic = j.get("license")
            if lic:
                spdx, gpl3 = normalize_license(lic)
                return spdx, gpl3, "plugin.json"
    spdx = sniff_license(plugin_dir)
    if spdx:
        return spdx, None, "LICENSE sniff"
    return None, None, None
