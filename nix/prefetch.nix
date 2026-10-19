# Prefetched Rack dep sources (gitignored in Rack's tree, downloaded at
# build time by src/Rack/dep/Makefile). Versions and hashes match that
# Makefile exactly (verified: SRI hashes converted from the Makefile's
# raw sha256 lines). SPDX-License-Identifier: GPL-3.0-or-later
{
  fetchzip,
  runCommand,
}:

let
  jansson = fetchzip {
    url = "https://github.com/akheron/jansson/releases/download/v2.12/jansson-2.12.tar.gz";
    hash = "sha256-7ekWk35dBPCrrjQJUNIcHyh1F2/CADTDl96pqJQccR0=";
  };

  libarchive = fetchzip {
    url = "https://github.com/libarchive/libarchive/releases/download/v3.4.3/libarchive-3.4.3.tar.gz";
    hash = "sha256-S/Qoi3/L/B6VXw+v91Q2Q0CCKPeHyOApz8B1uJq6u88=";
  };

  libsamplerate = fetchzip {
    url = "https://github.com/libsndfile/libsamplerate/releases/download/0.1.9/libsamplerate-0.1.9.tar.gz";
    hash = "sha256-1ThHKlHS01iYP/R44AewAUjl7Im9PA4M1CwORfLoo7o=";
  };

  zstd = fetchzip {
    url = "https://github.com/facebook/zstd/releases/download/v1.4.5/zstd-1.4.5.tar.gz";
    hash = "sha256-FI3L8EmRthpWrCwOAXSTlc162ieYjDUoq9Y5TSbFwys=";
  };
in
runCommand "jaybird-rack-dep-sources" { } ''
  mkdir -p $out
  ln -s ${jansson} $out/jansson-2.12
  ln -s ${libarchive} $out/libarchive-3.4.3
  ln -s ${libsamplerate} $out/libsamplerate-0.1.9
  ln -s ${zstd} $out/zstd-1.4.5
''
