# Build-time submodule patches

Submodule sources stay pristine in git; fixes JayBird needs live here as
git-format patches and are applied into the submodule working tree at build
time. Nothing patched is ever committed inside a submodule.

## Layout

    patches/<Subdir>/<name>.patch   git-format diff, paths relative to the
                                    submodule root
    patches/<Subdir>/meta.yaml      metadata (see below)

## meta.yaml

    submodule: plugins/<Subdir>     # required: path relative to repo root
    reason: ...                     # why the patch exists
    notes: ...                      # behavioral deviations, apply/commit pin

## Usage

    make -f patches/submodule-patches.mk submodule-patches   # apply all
    make -f patches/submodule-patches.mk submodule-unpatch   # revert all
    make -f patches/submodule-patches.mk submodule-status    # state

`plugins/Makefile` runs `submodule-patches` automatically as an order-only
prerequisite of the archive targets and of any patched plugin's object
rules, so a plain build applies patches on demand. "Already applied" is
detected with `git apply --reverse --check`, so no stamp files are needed
and fresh checkouts just work.

## Adding a patch for a new module

1. Modify the submodule working tree until the build passes:
       # edit plugins/<Subdir>/...
       make -C plugins <Subdir-target>
2. Record it and reset the submodule to pristine:
       git -C plugins/<Subdir> diff > patches/<Subdir>/<name>.patch
       git -C plugins/<Subdir> checkout -- .
3. Write patches/<Subdir>/meta.yaml (submodule:, reason:, notes:).
4. Add a `| submodule-patches` order-only prerequisite to the plugin's
   object rules in plugins/Makefile (see the SignalFunctionSet rules for
   the pattern; the order-only prereq must be on the same line as the real
   prerequisite — splitting the rule across two lines loses it).
5. Verify the round trip:
       make -f patches/submodule-patches.mk submodule-status    # unapplied
       make -C plugins ...                                      # auto-applies
       make -f patches/submodule-patches.mk submodule-status    # applied
       make -f patches/submodule-patches.mk submodule-unpatch   # pristine

## Rebasing after a pin move

    # old pin: patch applies; new pin: does not
    git -C plugins/<Subdir> apply patches/<Subdir>/<name>.patch   # from old pin
    # update the submodule pin, resolve conflicts in the working tree,
    # then regenerate:
    git -C plugins/<Subdir> diff > patches/<Subdir>/<name>.patch

## Current patches

- `SignalFunctionSet/osdialog-async.patch` — convert blocking osdialog
  calls to Cardinal's async dialog API. See its meta.yaml for details.
