# AGENTS.md — JayBird

Guidance for AI agents (and humans) working in this repository: what JayBird
is, the invariants you must not break, and the exact procedure for importing
a new module/plugin.

## What this repo is

JayBird is a fork of **Cardinal** (VCV Rack as plugins) whose distinguishing
feature is **kconfig-based module selection**: instead of compiling the whole
upstream plugin collection, a `.config` (Kconfig) selects which plugins —
down to individual modules — get built. Generated artifacts adapt the build:

- `kconfig/Kconfig.gen` — per-plugin/per-module menu fragments (generated)
- `plugins/plugins-jaybird.cpp` — filtered static registration file (generated)
- `kconfig/configs/{default,mini,test}.config` — selection profiles
- `nix/package.nix` + flake outputs `.#jaybird` (build-all), `.#test`, `.#mini`

New plugins arrive as **git submodules** under `plugins/<PluginName>`. The
submodule working trees must stay **pristine**; every adaptation JayBird
needs is applied at build time from `patches/` (see below). Selection code
lives in `utils/jaybird/` (`gen.py`, `gen_manifest.py`, `licensing.py`,
`buildability.py`, `audit-submodule-pins.sh`).

## Hard invariants (never violate)

1. **Submodules stay pristine.** Never commit modifications inside
   `plugins/<Subdir>/`. All fixes live as build-time patches in
   `patches/<Subdir>/` (git-format diffs + `meta.yaml`), applied by
   `patches/submodule-patches.mk` as an order-only prerequisite of the
   plugin's object rules.
2. **`plugins/plugins-jaybird.cpp` and `kconfig/Kconfig.gen` are generated**
   by `python3 utils/jaybird/gen.py` — never hand-edit them. Hand-edit
   `plugins/plugins.cpp` only where gen.py mirrors it, or gen.py itself.
3. **`nix/source-rev` must always point at the current HEAD commit** before
   a nix build. `make nix-update-rev` writes it; commit it together with
   the change it pins (amend if you forgot).
4. **Never run top-level `make clean`** — it wipes `deps/` and `dpf/`.
   Only `make clean -C plugins` (keeps `src/Rack/dep` intact).
5. **Patch application uses plain `patch(1)`, not `git apply`** — the nix
   sandbox materializes submodules *without* their `.git`, so git is
   unavailable inside the sandbox. `patches/submodule-patches.mk` handles
   apply/reverse-check/unpatch with `patch`; don't "simplify" it back to
   `git apply`.

## Importing a new plugin — step by step

### 1. Add and pin the submodule

```sh
git submodule add <url> plugins/<Name>
```

Pin to the commit you want to build. **Verify the tag is actually current**
— release tags are sometimes stale (halfagiraf's `v2.1.0` tag was outdated;
its main branch was at `v2.2.0` content). Compare tag vs main tip before
pinning. Note the exact commit + `plugin.json` version in the patch
`meta.yaml` and commit message, since patches record what they apply to.

### 2. Write the plugins/Makefile section

Add a section like the existing ones (`# <Name>` block). Decide:

**Source list.** Mirror the *upstream plugin's own Makefile*, not guesswork:
which `src/*.cpp` files are compiled, which subdirectories exist (do NOT
forget extra source dirs — see the CountModula failure below), and which
files are excluded (unregistered dev code like `Palimpsest.cpp`). Then:

