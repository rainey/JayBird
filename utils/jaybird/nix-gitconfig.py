#!/usr/bin/env python3
"""Generate a machine-local git config that redirects every submodule's
network URL to its local checkout under this repo.

Why: the flake fetches the source tree with builtins.fetchGit { submodules
= true; }, and a fresh rev means a cold submodule fetch in which nix runs
`git ls-remote`/fetch against every submodule remote serially (Carla's
JUCE/PawPaw/etc. chain alone is dozens of round trips). On a slow link
that looks like a multi-hour stall. With this config the same fetch is
local (clones from the working-tree checkouts) and takes ~40 s.

Usage:
    make nix-gitconfig                      # (re)generate .nix-gitconfig
    GIT_CONFIG_GLOBAL=$(pwd)/.nix-gitconfig nix build .#...

The generated file must NOT be committed: it contains absolute paths to
this machine's checkout. Each developer generates their own. Pins that
are not checked out locally (or repos fetched over ssh-only URLs) simply
fall through to their network remote, so the config is always safe.

Requires: every submodule's pinned commit present in its local checkout
(`git submodule update --init` once after clone).
"""

import os
import re
import subprocess
import sys

REPO = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True, text=True, check=True,
).stdout.strip()

PATH_RX = re.compile(r"\.path\s+(.+)$")
URL_RX = re.compile(r"remote\.\S+\.url\s+(.+)$")


def walk(base, subs):
    """Collect submodule dirs recursively (nested .gitmodules included)."""
    gm = os.path.join(base, ".gitmodules")
    if not os.path.isfile(gm):
        return
    out = subprocess.run(
        ["git", "config", "--file", gm, "--get-regexp", r"submodule\..*\.path"],
        capture_output=True, text=True,
    ).stdout
    for ln in out.splitlines():
        m = PATH_RX.search(ln)
        if not m:
            continue
        sub = os.path.join(base, m.group(1).strip())
        # A checkout must exist; .git may be a dir (top level) or a file
        # (gitlink into the parent's .git/modules).
        if os.path.exists(os.path.join(sub, ".git")):
            subs.append(sub)
            walk(sub, subs)


def main():
    subs = []
    walk(REPO, subs)

    lines, seen = [], set()

    # The flake fetches its own source from the canonical GitHub URL;
    # rewrite that too so local builds (incl. unpushed commits) clone
    # from this checkout instead of the remote.
    origin = subprocess.run(
        ["git", "-C", REPO, "config", "--get", "remote.origin.url"],
        capture_output=True, text=True,
    ).stdout.strip()
    if origin and not origin.startswith("file://"):
        seen.add(origin)
        local = f"file://{REPO}"
        lines.append(f'[url "{local}"]\n\tinsteadOf = {origin}\n')
        if origin.endswith(".git"):
            lines.append(f'[url "{local}"]\n\tinsteadOf = {origin[:-4]}\n')

    for sub in sorted(set(subs)):
        out = subprocess.run(
            ["git", "-C", sub, "config", "--get-regexp", r"remote\..*\.url"],
            capture_output=True, text=True,
        ).stdout
        for ln in out.splitlines():
            m = URL_RX.search(ln)
            if not m:
                continue
            url = m.group(1).strip()
            if url.startswith("file://") or url in seen:
                continue
            seen.add(url)
            local = f"file://{sub}"
            lines.append(f'[url "{local}"]\n\tinsteadOf = {url}\n')
            # Repos reference each other with and without the .git suffix;
            # cover both spellings.
            if url.endswith(".git"):
                lines.append(f'[url "{local}"]\n\tinsteadOf = {url[:-4]}\n')

    out_path = os.path.join(REPO, ".nix-gitconfig")
    with open(out_path, "w") as f:
        f.write("".join(lines))
    print(f".nix-gitconfig written: {len(seen)} URLs -> local checkouts "
          f"({len(set(subs))} submodule dirs)")
    print("use: GIT_CONFIG_GLOBAL=" + out_path + " nix build .#<profile>")


if __name__ == "__main__":
    sys.exit(main())
