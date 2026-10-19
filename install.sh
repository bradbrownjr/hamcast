#!/bin/sh
# Install hamcast without Docker.
#
#   ./install.sh [--prefix DIR] [--no-icecast] [--whisper] [--service]
#
#   --prefix DIR   where hamcast goes (default /opt/hamcast)
#   --no-icecast   don't install Icecast (you'll set HAMCAST_ICECAST_URL)
#   --whisper      also install the built-in Whisper (faster-whisper)
#   --service      install and enable a systemd service (Linux)
#
# Detects the OS and installs what hamcast needs with its package manager:
# Python 3.11+, a C compiler, git, curl, ffmpeg (with the LAME MP3 encoder),
# Node.js 20.19+ (to build the web app) and Icecast. Package names were checked against repology.org; Arch has
# Icecast only in the AUR, so it is skipped there.
set -eu

PREFIX=/opt/hamcast
ICECAST=1
WHISPER=0
SERVICE=0
REPO=https://github.com/bradbrownjr/hamcast.git

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --no-icecast) ICECAST=0; shift ;;
        --whisper) WHISPER=1; shift ;;
        --service) SERVICE=1; shift ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

SUDO=""
if [ "$(id -u)" != "0" ]; then
    command -v sudo >/dev/null 2>&1 || die "run as root or install sudo"
    SUDO=sudo
fi

# ========== SYSTEM PACKAGES ==========

OS="$(uname -s)"
ID=""; ID_LIKE=""
if [ -r /etc/os-release ]; then
    . /etc/os-release
fi
say "Installing system packages for ${PRETTY_NAME:-$OS}"

case "$OS:$ID:$ID_LIKE" in
    Darwin:*)
        command -v brew >/dev/null 2>&1 || die "install Homebrew first: https://brew.sh"
        brew install python git ffmpeg node $( [ $ICECAST = 1 ] && echo icecast )
        ;;
    Linux:debian:*|Linux:ubuntu:*|Linux:raspbian:*|Linux:*:*debian*|Linux:*:*ubuntu*)
        $SUDO apt-get update
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            python3 python3-venv gcc libc6-dev git curl ca-certificates ffmpeg nodejs npm \
            $( [ $ICECAST = 1 ] && echo icecast2 )
        ;;
    Linux:fedora:*|Linux:rhel:*|Linux:centos:*|Linux:rocky:*|Linux:almalinux:*|Linux:*:*fedora*|Linux:*:*rhel*)
        if [ "$ID" != "fedora" ]; then
            $SUDO dnf install -y epel-release || true  # ffmpeg and icecast come from EPEL on RHEL clones
        fi
        $SUDO dnf install -y python3 gcc glibc-devel git curl nodejs npm
        $SUDO dnf install -y ffmpeg-free || $SUDO dnf install -y ffmpeg
        [ $ICECAST = 1 ] && $SUDO dnf install -y icecast
        ;;
    Linux:arch:*|Linux:*:*arch*)
        $SUDO pacman -Sy --needed --noconfirm python gcc git curl ffmpeg nodejs npm
        if [ $ICECAST = 1 ]; then
            echo "Icecast is only in the AUR on Arch; install it with your AUR helper, or use --no-icecast."
        fi
        ;;
    Linux:alpine:*)
        $SUDO apk add --no-cache python3 py3-pip gcc musl-dev git curl ffmpeg nodejs npm $( [ $ICECAST = 1 ] && echo icecast )
        if [ $WHISPER = 1 ]; then
            echo "faster-whisper has no musl wheels; skipping --whisper on Alpine (use HAMCAST_STT_URL)."
            WHISPER=0
        fi
        ;;
    *)
        die "unsupported system ($OS ${ID:-unknown}); install Python 3.11+, gcc, git, curl, ffmpeg and Icecast yourself, then rerun with those present"
        ;;
esac

