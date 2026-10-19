"""Sign-in for the dashboard's Manage pages.

One shared admin password (HAMCAST_ADMIN_PASSWORD, or generated once into
<data_dir>/admin-password.txt). A successful sign-in sets an HttpOnly
cookie holding an expiry signed with HMAC-SHA256 under a per-install
secret, so nothing is kept server-side and restarts don't sign anyone out.
Failed attempts are throttled per client address.
"""

import hashlib
import hmac
import logging
import secrets
import time
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

COOKIE = "hamcast_session"
SESSION_SECONDS = 30 * 24 * 3600
MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60


def _read_or_create(path: Path, make) -> str:
    if path.exists():
        return path.read_text().strip()
    value = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n")
    path.chmod(0o600)
    return value


class Auth:
    def __init__(self, cfg: Config) -> None:
        pw_file = cfg.data_dir / "admin-password.txt"
        if cfg.admin_password:
            self.password = cfg.admin_password
        else:
            existed = pw_file.exists()
            self.password = _read_or_create(pw_file, lambda: secrets.token_urlsafe(12))
            if not existed:
                log.info("dashboard admin password generated: see %s", pw_file)
        self._secret = _read_or_create(cfg.data_dir / "session-secret", lambda: secrets.token_hex(32)).encode()
        self._failures: dict[str, list[float]] = {}

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def throttled(self, client: str) -> bool:
        now = time.time()
        recent = [t for t in self._failures.get(client, []) if now - t < FAILURE_WINDOW]
        self._failures[client] = recent
        return len(recent) >= MAX_FAILURES

    def login(self, password: str, client: str) -> str | None:
        """A session token, or None (and the failure is counted)."""
        if hmac.compare_digest(password.encode(), self.password.encode()):
            self._failures.pop(client, None)
            expiry = str(int(time.time()) + SESSION_SECONDS)
            return f"{expiry}.{self._sign(expiry)}"
        self._failures.setdefault(client, []).append(time.time())
        return None

    def valid(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        expiry, sig = token.split(".", 1)
        return (hmac.compare_digest(sig, self._sign(expiry))
                and expiry.isdigit() and int(expiry) > time.time())
