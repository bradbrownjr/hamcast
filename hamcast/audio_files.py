"""What happens to a transmission's WAV after it is recorded.

Clips shorter than the transcription minimum (kerchunks, IDs) are deleted.
The rest are kept as WAV until transcribed, so speech-to-text gets the
audio exactly as received, then compressed to MP3 (a quarter of the size
at 32k). Audio older than HAMCAST_AUDIO_DAYS is deleted; the database row
and transcript stay.
"""

import asyncio
import logging
import wave
from pathlib import Path

log = logging.getLogger(__name__)


def duration(path: Path) -> float:
    """Seconds of audio in a WAV (0 if unreadable)."""
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    except (OSError, EOFError, wave.Error):
        return 0.0


async def compress(wav: Path, bitrate: str) -> Path | None:
    """WAV to MP3 beside it; the WAV is deleted. None if ffmpeg failed."""
    mp3 = wav.with_suffix(".mp3")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(wav),
        "-codec:a", "libmp3lame", "-b:a", bitrate, str(mp3),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0 or not mp3.exists():
        log.warning("compressing %s failed: %s", wav.name, err.decode(errors="replace").strip())
        mp3.unlink(missing_ok=True)
        return None
    wav.unlink(missing_ok=True)
    return mp3