- **Exclude the registration file** (defines `init(Plugin*)` and
  `Plugin* pluginInstance`). Usually `src/plugin.cpp`, but the name varies
  (CountModula's is `src/CountModula.cpp`). Pattern:
  ```make
  PLUGIN_FILES += $(filter-out <Name>/src/plugin.cpp,$(wildcard <Name>/src/*.cpp))
  ```
- If the plugin needs `-Dinit=init__<Name>` to keep its registration file
  compiled (upstream style used by a few plugins like AaronStatic/MindMeld),
  apply the rename **only in a dedicated rule for that one file**, never as
  a blanket define on all of the plugin's TUs (see GCC 16 finding below).
- Vendored third-party code (e.g. Mutable Beads/stmlib) needs the same
  flags upstream uses; check upstream's `BEADS_SOURCES`-style wildcards and
  which files are *excluded* from them (`factory_test.cc`, `ui.cc`, etc.).

**Symbol clashes.** If the plugin defines types/functions/classes whose
names collide with another compiled plugin, use the `custom_module_names`
macro with a `<NAME>_CUSTOM = Foo Bar` list — this compiles the plugin with
`-DFoo=<Name>Foo` etc. (see `COUNTMODULA_CUSTOM`, `HALFAGIRAF_CUSTOM`,
`ARABLE_CUSTOM`...). Check for clashes with:

```sh
grep -rn "struct <TypeName>\b" plugins/*/src | ...   # before choosing
```

Symbol classes that have actually clashed before: `stmlib` (halfagiraf →
`-Dstmlib=Halfagirafstmlib`; note Arable/Parable rename it too, while
AudibleInstruments compiles it *unrenamed*), module type names (Arpeggiator,
Mixer, Fade, Stack...), `defaultTheme`/`prevDefaultTheme` globals (Venom
also defines `defaultTheme`).

**Patch hook.** If the plugin has any patch, add
`| submodule-patches` (order-only prereq) **on the same line** as the real
prerequisite of its object rule — splitting it to the next line loses it.

### 3. Handle Cardinal's stubs / removed APIs

Cardinal plugin builds differ from Rack in ways that break upstream code:

- **osdialog is stubbed out** (`include/osdialog-stub/osdialog.h`, upstream
  Cardinal commit 83ba2ca): blocking `osdialog_file/message/prompt` do not
  link. Convert to Cardinal's async dialogs under
  `#ifdef USING_CARDINAL_NOT_RACK` (upstream Rack behavior stays in the
  `#else`): `async_dialog_filebrowser`, `async_dialog_message`,
  `async_dialog_text_input` (declared via `include/common.hpp`).
  Deviations to document: file-type filters are dropped; directory pickers
  don't exist in the async API — use a save dialog + `system::getDirectory`
  of the chosen path; code that polled a modal result inside `step()` must
  be restructured to fire-and-resume-in-callback.
- **The MIDI driver stack is removed**: `rack::midi::Output` doesn't exist
  in Cardinal's `include/midi.hpp`. To emit MIDI from a module, write a
  small adapter that forwards to the host via
  `CardinalPluginContext::writeMidiMessage` (defined in
  `src/CardinalCommon.cpp`, so it resolves at the *final* Cardinal link —
  `plugins.a`-only builds won't see it, which is fine). Get the context via
  `static_cast<CardinalPluginContext*>(APP)` — the context is **not
  polymorphic**, never `dynamic_cast`. Precedent: `CardinalMidiOut` in the
  halfagiraf `osdialog-midi.patch`; core HostMIDI does the same. Neutralize
  `toJson/fromJson` of the removed port state (empty object), and omit
  Driver/Device menu submenus under Cardinal.
- **phone_home policy**: modules that perform any online access
  (downloads, update checks) are allowed only if `kconfig/manifest.yaml`
  marks `phone_home: true`, and are additionally gated by the default
  `STRICT_NO_PHONE_HOME=y` config. No-network plugins must be marked
  `phone_home: false` *after actually verifying* (grep the source for
  curl/http/sockets), not assumed.

### 4. Record the patch (if any)

Follow `patches/submodule-patches.README.md`:

1. Edit the submodule working tree until the build passes.
2. `git -C plugins/<Name> diff > patches/<Name>/<something>.patch`
3. `git -C plugins/<Name> checkout -- .` (restore pristine)
4. Write `patches/<Name>/meta.yaml`: `submodule:`, `reason:`, `notes:`
   (include behavioral deviations and the exact commit the patch applies
   to, plus the regeneration command for after a pin move).

### 5. Register the plugin

Registration is generated. Run:

```sh
python3 utils/jaybird/gen.py            # regenerates Kconfig.gen + plugins-jaybird.cpp
```

Plugin selection state comes from `kconfig/manifest.yaml` (hand-curated:
`artwork_license`, `phone_home`). Generate a draft entry with
`python3 utils/jaybird/gen_manifest.py`, then **curate it**: fill artwork
license (SPDX) and verify phone-home by reading the code. Code licenses are
derived automatically from `plugin.json` — don't put them in the manifest.

If the plugin's module count/collection must always be registered (host
plumbing), it belongs in `ALWAYS_ON` in gen.py (only Cardinal/Fundamental
so far). If it participates in `updateStaticPluginsDarkMode()`, add it to
`DARKMODE_PLUGINS` (bogaudio, meander, GlueTheGiant, surgext).

### 6. Verify — in the right order

```sh
# a) targeted compile
python3 utils/jaybird/buildability.py --filter <Name> --force --keep
#    (transient kconfig + `make -C plugins plugins.a`; log in buildability-logs/)

# b) symbol audit of the resulting archive — plugins.a does NOT resolve
#    symbols, so undefined refs are only caught here or at final link:
nm -A --defined-only plugins.a | grep <Name>       # definitions exist
nm -A -u plugins.a | grep -i <name>                # cross-check leftovers

# c) the real test: a full Cardinal link (see warning below)
nix build .#test --cores 4        # or: make cardinal locally if deps are set up
```

**Warning that has bitten us repeatedly:** `make -C plugins plugins.a` and
the buildability sweep only exercise compilation + archiving. `ar` does not
link, so **duplicate/undefined cross-TU symbols surface only at the final
Cardinal link** (`make cardinal` / the nix build). A plugin can pass the
entire local sweep and still fail the nix build hours later. Treat a full
link as a mandatory gate for any new plugin. `#mini` excludes most plugins,
so a green `#mini` proves nothing about your plugin.

**Make gotcha:** editing a compile *rule* (flags) does not invalidate
existing objects — make only compares source mtimes. After changing a
plugin's rule flags, `rm -rf ../build/plugins/<Name>` (or the specific
objects) before rebuilding, or you will mix old/new objects and get
mysterious undefined symbols from the stale ones.

