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
  writeText,
  alsa-lib,
  carla,
  ccache,
  cmake,
  curl,
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
  mesa,
  pipewire,
  pkg-config,
  python3,
  speexdsp,

  # Module selection passthrough (see kconfig/)
  srcArg,
  prefetchedDeps,
  configPath ? null,
  headless ? false,

  # JACK client implementation exposed to the runtime dlopen (see note at
  # wrapProgram). Compile-time always uses libjack2's headers/jack.pc:
  # pipewire.jack ships no jack.pc, and libjack2's is API-compatible for
  # the bridge's dlsym'd functions.
  #   "pipewire" (default) — nix closure's pipewire.jack client
  #     (hermetic: works on any host running a pipewire daemon).
  #   "jack2" — nix closure's libjack2 client (hosts running jackd).
  #   "host" — no client lib in the closure; dlopen("libjack.so.0")
  #     resolves through the host's own dirs (probing pipewire-jack's
  #     private dir first, then the host default paths). Non-hermetic by
  #     definition: guaranteed server/client pairing, but depends on host
  #     layout.
  jackClient ? "pipewire",

  # OpenGL driver stack on LD_LIBRARY_PATH for GLVND's runtime
  # dlopen("libGLX_mesa.so.0")/("libEGL_mesa.so.0"). The binary links nix
  # libglvnd, whose vendor lookup searches only LD_LIBRARY_PATH + nix
  # store RUNPATHs + nix glibc — the HOST's vendor lib (/usr/lib on Arch,
  # /run/opengl-driver on NixOS) is invisible to a nix binary, so on
  # non-NixOS hosts puglRealize fails with an empty FBConfig list
  # ("Failed to realize Pugl view" / "Failed to create NanoVG context").
  #   "mesa" (default) — closure's mesa.drivers (libGLX_mesa + DRI
  #     drivers). Hermetic; kernel/drm API coupling is stable. Correct
  #     for AMD/Intel hosts.
  #   "host" — nothing from the closure; a runtime shim dir (created by
  #     a sourced script via makeWrapper --run) exposes the HOST's GLX/
  #     EGL vendor lib + private deps (nvidia glcore/glsi/..., mesa
  #     libgallium) through symlinks, without exposing /usr/lib
  #     wholesale. Needed for proprietary-NVIDIA hosts: glvnd there must
  #     load libGLX_nvidia, which the host driver ships. Also fine on
  #     NixOS (/run/opengl-driver links are picked up; the loader path
  #     already covers them) and on mesa hosts without nixpkgs-mesa.
  glDriver ? "mesa",

  # Host-side ccache directory (e.g. "/var/tmp/jaybird-ccache"). When set,
  # compiles run through ccache; the directory must be exposed to the
  # sandbox with:  --option extra-sandbox-paths <dir>  (and be writable by
  # the nixbld build users). Falls back to an ephemeral in-sandbox cache
  # (with a warning) when the host dir is unavailable, so builds never
  # fail over a missing bind mount.
  ccacheDir ? null,
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

  # No CC := / CXX := overrides exist in the Makefiles, so exported env
  # vars win over their `?=` fallbacks. Multi-word values are dangerous:
  # several vendored dep Makefiles recurse with an unquoted `CC=$(CC)`
  # (deps/Makefile DEP_MAKE), which turns `CC="ccache cc"` into a stray
  # "cc" make goal. So instead of a two-word CC/CXX, generate per-build
  # single-word shims that call ccache with the absolute compiler path,
  # and let CC/CXX stay plain names. Also covers carla and every other
  # recursive dep build.
  preBuild = lib.optionalString (ccacheDir != null) ''
    mkdir -p "$NIX_BUILD_TOP/ccshims"
    for t in cc gcc c++ g++; do
      orig="$(command -v "$t")" || exit 1
      printf '#!/bin/sh\nexec ccache %q "$@"\n' "$orig" > "$NIX_BUILD_TOP/ccshims/$t"
      chmod +x "$NIX_BUILD_TOP/ccshims/$t"
    done
    export PATH="$NIX_BUILD_TOP/ccshims:$PATH"
    export CC=cc CXX=g++
    export CCACHE_MAXSIZE=10G
    if mkdir -p ${lib.escapeShellArg ccacheDir} 2>/dev/null && [ -w ${lib.escapeShellArg ccacheDir} ]; then
      export CCACHE_DIR=${lib.escapeShellArg ccacheDir}
      echo "ccache: using host cache ${ccacheDir}"
    else
      export CCACHE_DIR="$NIX_BUILD_TOP/ccache"
      echo "ccache WARNING: host cache unavailable (pass --option extra-sandbox-paths ${ccacheDir} — and add 'extra-sandbox-paths = ${ccacheDir}' to /etc/nix/nix.conf, client options are ignored by the untrusted daemon); cache is ephemeral for this build"
    fi
  '';

  nativeBuildInputs = [
    cmake
    file
    pkg-config
    makeWrapper
    (python3.withPackages (p: [ p.pyyaml ]))
  ] ++ lib.optionals (ccacheDir != null) [ ccache ];

  buildInputs = [
    alsa-lib
    curl # dbRackCsound's vendored libcsound64.a references libcurl
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

  postInstall =
    let
      # DPF's jackbridge dlopen()s "libjack.so.0" at runtime — the binary
      # has no libjack NEEDED entry. Choose the client implementation per
      # jackClient:
      #   pipewire — the closure's pipewire.jack client (speaks the
      #     pipewire protocol; libjack2 kept as fallback). Hermetic.
      #   jack2    — the closure's libjack2 (jackd wire protocol only).
      #   host     — nothing from the closure; probe pipewire-jack's
      #     private dir (/usr/lib/pipewire-0.3/jack on Arch, absent no-op
      #     elsewhere) and let the host's default search
      #     (/etc/ld.so.cache, /usr/lib) provide the rest. Non-hermetic.
      # NEVER expose /usr/lib wholesale: system libs (e.g. an older
      # libjansson) would shadow the closure's and break symbol-version
      # lookups (JANSSON_4 not found).
      jackLibPaths =
        if jackClient == "pipewire" then
          [ pipewire.jack libjack2 ]
        else if jackClient == "jack2" then
          [ libjack2 ]
        else if jackClient == "host" then
          [ ]
        else
          throw "jackClient must be \"pipewire\", \"jack2\" or \"host\"";
      # Flag list built in nix (not bash string interpolation) so empty
      # modes can never leave a dangling backslash-continuation.
      # makeLibraryPath appends "/lib" itself — do NOT append manually
      # (produces ".../lib/lib", a dir that never exists).
      # host GL mode: glvnd must dlopen the HOST's vendor lib
      # (libGLX_nvidia on nvidia hosts, libGLX_mesa elsewhere), but a nix
      # binary's dlopen never sees /usr/lib (see glDriver comment above)
      # and the vendor differs per host, so it cannot be vendored
      # hermetically. A per-user shim dir of symlinks makes the host
      # vendor + its private deps visible without exposing /usr/lib
      # wholesale. Sourced via makeWrapper --run so the export reaches
      # the wrapper env (make-wrapper.sh embeds --run commands verbatim
      # in the wrapper shell).
      glHostShim = ''
        # Refresh symlinks on every start so driver updates are picked
        # up. Missing globs stay literal and fail the [ -e ] test, so
        # this is inert on hosts whose driver it does not match; a
        # vendor-less host (headless) exports nothing.
        _glshim="''${XDG_RUNTIME_DIR:-/tmp}/.jaybird-glvendor-$(id -u)"
        mkdir -p "$_glshim" 2>/dev/null || return 0
        _gldid=""
        for _f in \
          /usr/lib/libGLX_*.so.* \
          /usr/lib/libEGL_*.so.* \
          /usr/lib/libnvidia-*.so.* \
          /usr/lib/libgallium*.so.* \
          /usr/lib/libglapi.so.* \
          /run/opengl-driver/lib/libGLX_*.so.* \
          /run/opengl-driver/lib/libEGL_*.so.*
        do
          if [ -e "$_f" ]; then
            ln -sf "$_f" "$_glshim/" && _gldid=1
          fi
        done
        unset _f
        if [ -n "$_gldid" ]; then
          export LD_LIBRARY_PATH="$_glshim''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        fi
        unset _gldid _glshim
      '';
      glLibPaths =
        if glDriver == "mesa" then
          [ mesa.drivers ]
        else
          [ ];
      # host GL mode wrapper flags: source the shim script (a store
      # file, interpolated at nix-eval time into the flag text) before
      # the jack suffix flags — its export prepends the shim dir to
      # LD_LIBRARY_PATH ahead of everything else.
      glFlags =
        if glDriver == "mesa" then
          [ ("--prefix LD_LIBRARY_PATH : "
             + lib.makeLibraryPath glLibPaths) ]
        else if glDriver == "host" then
          [ (''--run "source ${glHostShimFile}"'') ]
        else
          throw "glDriver must be \"mesa\" or \"host\"";
      jackFlags =
        lib.optionals (jackClient == "host")
          [ "--prefix LD_LIBRARY_PATH : /usr/lib/pipewire-0.3/jack" ]
        ++ glFlags
        ++ [ ("--suffix LD_LIBRARY_PATH : "
             + lib.makeLibraryPath (jackLibPaths ++ [ alsa-lib ])) ];
      glHostShimFile = writeText "jaybird-glhost-shim.sh" glHostShim;
      wrap = bin: ''
        wrapProgram $out/bin/${bin} \
          ${lib.concatStringsSep " \\\n          " jackFlags}
      '';
    in
    ''
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

    ${wrap "Cardinal"}
    ${wrap "CardinalMini"}

    # developer test tool, like nixpkgs cardinal
    rm -f $out/bin/CardinalNative
  '';

  passthru = {
    inherit configPath;
    inherit ccacheDir;
    inherit jackClient;
    inherit glDriver;
  };

  meta = with lib; {
    description = "JayBird — a Cardinal (VCV Rack) fork with selectable module builds";
    homepage = "https://github.com/rainey/JayBird";
    license = licenses.gpl3Plus;
    platforms = platforms.linux;
    mainProgram = "Cardinal";
  };
})
