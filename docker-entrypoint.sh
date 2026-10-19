#!/bin/sh
# Run hamcast as PUID:PGID (Unraid's nobody:users, 99:100, by default).
# Icecast refuses to run as root, and files in /data should belong to the
# host user rather than root.
set -e
PUID="${PUID:-99}"
PGID="${PGID:-100}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    find /data \( ! -uid "$PUID" -o ! -gid "$PGID" \) -exec chown "$PUID:$PGID" {} +
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --inh-caps=-all hamcast "$@"
fi
exec hamcast "$@"
