"""Recordings made before hamcast kept its database (db.py), imported once
per net at startup.

Each is <stamp>_<talker>.wav, where the stamp is the local start time
(YYYYMMDD-HHMMSS), sometimes with a <stamp>_<talker>.json beside it
holding the talker, gateway, mode, start, length and transcript.
"""

import json
import logging
import re
import time
from pathlib import Path

from .audio_files import duration
from .stream import Heard

log = logging.getLogger(__name__)


def _read(wav: Path) -> Heard | None:
    sidecar = wav.with_suffix(".json")
    meta = None
    if sidecar.exists():
        try:
            meta = json.loads(sidecar.read_text())
        except ValueError:
            log.warning("ignoring unreadable %s", sidecar)
    if meta:
        started, seconds = float(meta["started"]), float(meta["seconds"])
        heard = Heard(talker=meta.get("talker") or "unknown", gateway=meta.get("gateway") or "",
                      started=started, ended=started + seconds, mode=meta.get("mode") or "",
                      recording=str(wav))
        if "text" in meta:
            heard.transcript = meta["text"] or None
            heard.transcript_status = "done" if meta["text"] else "no_speech"
        return heard
    stamp, _, talker = wav.stem.partition("_")
    try:
        started = time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S"))
    except ValueError:
        return None
    # TransmissionRecorder adds -2, -3, ... when a name is taken.
    return Heard(talker=re.sub(r"-\d+$", "", talker) or "unknown", gateway="", started=started,
                 ended=started + duration(wav), recording=str(wav))


def recordings(directory: Path) -> list[Heard]:
    """Every old recording in a net's folder, oldest first."""
    if not directory.is_dir():
        return []
    found = [_read(p) for p in sorted(directory.glob("*.wav"))]
    return [h for h in found if h]