PY="$(command -v python3 || true)"
[ -n "$PY" ] || die "python3 not found"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || die "hamcast needs Python 3.11 or newer ($("$PY" --version) found)"
node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 20 || (a === 20 && b >= 19) ? 0 : 1)' \
    || die "the web app needs Node.js 20.19 or newer ($(node --version 2>/dev/null || echo none) found); install a newer Node.js and rerun"
ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libmp3lame \
    || die "ffmpeg has no MP3 encoder (libmp3lame); install an ffmpeg build with LAME"

# ========== HAMCAST ==========

say "Installing hamcast into $PREFIX"
$SUDO mkdir -p "$PREFIX"
$SUDO chown "$(id -u):$(id -g)" "$PREFIX"
here="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$here/pyproject.toml" ] && [ -d "$here/hamcast" ]; then
    SRC="$here"
else
    SRC="$PREFIX/src"
    if [ -d "$SRC/.git" ]; then git -C "$SRC" pull -q; else git clone -q "$REPO" "$SRC"; fi
fi

"$SRC/native/build.sh" "$PREFIX/lib"
(cd "$SRC/web" && npm ci --no-audit --no-fund && npm run build)
"$PY" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q --upgrade pip
if [ $WHISPER = 1 ]; then
    "$PREFIX/venv/bin/pip" install -q "$SRC[whisper]"
else
    "$PREFIX/venv/bin/pip" install -q "$SRC"
fi

# ========== CONFIGURATION ==========

if [ "$OS" = "Darwin" ]; then
    CONF_DIR="$PREFIX/config"; DATA_DIR="$PREFIX/data"
else
    CONF_DIR=/etc/hamcast; DATA_DIR=/var/lib/hamcast
fi
$SUDO mkdir -p "$CONF_DIR" "$DATA_DIR"
if [ ! -f "$CONF_DIR/config.yaml" ]; then
    $SUDO cp "$SRC/config.example.yaml" "$CONF_DIR/config.yaml"
fi
if [ ! -f "$CONF_DIR/hamcast.env" ]; then
    $SUDO sh -c "sed -e '/HOST_PORT/d' -e '/^PUID/d' -e '/^PGID/d' '$SRC/.env.example' > '$CONF_DIR/hamcast.env'"
    $SUDO sh -c "printf '\nHAMCAST_DATA_DIR=%s\nHAMCAST_LIBHCMBE=%s\n' '$DATA_DIR' '$PREFIX/lib/libhcmbe.so' >> '$CONF_DIR/hamcast.env'"
    $SUDO chmod 600 "$CONF_DIR/hamcast.env"
fi

if [ $SERVICE = 1 ]; then
    command -v systemctl >/dev/null 2>&1 || die "--service needs systemd"
    say "Installing the systemd service"
    id hamcast >/dev/null 2>&1 || $SUDO useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin hamcast
    $SUDO chown -R hamcast: "$DATA_DIR"
    $SUDO chown hamcast: "$CONF_DIR/hamcast.env"
    $SUDO tee /etc/systemd/system/hamcast.service >/dev/null <<EOF
[Unit]
Description=hamcast - digital voice nets to Icecast
After=network-online.target
Wants=network-online.target

[Service]
User=hamcast
EnvironmentFile=$CONF_DIR/hamcast.env
ExecStart=$PREFIX/venv/bin/hamcast serve --config $CONF_DIR/config.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable hamcast
fi

say "Done"
cat <<EOF
Next:
  1. Set your callsign (and DMR ID) in $CONF_DIR/hamcast.env
  2. List your nets in $CONF_DIR/config.yaml
EOF
if [ $SERVICE = 1 ]; then
    echo "  3. sudo systemctl start hamcast; dashboard on http://localhost:8080"
else
    echo "  3. set -a; . $CONF_DIR/hamcast.env; set +a"
    echo "     $PREFIX/venv/bin/hamcast serve --config $CONF_DIR/config.yaml"
fi
