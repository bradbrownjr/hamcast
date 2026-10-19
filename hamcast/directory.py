"""Public reflector and master lists for the dashboard's pickers.

Pi-Star's host files (https://www.pistar.uk/downloads/) are the lists most
hotspots use:
  YSF_Hosts.txt   id;name;description;host;port;flags
  DMR_Hosts.txt   name  id  host  password  port   (whitespace separated)
Each is cached in <data_dir>/directory for a day; if a refresh fails the
cached copy is used.
"""

import logging
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

SOURCES = {
    "ysf": "https://www.pistar.uk/downloads/YSF_Hosts.txt",
    "dmr": "https://www.pistar.uk/downloads/DMR_Hosts.txt",
}
MAX_AGE = 24 * 3600


def _text(kind: str, cache_dir: Path) -> str:
    cache = cache_dir / f"{kind}_hosts.txt"
    if cache.exists() and time.time() - cache.stat().st_mtime < MAX_AGE:
        return cache.read_text(errors="replace")
    try:
        req = urllib.request.Request(SOURCES[kind], headers={"User-Agent": "hamcast"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8", "replace")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text)
        return text
    except Exception as exc:
        log.warning("cannot refresh %s host list: %s", kind, exc)
        return cache.read_text(errors="replace") if cache.exists() else ""


def parse_ysf(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split(";")
        if len(f) >= 5 and f[4].strip().isdigit():
            out.append({"id": f[0].strip(), "name": f[1].strip(), "description": f[2].strip(),
                        "host": f[3].strip(), "port": int(f[4])})
    return out


def parse_dmr(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split()
        if len(f) >= 5 and f[-1].isdigit():
            out.append({"name": f[0], "id": f[1], "host": f[2], "password": f[3], "port": int(f[-1])})
    return out


def listing(kind: str, cache_dir: Path) -> list[dict]:
    text = _text(kind, cache_dir)
    return parse_ysf(text) if kind == "ysf" else parse_dmr(text)
