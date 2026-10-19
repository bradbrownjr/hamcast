"""Past transmissions, read back from the recordings folder.

Each recording <stamp>_<talker>.wav has a <stamp>_<talker>.json beside it,
written when the transmission ends (talker, gateway, mode, start, length)
and completed by the transcriber (text and segments). Recordings made
before the .json was written for every transmission have only the WAV;
their talker and start time come from the file name.

File names start with the local start time (YYYYMMDD-HHMMSS), so sorting
them by name sorts them by time.
"""

import json
import logging
import re
import time
import wave
from pathlib import Path

from .stream import Heard

log = logging.getLogger(__name__)


def metadata(heard: Heard) -> dict:
    return {"talker": heard.talker, "gateway": heard.gateway, "mode": heard.mode,
            "started": heard.started, "seconds": round(heard.seconds, 1)}


def write_metadata(heard: Heard) -> None:
    """Save what is known about a finished, recorded transmission."""
    if heard.recording:
        Path(heard.recording).with_suffix(".json").write_text(json.dumps(metadata(heard), indent=1))


def _read(wav: Path, min_seconds: float, transcribed: bool) -> Heard | None:
    try:
        meta = json.loads(wav.with_suffix(".json").read_text())
    except FileNotFoundError:
        meta = None
    except ValueError:
        log.warning("ignoring unreadable %s", wav.with_suffix(".json"))
        meta = None
    if meta:
        started, seconds = float(meta["started"]), float(meta["seconds"])
        heard = Heard(talker=meta.get("talker") or "unknown", gateway=meta.get("gateway") or "",
                      started=started, ended=started + seconds, mode=meta.get("mode") or "",
                      recording=str(wav))
    else:
        stamp, _, talker = wav.stem.partition("_")
        try:
            started = time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S"))
            with wave.open(str(wav)) as w:
                seconds = w.getnframes() / w.getframerate()
        except (ValueError, OSError, EOFError, wave.Error):
            return None
        # TransmissionRecorder adds -2, -3, ... when a name is taken.
        heard = Heard(talker=re.sub(r"-\d+$", "", talker) or "unknown",
                      gateway="", started=started, ended=started + seconds, recording=str(wav))
    if meta and "text" in meta:
        heard.transcript = meta["text"] or None
        heard.transcript_status = "done" if meta["text"] else "no_speech"
    elif transcribed:
        heard.transcript_status = "too_short" if heard.seconds < min_seconds else "not_transcribed"
    return heard


def load(directory: Path, before: str | None = None, limit: int = 50,
         min_seconds: float = 1.5, transcribed: bool = True) -> tuple[list[Heard], bool]:
    """Up to `limit` transmissions, newest first, older than the recording
    named `before` (a file name) if given. Also says whether older ones remain."""
    if not directory.is_dir():
        return [], False
    names = sorted((p.name for p in directory.glob("*.wav")), reverse=True)
    if before:
        names = [n for n in names if n < before]
    out: list[Heard] = []
    for name in names:
        if len(out) == limit:
            return out, True
        heard = _read(directory / name, min_seconds, transcribed)
        if heard:
            out.append(heard)
    return out, False
