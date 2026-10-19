"""Icecast helpers: stream metadata updates and listener counts."""

import base64
import json
import logging
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


def _http_base(push_url: str) -> tuple[str, str]:
    """icecast://user:pw@host:port -> ("http://host:port", "Basic ...")."""
    u = urllib.parse.urlsplit(push_url)
    auth = base64.b64encode(f"{u.username}:{u.password}".encode()).decode()
    return f"http://{u.hostname}:{u.port or 8000}", f"Basic {auth}"


def set_title(push_url: str, mount: str, title: str) -> None:
    """Set the "now playing" title. Icecast accepts the mount's own source
    credentials for this, so no separate admin password is needed.
    Blocking; call from a thread."""
    base, auth = _http_base(push_url)
    q = urllib.parse.urlencode({"mount": mount, "mode": "updinfo", "song": title})
    req = urllib.request.Request(f"{base}/admin/metadata?{q}", headers={"Authorization": auth})
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:
        log.debug("metadata update for %s failed: %s", mount, exc)


def listener_counts(push_url: str) -> dict[str, int]:
    """Listeners per mount from the public status-json.xsl. Blocking."""
    base, _ = _http_base(push_url)
    try:
        with urllib.request.urlopen(f"{base}/status-json.xsl", timeout=5) as resp:
            data = json.load(resp)
    except Exception as exc:
        log.debug("listener count failed: %s", exc)
        return {}
    sources = data.get("icestats", {}).get("source", [])
    if isinstance(sources, dict):  # Icecast returns a bare object for one mount
        sources = [sources]
    out = {}
    for s in sources:
        mount = "/" + s.get("listenurl", "").rsplit("/", 1)[-1]
        out[mount] = int(s.get("listeners", 0))
    return out
