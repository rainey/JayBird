# AUR packaging for JayBird

Arch/Parabola packaging modeled on the official `cardinal` package
(Extra repo, split per-format subpackages upstream; JayBird uses a single
package for simplicity).

## Contents

- `PKGBUILD` — builds from a git tag with submodules, `SYSDEPS=true`
  (system jansson/libarchive/libsamplerate/speexdsp/fftw; only quickjs
  and surge build in-tree — both sources are submodules, no network
  needed beyond the initial clone).

## Module selection profiles

The package builds with the `default` profile (all modules; identical
to upstream behavior). Select another profile at build time:

```
_jaybird_config=test makepkg          # profile from kconfig/configs/
_jaybird_config=/path/to/my.config makepkg   # external config file
```

An external config is copied into the tree as `kconfig/configs/aur-<name>.config`
so the standard `make CONFIG=<name>` machinery (see docs/FORK-NOTES.md)
picks it up. `make gen` in `check()` runs TTL generation, which
instantiates every registered plugin — a selection that breaks
registration fails the package build.

## Layout

Installs Cardinal-style:
- `/usr/bin/Cardinal`, `/usr/bin/CardinalMini` (standalone, JACK)
- `/usr/lib/lv2/*.lv2`, `/usr/lib/vst/*.vst`, `/usr/lib/vst3/*.vst3`,
  `/usr/lib/clap/*.clap`
- `/usr/share/cardinal/*` (resources)
- `/usr/share/doc/jaybird/` (README, FORK-NOTES)

`CardinalNative` (developer test tool) is removed, matching upstream
packaging. VST2 is intentionally kept in the main package (unlike
upstream's split packages) — reorganize into depends-providers if you
ever want format-split subpackages.

## Local testing (Parabola)

```
cd packaging/aur
_jaybird_config=default makepkg -Cf
pacman -U jaybird-26.02-1-x86_64.pkg.tar.zst
```

NOTE: local libsndfile/jansson/libarchive dev headers must be present
(`pacman -S libsndfile jansson libarchive` — Parabola may need the
`-doc`/dev variants if split).

## Publishing to AUR

```
# first time:
git clone ssh://aur@aur.archlinux.org/jaybird.git aur-jaybird
cp packaging/aur/PKGBUILD packaging/aur/SRCINFO aur-jaybird/
cd aur-jaybird && makepkg --printsrcinfo > .SRCINFO
git add PKGBUILD .SRCINFO && git commit -m "jaybird 26.02-1" && git push
```

Subsequent releases: bump `pkgver`/`pkgrel`, tag `v<version>` on GitHub,
regenerate `.SRCINFO`, push. `sha256sums` stays `SKIP` (git-tag source;
add tarball sources + hashes if you prefer the release-tarball flow via
`make jaybird-tarball`).
