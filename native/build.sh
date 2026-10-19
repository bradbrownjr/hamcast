#!/bin/sh
# Build libhcmbe.so: mbelib plus the hcmbe.c shim, in one shared library.
#
#   native/build.sh [output-dir]
#
# mbelib is fetched at a pinned commit so every build decodes identically.
# Needs git, gcc and libm; no cmake.
set -eu

MBELIB_REPO="https://github.com/szechyjs/mbelib.git"
MBELIB_COMMIT="9a04ed5c78176a9965f3d43f7aa1b1f5330e771f"

here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git clone -q "$MBELIB_REPO" "$work/mbelib"
git -C "$work/mbelib" checkout -q "$MBELIB_COMMIT"

mkdir -p "$out"
gcc -O2 -fPIC -shared -I"$work/mbelib" \
    "$work"/mbelib/ecc.c \
    "$work"/mbelib/mbelib.c \
    "$work"/mbelib/ambe3600x2400.c \
    "$work"/mbelib/ambe3600x2450.c \
    "$work"/mbelib/imbe7200x4400.c \
    "$work"/mbelib/imbe7100x4400.c \
    "$here/hcmbe.c" \
    -lm -o "$out/libhcmbe.so"

echo "built $out/libhcmbe.so (mbelib $MBELIB_COMMIT)"