### 7. Commit

```sh
git add plugins/<Name> plugins/Makefile plugins/plugins.cpp patches/<Name> ...
make nix-update-rev && git add nix/source-rev
git commit   # submodule pin + integration + patches + rev pin together
```

(Dirty `plugins/surgext` and `src/Rack` submodules are pre-existing; leave
them unstaged.) Then rebuild the affected flake outputs:

```sh
nix build .#jaybird --cores 4   # and/or .#test / .#mini
```

## Major findings / gotchas archive

These were each discovered the hard way; don't rediscover them:

- **GCC 16 + blanket `-Dinit=` renames break the link.** Newer libstdc++
  no longer inline-defines `std::basic_ios::init` in headers, so any TU
  compiled with `-Dinit=init__X` that constructs an iostream/fstream emits
  undefined `init__CountModula`-style references (the call inside the
  header gets macro-renamed but nothing defines it). Rule: never apply
  `-Dinit=` to a whole plugin's sources; only to the single registration
  TU that needs it — or better, exclude the registration file and drop the
  rename entirely (the CountModula approach).
- **Registration-file pattern.** Cardinal-side `plugins.cpp` *defines*
  `Plugin* pluginInstance__X` for plugins whose registration file is
  excluded, and declares it `extern` for the few upstream-style plugins
  whose registration file is compiled with the rename. Mixing the two for
  one plugin = duplicate `pluginInstance__X` at the final link. Keep the
  two categories consistent.
- **Missing source directories.** CountModula's `src/components/*.cpp`
  (defining `STD_HALF_ROWS6/7/8`) was missed because the wildcard only
  globbed `src/*.cpp` + `src/modules/*.cpp`. Always enumerate the plugin's
  actual source tree (`find plugins/<Name>/src -name '*.cpp'`) and mirror
  the upstream Makefile's selection.
- **Repo-owned shims.** When an excluded registration file also carries
  live code that other TUs reference (CountModula's theme globals,
  settings helpers, expander positioning), provide it in a repo-owned
  `plugins/<Name>-shim.cpp` with its own explicit rule, copying the
  upstream code verbatim (minus registration) with the same `-D` renames,
  plus a header comment pointing at the upstream file to re-sync on pin
  moves. See `plugins/CountModula-shim.cpp`.
- **Generated-file extern/definition state must match the Makefile.**
  gen.py emits `Plugin* pluginInstance__X;` definitions; if you switch a
  plugin to the "registration file compiled" style, gen.py/plugins.cpp
  must emit `extern` instead.
- **Tag staleness.** A plugin's latest git tag can lag its main branch
  (halfagiraf v2.1.0 tag vs v2.2.0 content on main). Pin to content, not
  to a tag name; record the commit in meta.yaml.
- **Sandbox vs git.** nix builds strip submodule `.git`; anything that
  assumes git metadata inside the build (including `git apply`) fails with
  misleading errors. Plain `patch(1)` is sandbox-proof. Debugging note:
  a patch-apply failure inside nix surfaces as a generic build error —
  reproduce with `make -f patches/submodule-patches.mk submodule-status`
  outside nix first.
- **Cap nix parallelism on shared/interactive machines.** `nix build` uses
  all cores by default and its build processes are daemon-owned at nice 0
  (renicing them needs root), so a full-speed build makes the desktop
  unusable. Pass an explicit cap, e.g. `nix build .#<out> --cores 4`.
- **Final-link symbol classes to grep for when a link fails:** multiple
  definition of `pluginInstance__*` (registration file compiled twice),
  undefined `<Name><Helper>` (missing source file or excluded-but-referenced
  code), undefined `init__*` / `std::basic_ios<...>::init__*` (blanket
  init rename). The linker error names the defining
  `plugins.a(<file>.cpp.o)` — read it before touching anything.

## Useful commands

```sh
python3 utils/jaybird/gen.py [kconfig/configs/<profile>.config]   # regenerate
python3 utils/jaybird/gen_manifest.py                            # draft manifest entries
python3 utils/jaybird/buildability.py [--filter X] [--drilldown] [--restore]
./utils/jaybird/audit-submodule-pins.sh                          # pins vs patches
make -f patches/submodule-patches.mk submodule-{patches,unpatch,status}
make -C plugins plugins.a                                        # quick archive build
nix build .#jaybird --cores 4                                    # full build incl. link
nix flake show                                                   # sanity-check the flake
```

