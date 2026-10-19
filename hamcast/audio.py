"""Real-time PCM clock, jitter buffer and audio sinks.

Network voice arrives in bursts (YSF: five 20 ms frames per packet every
~100 ms) and stops entirely between transmissions. Icecast listeners need an
unbroken real-time stream, so a clock emits exactly one 20 ms frame every
20 ms: decoded audio when there is some, silence when there isn't.
"""

import asyncio
import collections
import logging
import time
import wave
from pathlib import Path

from .vocoder import SAMPLES_PER_FRAME

log = logging.getLogger(__name__)

SAMPLE_RATE = 8000
FRAME_BYTES = SAMPLES_PER_FRAME * 2
FRAME_SECONDS = SAMPLES_PER_FRAME / SAMPLE_RATE
SILENCE = bytes(FRAME_BYTES)

# Hold this many frames at the start of a transmission before playing, so
# normal packet jitter doesn't chop the audio. 10 frames = 200 ms.
PREBUFFER_FRAMES = 10


class PcmSink:
    def write(self, pcm: bytes) -> None: ...
    def close(self) -> None: ...


class JitterClock:
    def __init__(self, sinks: list[PcmSink]) -> None:
        self.sinks = sinks
        self._queue: collections.deque[bytes] = collections.deque()
        self._playing = False

    def push(self, pcm: bytes) -> None:
        self._queue.append(pcm)

    def _next_frame(self) -> bytes:
        if not self._playing and len(self._queue) >= PREBUFFER_FRAMES:
            self._playing = True
        if self._playing and self._queue:
            return self._queue.popleft()
        self._playing = False
        return SILENCE

    async def run(self, stop: asyncio.Event) -> None:
        next_tick = time.monotonic()
        while not stop.is_set():
            frame = self._next_frame()
            for sink in self.sinks:
                try:
                    sink.write(frame)
                except Exception:
                    log.exception("audio sink %r failed", sink)
            next_tick += FRAME_SECONDS
            delay = next_tick - time.monotonic()
            if delay < -1.0:
                # Fell badly behind (host stalled); resync instead of bursting.
                next_tick = time.monotonic()
                delay = 0
            await asyncio.sleep(max(delay, 0))


class FfmpegSink(PcmSink):
    """Pipes PCM to ffmpeg, which encodes MP3 and pushes it as an Icecast source."""

    def __init__(self, icecast_url: str, bitrate: str = "32k", name: str = "", description: str = "") -> None:
        self.icecast_url = icecast_url
        self.bitrate = bitrate
        self.name = name
        self.description = description
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
            # 8 kHz MP3 isn't playable everywhere; 22.05 kHz is universally supported.
            "-ar", "22050", "-c:a", "libmp3lame", "-b:a", self.bitrate,
            "-content_type", "audio/mpeg",
            "-ice_name", self.name, "-ice_description", self.description,
            "-f", "mp3", self.icecast_url,
        ]
        self._proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE)
        log.info("ffmpeg started for %s", _redact(self.icecast_url))

    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def write(self, pcm: bytes) -> None:
        if self.alive() and self._proc.stdin:
            self._proc.stdin.write(pcm)

    def close(self) -> None:
        if self.alive():
            self._proc.stdin.close()
            self._proc.terminate()


class TransmissionRecorder(PcmSink):
    """Writes each transmission to its own WAV, named by start time and talker.

    Fed directly with decoded audio (not through the clock), so recordings
    contain no inter-transmission silence and need no trimming before STT.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._wav: wave.Wave_write | None = None
        self.current_path: Path | None = None

    def begin(self, talker: str) -> Path:
        self.end()
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = "".join(c for c in talker if c.isalnum() or c in "-/").replace("/", "-") or "unknown"
        self.current_path = self.directory / f"{stamp}_{safe}.wav"
        self._wav = wave.open(str(self.current_path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(SAMPLE_RATE)
        return self.current_path

    def write(self, pcm: bytes) -> None:
        if self._wav:
            self._wav.writeframes(pcm)

    def end(self) -> Path | None:
        path = self.current_path
        if self._wav:
            self._wav.close()
        self._wav = None
        self.current_path = None
        return path

    close = end


def _redact(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url
