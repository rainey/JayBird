#!/usr/bin/env bash
# Audit which submodule pins are fetchable upstream (reachability is all
# that matters: git fetch origin <sha> works for any reachable sha).
# SPDX-License-Identifier: GPL-3.0-or-later
set -uo pipefail

# path|url|rev triples from .gitmodules + ls-tree, robust to spaces
audit() {
  git config -f .gitmodules --get-regexp '^submodule\..*\.path$' |
    sed 's/^submodule\.\(.*\)\.path /\1 /' |
    while read -r sec path; do
      url=$(git config -f .gitmodules --get "submodule.${sec}.url")
      rev=$(git ls-tree HEAD "$path" | awk '{print $3}')
      printf '%s|%s|%s\n' "$path" "$url" "$rev"
    done
}

audit | while IFS='|' read -r path url rev; do
  found=$(timeout 90 git ls-remote "$url" 'refs/heads/*' 'refs/tags/*' 'refs/pull/*/head' 2>/dev/null |
    grep -c "^$rev")
  if [ "$found" -eq 0 ]; then
    echo "UNFETCHABLE|$path|$url|$rev"
  fi
done
