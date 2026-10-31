# JayBird flake.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Usage:
#   nix build .#jaybird        # build-all
#   nix build .#test           # profile kconfig/configs/test.config
#   nix build .#full           # like build-all, plus phone-home plugins (no STRICT_NO_PHONE_HOME)
#   nix build .#<out>-ccache --option extra-sandbox-paths /var/tmp/jaybird-ccache
#                              # same, compiling through ccache (fast rebuilds;
#                              # pass the sandbox option or caching is ephemeral)
#   nix run .#menuconfig       # edit kconfig/configs/default.config
#
# Commit changes before building: flake sources use builtins.fetchGit.

{
  description = "JayBird — a DISTRHO Cardinal (VCV Rack) fork with selectable module builds";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      inherit (nixpkgs) lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);
      nixpkgsFor = forAllSystems (system: import nixpkgs { inherit system; });

      callJaybird =
        pkgs: args:
        pkgs.callPackage ./nix/package.nix args;

      # Source with submodules, pinned by the rev in nix/source-rev
      # (written by `make nix-update-rev`; pure-eval requires a rev).
      self-src = forAllSystems (
        _:
        builtins.fetchGit {
          url = "file:///storage/69/vcvprojects/JayBird";
          submodules = true;
          allRefs = true;
          rev = lib.removeSuffix "\n" (builtins.readFile ./nix/source-rev);
        }
      );

      # Rack dep sources that are gitignored upstream (downloaded at build
      # time by src/Rack/dep/Makefile) — prefetched for sandboxed builds.
      prefetchDeps = forAllSystems (
        system: (nixpkgsFor.${system}.callPackage ./nix/prefetch.nix { })
      );

      # Named profiles live in kconfig/configs/*.config. Pass ccacheDir
      # (non-null) to emit `<name>-ccache` variants that compile through
      # ccache with a host-side cache directory.
      profilePackages =
        { pkgs, src, deps, ccacheDir ? null, jackClient ? "pipewire", glDriver ? "mesa" }:
        let
          inherit (pkgs) lib;
          suffix =
            (if ccacheDir == null then "" else "-ccache")
            # non-default jack/gl clients get an explicit suffix
            + (if jackClient == "pipewire" then "" else "-${jackClient}")
            + (if glDriver == "mesa" then "" else "-gl-${glDriver}");
          configs = lib.filterAttrs (
            name: type: type == "regular" && lib.hasSuffix ".config" name
          ) (builtins.readDir ./kconfig/configs);
        in
        lib.listToAttrs (
          lib.mapAttrsToList (
            name: _:
            lib.nameValuePair (lib.removeSuffix ".config" name + suffix) (
              callJaybird pkgs {
                srcArg = src;
                prefetchedDeps = deps;
                configPath = ./kconfig/configs + "/${name}";
                inherit ccacheDir jackClient glDriver;
              }
            )
          ) configs
        );
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgsFor.${system};
        in
        {
          jaybird = callJaybird pkgs { srcArg = self-src.${system}; prefetchedDeps = prefetchDeps.${system}; };
          jaybird-ccache = callJaybird pkgs {
            srcArg = self-src.${system};
            prefetchedDeps = prefetchDeps.${system};
            ccacheDir = "/var/tmp/jaybird-ccache";
          };
          default = self.packages.${system}.jaybird;
        }        // profilePackages { inherit pkgs; src = self-src.${system}; deps = prefetchDeps.${system}; }
                  // profilePackages {
                    inherit pkgs;
                    src = self-src.${system};
                    deps = prefetchDeps.${system};
                    ccacheDir = "/var/tmp/jaybird-ccache";
                  }
                  // profilePackages {
                    inherit pkgs;
                    src = self-src.${system};
                    deps = prefetchDeps.${system};
                    ccacheDir = "/var/tmp/jaybird-ccache";
                    jackClient = "host";
                  }
                  // profilePackages {
                    inherit pkgs;
                    src = self-src.${system};
                    deps = prefetchDeps.${system};
                    ccacheDir = "/var/tmp/jaybird-ccache";
                    glDriver = "host";
                  }
                  // profilePackages {
                    inherit pkgs;
                    src = self-src.${system};
                    deps = prefetchDeps.${system};
                    ccacheDir = "/var/tmp/jaybird-ccache";
                    jackClient = "jack2";
                  }
      );

      apps = forAllSystems (
        system:
        let
          pkgs = nixpkgsFor.${system};
          menuconfig = pkgs.writeShellApplication {
            name = "jaybird-menuconfig";
            text = ''
              set -euo pipefail
              CONFIG=''${1:-default}
              KCONFIG_CONFIG="$PWD/kconfig/configs/$CONFIG.config"
              srctree="$PWD/kconfig" python3 ${pkgs.kconfiglib}/bin/menuconfig "$PWD/kconfig/Kconfig"
            '';
          };
        in
        {
          menuconfig = {
            type = "app";
            program = "${menuconfig}/bin/jaybird-menuconfig";
          };
          default = self.apps.${system}.menuconfig;
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgsFor.${system};
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              cmake
              file
              pkg-config
              (python3.withPackages (p: [ p.pyyaml p.kconfiglib ]))
              kconfiglib
            ];
            buildInputs = with pkgs; [
              alsa-lib
              dbus
              fftwFloat
              freetype
              jansson
              libGL
              libglvnd
              libjack2
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
          };
        }
      );
    };
}
