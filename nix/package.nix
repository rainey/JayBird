# JayBird — Nix package.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Modeled on nixpkgs' cardinal package (SYSDEPS=true, system libraries,
# carla path substitution), building from the full source tree.
#
# configPath: a .config file to build with, installed as
# kconfig/configs/nix.config (CONFIG=nix), or null for build-all.

{
  lib,
  stdenv,
  alsa-lib,
  carla,
  cmake,
  dbus,
  fftwFloat,
  file,
  freetype,
  jansson,
  libGL,
  libglvnd,
  libjack2,
  libx11,
  libxcursor,
  libxext,
  libxrandr,
  libarchive,
  liblo,
  libsamplerate,
  libsndfile,
  makeWrapper,
  pkg-config,
  python3,
  speexdsp,

  # Module selection passthrough (see kconfig/)
  srcArg,
  prefetchedDeps,
  configPath ? null,
  headless ? false,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "jaybird";
  version = "26.02";

  src = srcArg;

  postPatch = ''
    patchShebangs .

    # Rack's /dep is gitignored and downloaded at build time; place the
    # prefetched sources so the sandbox build needs no network.
    mkdir -p src/Rack/dep/lib
    cp -r ${prefetchedDeps}/jansson-2.12 src/Rack/dep/jansson-2.12
    cp -r ${prefetchedDeps}/libarchive-3.4.3 src/Rack/dep/libarchive-3.4.3
    cp -r ${prefetchedDeps}/libsamplerate-0.1.9 src/Rack/dep/libsamplerate-0.1.9
    cp -r ${prefetchedDeps}/zstd-1.4.5 src/Rack/dep/zstd-1.4.5

    substituteInPlace plugins/Cardinal/src/Carla.cpp \
      --replace-fail "/usr/lib/carla" "${carla}/bin" \
      --replace-fail "/usr/share/carla/resources" "${carla}/share"

    substituteInPlace plugins/Cardinal/src/Ildaeil.cpp \
      --replace-fail "/usr/lib/carla" "${carla}/bin" \
      --replace-fail "/usr/share/carla/resources" "${carla}/share"
  ''
  # Activate module selection: place the config and let the build run
  # `make CONFIG=nix` so the Makefile's wildcard picks it up.
  + lib.optionalString (configPath != null) ''
    install -Dm644 ${configPath} kconfig/configs/nix.config
  '';

  # The build writes generated files into the source tree
  # (kconfig/Kconfig.gen, plugins/plugins-jaybird.cpp, bin/, build/).
  # In the fixed-output build dir this is fine (source is copied, not linked).
  dontUseCmakeConfigure = true;
  enableParallelBuilding = true;
  strictDeps = true;

  nativeBuildInputs = [
    cmake
    file
    pkg-config
    makeWrapper
    (python3.withPackages (p: [ p.pyyaml ]))
  ];

  buildInputs = [
    alsa-lib
    dbus
    fftwFloat
    freetype
    jansson
    libGL
    libglvnd
    libx11
    libxcursor
    libxext
    libxrandr
    libarchive
    liblo
    libsamplerate
    libsndfile
    speexdsp
  ];

  hardeningDisable = [ "format" ];

  makeFlags = [
    "SYSDEPS=true"
    "PREFIX=$(out)"
  ]
  ++ lib.optional (stdenv.hostPlatform != stdenv.buildPlatform) "CROSS_COMPILING=true"
  ++ lib.optional headless "HEADLESS=true"
  ++ lib.optional (configPath != null) "CONFIG=nix";

  outputs = [
    "out" # standalone binaries
    "lv2" # LV2 bundles
    "vst3" # VST3 bundles
    "clap" # CLAP bundles
  ];

  postInstall = ''
    # Cardinal's install layout puts bundles in $out/lib/{lv2,vst,vst3,clap};
    # mirror nixpkgs cardinal's layout (single output compatible) but keep
    # our split outputs by moving from $out/lib/* into each output root.
    moveToOutput lib/lv2 "$lv2"
    moveToOutput lib/vst3 "$vst3"
    moveToOutput lib/clap "$clap"
    # keep VST2 in $out (format is legacy and proprietary-toolchain only)

    # Bundle resources contain absolute symlinks into the build tree;
    # dereference them so each output is self-contained.
    fixup_bundle_resources() {
      local bundle="$1"
      [ -d "$bundle/resources" ] || [ -d "$bundle/Resources" ] || return 0
      local resdir="$bundle/resources"
      [ -d "$resdir" ] || resdir="$bundle/Resources"
      cp -rL "$resdir" "$resdir.real"
      rm -rf "$resdir"
      mv "$resdir.real" "$resdir"
    }

    for bundle in "$lv2"/lib/lv2/*.lv2 "$vst3"/lib/vst3/*.vst3 "$clap"/lib/clap/*.clap; do
      fixup_bundle_resources "$bundle"
    done

    wrapProgram $out/bin/Cardinal \
      --suffix LD_LIBRARY_PATH : ${lib.makeLibraryPath [ libjack2 alsa-lib ]}
    wrapProgram $out/bin/CardinalMini \
      --suffix LD_LIBRARY_PATH : ${lib.makeLibraryPath [ libjack2 alsa-lib ]}

    # developer test tool, like nixpkgs cardinal
    rm -f $out/bin/CardinalNative
  '';

  passthru = {
    inherit configPath;
  };

  meta = with lib; {
    description = "JayBird — a Cardinal (VCV Rack) fork with selectable module builds";
    homepage = "https://github.com/rainey/JayBird";
    license = licenses.gpl3Plus;
    platforms = platforms.linux;
    mainProgram = "Cardinal";
  };
})
