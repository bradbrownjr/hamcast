"""DMR ID -> callsign, via the RadioID.net API, cached on disk.

DMR packets carry only numeric IDs. A lookup never blocks the audio path:
an unknown ID is shown as its number and fetched in the background, and the
answer is used from then on (and saved, so it survives restarts). Hotspot
IDs (a 7-digit ID plus a 2-digit suffix) are looked up by their base ID.
"""

import asyncio
import json
import logging
import urllib.request
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

API = "https://radioid.net/api/dmr/user/?id={}"


def base_id(radio_id: int) -> int:
    return radio_id // 100 if radio_id > 9_999_999 else radio_id


def _fetch(radio_id: int) -> str | None:
    req = urllib.request.Request(API.format(radio_id), headers={"User-Agent": "hamcast"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        results = json.load(resp).get("results") or []
    return results[0]["callsign"].upper() if results else None


class CallsignCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._known: dict[str, str | None] = {}
        self._pending: set[int] = set()
        if path and path.exists():
            try:
                self._known = json.loads(path.read_text())
            except (OSError, ValueError):
                log.warning("ignoring unreadable callsign cache %s", path)

    def lookup(self, radio_id: int, on_resolved: Callable[[str], None] | None = None) -> str:
        """The callsign if known, else the number (and start a lookup that
        calls on_resolved with the callsign if it finds one)."""
        key = str(base_id(radio_id))
        if self._known.get(key):
            return self._known[key]
        if key not in self._known and int(key) not in self._pending:
            self._pending.add(int(key))
            asyncio.get_running_loop().create_task(self._resolve(int(key), on_resolved))
        return str(radio_id)

    async def _resolve(self, key: int, on_resolved) -> None:
        try:
            callsign = await asyncio.get_running_loop().run_in_executor(None, _fetch, key)
        except Exception as exc:  # network trouble: try again next time this ID talks
            log.debug("RadioID lookup for %d failed: %s", key, exc)
            self._pending.discard(key)
            return
        self._pending.discard(key)
        self._known[str(key)] = callsign
        self._save()
        if callsign and on_resolved:
            on_resolved(callsign)

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._known, sort_keys=True))
        except OSError as exc:
            log.warning("cannot save callsign cache %s: %s", self.path, exc)
