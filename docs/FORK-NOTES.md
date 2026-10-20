# JayBird fork notes

JayBird is a source-only fork of [DISTRHO Cardinal](https://github.com/DISTRHO/Cardinal).
It is **not** built or released as binaries by the project; anyone compiling it does so
under their own judgment about which modules to enable and what they can legally
distribute.

## Fork provenance

- Base: Cardinal commit `0a530b7` (post-26.02 era; upstream continues development separately).
- Remotes:
  - `origin`   → `github.com/rainey/JayBird` (this fork)
  - `upstream` → `github.com/DISTRHO/Cardinal` (full history preserved, so
    `git fetch upstream && git merge upstream/main` stays cheap — upstream history is
    mostly additive: new plugin submodules in `.gitmodules` + entries in
    `plugins/Makefile`).
- Rack submodule (`src/Rack`) is pinned at the v2.4.1-era commit Cardinal shipped
  (`8c6f41b7`, Aug 2023). Upgrading Rack is a separate, deliberate effort — see
  "Upgrading the Rack submodule" below.

## Intentional non-changes (upstream merge friendliness)

The following were deliberately left identical to upstream Cardinal:

- **Variant directory names** (`src/Cardinal`, `src/CardinalFX`, ...). Only the
  host-visible identity inside each `DistrhoPluginInfo.h` changed.
- **Internal `CARDINAL_*` macros** (`CARDINAL_VARIANT_MAIN`,
  `CARDINAL_NUM_AUDIO_INPUTS`, ...). Purely internal; renaming would create merge
  conflicts forever.
- **The `plugins/Cardinal` module collection slugs** (`Cardinal.AudioFile`,
  `Cardinal.HostParameters`, ...). These slugs appear in saved patches; renaming them
  would break patch compatibility with existing Cardinal patches.
- **Copyright headers and the `DISTRHO` plugin brand.** Attribution stays with
  DISTRHO/VCV for code we do not meaningfully modify.

## Branding changes (what makes JayBird distinct in a host)

Only host-visible identity strings were changed, in the per-variant
`DistrhoPluginInfo.h` files:

- Plugin name/label: `Cardinal` → `JayBird` (with per-variant suffixes:
  `JayBird FX`, `JayBird Synth`, `JayBird Mini`, `JayBird Loader`).
- LV2 URI: `https://distrho.kx.studio/plugins/cardinal` →
  `https://github.com/rainey/JayBird/plugins/jaybird` (per-variant `#fx`, `#synth`,
  `#mini`, `#loader` suffixes preserved).
- CLAP ID: `studio.kx.distrho.cardinal` → `com.github.rainey.jaybird`.
- VST2 four-character IDs: `DcnM`→`JyBd` (main), `DcnF`→`JyBf` (FX),
  `DcnC`→`JyBl` (Loader), `DcnM`→`JyBr` (Remote), `DcnS`→`JyBs` (Synth).
  (Mini/Native do not define one, matching upstream.)

Note: `src/CardinalRemote/DistrhoPluginInfo.h` is a **symlink** to
`../Cardinal/DistrhoPluginInfo.h` upstream, mirroring the main variant's identity.
Keep it a symlink; tooling that edits these files in place (e.g. `sed -i`) will
dereference it.

## Licensing notes

- Cardinal (and JayBird) are GPLv3+.
- Cardinal's rule of excluding `GPL-3.0-only` modules is **project policy, not a legal
  necessity** of the Rack license. `src/Rack` is GPLv3-or-later (plus a section-7
  Non-Commercial Plugin License Exception). A combined GPLv3+ binary may include
  GPL-3.0-only code.
- The harder axis is **artwork**: Rack's Component Library is CC BY-NC 4.0, Core
  module art is CC BY-NC-ND 4.0, and many plugin panels are CC-NC or custom
  "with permission" licenses (see `docs/LICENSES.md`). Treat code license and artwork
  license as separate axes when curating which modules a given build enables.
- Phone-home / online access is not allowed in any included module (Cardinal policy,
  kept).

## Module selection system

Selection is compile-time (the binary is self-contained by design), driven by
kconfiglib — the same menuconfig TUI as the Linux kernel.

### Day-to-day usage

```
make menuconfig                          # edit default config (kconfig/configs/default.config)
make CONFIG=test menuconfig              # edit a named config profile
make CONFIG=test                         # build with that profile
make jaybird-gen                         # regenerate build inputs from current config
```

Without any `kconfig/configs/<CONFIG>.config` file, the build is **build-all**
(byte-identical to upstream Cardinal behavior). Selecting a saved config
switches the build to the generated registration file `plugins/plugins-jaybird.cpp`
which replaces upstream's `plugins/plugins.cpp` in `plugins.a`.

`kconfig/configs/mini.config` (generated) mirrors upstream's `plugins-mini.cpp`
selection for the main family; the `CardinalMini` bundle itself is built by
upstream and is unaffected by `CONFIG` (see limitations).

### How it works

- `kconfig/manifest.yaml` — hand-curated per-plugin license data that needs
  judgment: artwork license and phone-home. Regenerate the draft from
  submodules via `python3 utils/jaybird/gen_manifest.py`, then curate by hand.
  Code licenses are **derived at generation time** from each `plugin.json`
  (with a LICENSE-file fallback) — see `utils/jaybird/licensing.py`.
- `utils/jaybird/gen.py` — the generator. Joins three sources:
  - `plugins.cpp` registration blocks (`StaticPluginLoader spl(p, "<dir>")`,
    `p->addModel(...)`, `spl.removeModule(...)`),
  - each plugin's `createModel<T>("slug")` definitions in its sources
    (slug↔symbol mapping; handles namespaced, macro-const and macro-table
    patterns),
  - the selected `.config` (via kconfiglib, honoring policy switches and
    defaults).
- Outputs: `kconfig/Kconfig.gen` (menu fragments),
  `plugins/plugins-jaybird.cpp` (filtered registration file),
  `plugins/plugins-jaybird.mk` (disabled-plugin list for the Makefile), and
  `kconfig/configs/mini.config`.
- Excluding a **module** = dropping its `addModel` line **plus** inserting
  `spl.removeModule("<slug>")`, matching upstream's own exclusion mechanism
  (Rack's `Plugin::modulesFromJson` matches manifest entries by slug and
  throws on stray entries). The plugin's sources still compile.
- Excluding a **plugin** = dropping its `initStatic__X()` body, its dispatch
  call and its `updateStaticPluginsDarkMode()` block, and filtering its
  sources (`PLUGIN_FILES`/`PLUGIN_BINARIES`) and shipped manifest
  (`PLUGIN_LIST`) via `plugins-jaybird.mk`. Headers stay included (shared
  stub definitions in `plugins.cpp` need the plugin types). Sources that
  always-compiled helpers depend on (e.g. `BaconPlugs/src/Style.cpp`, used
  by `surgext-helper`) are kept via `JAYBIRD_KEEP_SOURCES`, derived from
  upstream's own `MINIPLUGIN_FILES` curation. This mirrors how upstream
  hand-writes `plugins-mini.cpp`.
- Policy switches in `kconfig/Kconfig`: `ALLOW_GPL3_ONLY` (default y —
  Cardinal's GPL-3.0-only exclusion is policy, not law), `ALLOW_NC_ARTWORK`
  (default y), `STRICT_NO_PHONE_HOME` (default y). Plugins failing the active
  policy are hidden from the menu; their modules become unavailable.

### Known v1 limitations

- `ParableInstruments` registration is not filtered (shared
  `ArableInstruments` sources with `-DPARASITES`).
- DHE-Modules registers via per-namespace init helpers — plugin-level
  selection only.
- The `CardinalMini` variant keeps its own curated registration file
  (`plugins-mini.cpp`) and is built exactly as upstream: `CONFIG` governs the
  main/FX/Synth/Native/Loader archives only. `kconfig/configs/mini.config`
  only reproduces that selection for those archives; don't distribute
  `CardinalMini` if its fixed set does not fit your license requirements.
- `updateStaticPluginsDarkMode()` shared blocks are mapped by hand
  (`DARKMODE_PLUGINS` in `gen.py`); a new shared reference upstream would need
  to be added there.
- Cross-plugin source dependencies are only known where upstream's Mini
  curation exposes them (`JAYBIRD_KEEP_SOURCES`). Disabling a plugin that
  another *enabled* plugin's sources depend on (outside that set) can fail at
  link time.

## Upgrading the Rack submodule

Cardinal builds Rack from the `src/Rack` submodule, but replaces a set of files with
its own versions:

- `src/override/` — edited copies of Rack sources (notably `engine/Engine.cpp`:
  single-threaded engine on the audio thread + cable-order topological sorting),
  with per-file patch documentation in `src/override/diffs/`.
- `src/custom/` — replacements disabling network/library access (`asset.cpp`,
  `network.cpp`, `library.cpp`, ...).
- `src/Makefile` `IGNORED_FILES` lists exactly which Rack sources are dropped.

To upgrade Rack: bump the submodule, re-apply each `src/override/diffs/*.diff` against
the new Rack sources, resolve drift, and update `IGNORED_FILES` if file sets changed.
Do this deliberately; the v2.4.1 pin is fine until something specific is needed.

## Build recipe (Linux, Parabola/Arch)

See `docs/BUILDING.md` for dependencies. System packages used here: cmake, dbus,
fftw, libgl, liblo, libsndfile, libx11/libxcursor/libxext/libxrandr, python3
(jansson/libsamplerate/speexdsp/libarchive come vendored via `src/Rack/dep`).

Validated green build (2026-10-19):

```
make -j4        # ~25 min on 4 cores, all 89 plugin submodules + all variants
```

Produces in `bin/` (≈1.4 GB total):
- Standalone JACK apps: `Cardinal` (99 MB), `CardinalNative` (99 MB), `CardinalMini` (17 MB)
- LV2: `Cardinal.lv2`, `CardinalFX.lv2`, `CardinalSynth.lv2`, `CardinalMini.lv2`
- VST2: `Cardinal.vst` · VST3: `Cardinal.vst3` · CLAP: `Cardinal.clap`

Notes:
- Built **without** libsndfile dev headers (Audio File module falls back to
  MP3/MP4-only support). Install `libsndfile` and re-run `make` to link full
  format support.
- Output *bundle names* still carry the `Cardinal*` names (they derive from the
  variant Makefile `NAME`s). Host-side identity inside is JayBird (verified in
  generated LV2 TTL). Renaming bundle names can be done later if desired; LV2
  identification is URI-based and already collision-free.
- The build self-tests: LV2 TTL generation instantiates the plugin, loads
  default patches and steps the engine.
