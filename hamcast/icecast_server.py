"""The bundled Icecast: used when no external Icecast is configured.

hamcast writes an icecast.xml, runs Icecast as a child process and restarts
it if it exits. Passwords come from the configuration, or are generated
once and kept in <data_dir>/icecast-passwords.json so they survive restarts
(the admin password is needed to use Icecast's own admin pages).

Icecast refuses to run as root (Icecast-Server main.c, "You should not run
icecast2 as root"); the container entrypoint drops privileges first.
"""

import asyncio
import json
import logging
import secrets
import shutil
import urllib.parse
from pathlib import Path
from xml.sax.saxutils import escape

from .config import Config

log = logging.getLogger(__name__)

RUN_DIR = Path("/tmp/hamcast-icecast")
# Debian/Ubuntu install Icecast's web files here; other systems are found
# relative to the binary.
_SHARE_CANDIDATES = [Path("/usr/share/icecast2"), Path("/usr/share/icecast"),
                     Path("/usr/local/share/icecast"), Path("/opt/homebrew/share/icecast")]


def _binary() -> str | None:
    return shutil.which("icecast2") or shutil.which("icecast")


def _share_dir() -> Path:
    for p in _SHARE_CANDIDATES:
        if (p / "web").is_dir():
            return p
    return _SHARE_CANDIDATES[0]


def ensure_passwords(cfg: Config) -> None:
    """Fill in missing bundled-Icecast passwords from (or into) the data dir."""
    ice = cfg.icecast
    store = cfg.data_dir / "icecast-passwords.json"
    saved = {}
    if store.exists():
        try:
            saved = json.loads(store.read_text())
        except ValueError:
            log.warning("ignoring unreadable %s", store)
    changed = False
    for key in ("source_password", "admin_password"):
        if not getattr(ice, key):
            if not saved.get(key):
                saved[key] = secrets.token_urlsafe(16)
                changed = True
            setattr(ice, key, saved[key])
    if changed:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(saved, indent=2))
        store.chmod(0o600)
        log.info("generated bundled Icecast passwords in %s", store)


def push_url(cfg: Config) -> str:
    return f"icecast://source:{cfg.icecast.source_password}@127.0.0.1:{cfg.icecast.port}"


def _hostname(cfg: Config) -> str:
    """The host listeners reach, for the URLs Icecast reports."""
    ice = cfg.icecast
    if ice.hostname != "localhost" or not ice.public_url:
        return ice.hostname
    return urllib.parse.urlsplit(ice.public_url).hostname or ice.hostname


def render_xml(cfg: Config) -> str:
    ice = cfg.icecast
    share = _share_dir()
    # Room for nets added from the dashboard later, plus a few external
    # sources (e.g. BUTT feeding an EchoLink node's audio).
    sources = max(32, len(cfg.streams) + 8)
    return f"""<icecast>
    <location>hamcast</location>
    <admin>hamcast</admin>
    <hostname>{escape(_hostname(cfg))}</hostname>
    <limits>
        <clients>500</clients>
        <sources>{sources}</sources>
        <queue-size>524288</queue-size>
        <client-timeout>30</client-timeout>
        <header-timeout>15</header-timeout>
        <source-timeout>10</source-timeout>
        <burst-on-connect>1</burst-on-connect>
        <burst-size>65535</burst-size>
    </limits>
    <authentication>
        <source-password>{escape(ice.source_password)}</source-password>
        <relay-password>{escape(secrets.token_urlsafe(16))}</relay-password>
        <admin-user>admin</admin-user>
        <admin-password>{escape(ice.admin_password)}</admin-password>
    </authentication>
    <listen-socket>
        <port>{ice.port}</port>
    </listen-socket>
    <!-- Lets web apps (e.g. ECTLogger's player) read the stream and status.
         No comments inside http-headers: Icecast stops parsing headers at
         the first child that isn't <header> (cfgfile.c _parse_http_headers). -->
    <http-headers>
        <header name="Access-Control-Allow-Origin" value="*" />
    </http-headers>
    <fileserve>1</fileserve>
    <paths>
        <basedir>{share}</basedir>
        <logdir>{RUN_DIR}</logdir>
        <webroot>{share / "web"}</webroot>
        <adminroot>{share / "admin"}</adminroot>
    </paths>
    <logging>
        <errorlog>-</errorlog>
        <accesslog>access.log</accesslog>
        <loglevel>2</loglevel>
    </logging>
    <security>
        <chroot>0</chroot>
    </security>
</icecast>
"""


class BundledIcecast:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.running = False

    async def run(self, stop: asyncio.Event) -> None:
        binary = _binary()
        if not binary:
            log.error("no Icecast found: install icecast2, or set HAMCAST_ICECAST_URL to use an external one")
            return
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        conf = RUN_DIR / "icecast.xml"
        conf.write_text(render_xml(self.cfg))
        conf.chmod(0o600)
        while not stop.is_set():
            proc = await asyncio.create_subprocess_exec(binary, "-c", str(conf))
            self.running = True
            log.info("bundled Icecast started on port %d", self.cfg.icecast.port)
            waiter = asyncio.create_task(proc.wait())
            stopper = asyncio.create_task(stop.wait())
            await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
            self.running = False
            if stop.is_set():
                proc.terminate()
                await waiter
                break
            stopper.cancel()
            log.warning("bundled Icecast exited (%s), restarting", proc.returncode)
            await asyncio.sleep(3)
