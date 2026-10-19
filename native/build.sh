#!/bin/sh
# Build libhcmbe.so: mbelib-neo plus the hcmbe.c shim, in one shared library.
#
#   native/build.sh [output-dir]
#
# mbelib-neo and the PFFFT revision it pins are fetched at fixed versions
# (the PFFFT archive is checksum-verified, as mbelib-neo's own CMake build
# does) so every build decodes identically. Needs git, curl, gcc and libm;
# no cmake.
set -eu

NEO_REPO="https://github.com/arancormonk/mbelib-neo.git"
NEO_TAG="v2.6.0"
NEO_COMMIT="2b69ade768095ea25e94abe1d4f2bb429fcd2f0c"
NEO_VERSION="2.6.0"
# From mbelib-neo tools/ci-dependency-pins.env at NEO_TAG.
PFFFT_SHA="94d3c8323a530c5e60a2535505166366171c1fdb"
PFFFT_ARCHIVE_SHA256="18339f8f518f1837785120881857f98b3c0d028200967354bf422e9eb5181f6a"

here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git clone -q --depth 1 --branch "$NEO_TAG" "$NEO_REPO" "$work/neo"
test "$(git -C "$work/neo" rev-parse HEAD)" = "$NEO_COMMIT"

curl -fsSL -o "$work/pffft.tgz" "https://codeload.github.com/arancormonk/pffft/tar.gz/$PFFFT_SHA"
echo "$PFFFT_ARCHIVE_SHA256  $work/pffft.tgz" | sha256sum -c -
mkdir "$work/pffft"
tar xzf "$work/pffft.tgz" -C "$work/pffft" --strip-components=1

# CMake normally generates this from version.h.in.
mkdir -p "$work/gen/mbelib-neo"
sed "s/@PROJECT_VERSION@/$NEO_VERSION/" "$work/neo/include/mbelib-neo/version.h.in" \
    > "$work/gen/mbelib-neo/version.h"

src="$work/neo/src"
mkdir -p "$out"
gcc -O2 -fPIC -shared -std=c11 -D_GNU_SOURCE -DMBE_BUILDING=1 -DPFFFT_STATIC_DEFINE \
    -I"$work/neo/include" -I"$work/gen" -I"$work/neo" -I"$src/internal" \
    -I"$work/pffft/include/pffft" \
    "$src"/ambe/*.c "$src"/ecc/*.c "$src"/imbe/*.c "$src"/core/*.c "$src"/tetra/*.c \
    "$work/pffft/src/pffft.c" "$work/pffft/src/pffft_common.c" \
    "$here/hcmbe.c" \
    -lm -o "$out/libhcmbe.so"

echo "built $out/libhcmbe.so (mbelib-neo $NEO_TAG, PFFFT $PFFFT_SHA)"
