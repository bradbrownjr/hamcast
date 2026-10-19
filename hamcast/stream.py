"""One listenable stream: a network source, its decoder, and its outputs."""

import asyncio
import collections
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .audio import JitterClock, PcmSink, TransmissionRecorder
from .vocoder import Vocoder
from .ysf import frame as ysf
from .ysf.client import YsfClient, YsfPacket

log = logging.getLogger(__name__)

# A transmission with no new frames for this long is over, even if its
# terminator frame was lost.
TRANSMISSION_TIMEOUT = 1.5


@dataclass
class Heard:
    talker: str
    gateway: str
    started: float
    ended: float | None = None
    mode: str = ""
    recording: str | None = None

    @property
    def seconds(self) -> float:
        return (self.ended or time.time()) - self.started


@dataclass
class StreamStatus:
    linked: bool = False
    current: Heard | None = None
    heard: collections.deque = field(default_factory=lambda: collections.deque(maxlen=50))
    frames_ok: int = 0
    frames_bad_fich: int = 0
    frames_unsupported: int = 0


class YsfStream:
    def __init__(self, name: str, host: str, port: int, callsign: str,
                 sinks: list[PcmSink] | None = None, record_dir: Path | None = None) -> None:
        self.name = name
        self.status = StreamStatus()
        self.vocoder = Vocoder()
        self.clock = JitterClock(sinks or [])
        self.recorder = TransmissionRecorder(record_dir) if record_dir else None
        self.client = YsfClient(host, port, callsign, self._on_packet)
        self._last_frame_at = 0.0
        self._dt = ysf.DT_VD_MODE2
        self.on_transmission_start = None  # optional callback(Heard)
        self.on_transmission_end = None  # optional callback(Heard)

    # ========== TRANSMISSION TRACKING ==========

    def _begin(self, pkt: YsfPacket) -> None:
        self._end()
        self.vocoder.reset()
        heard = Heard(talker=pkt.src or "unknown", gateway=pkt.gateway, started=time.time())
        if self.recorder:
            heard.recording = str(self.recorder.begin(heard.talker))
        self.status.current = heard
        log.info("[%s] %s via %s", self.name, heard.talker, heard.gateway)
        if self.on_transmission_start:
            self.on_transmission_start(heard)

    def _end(self) -> None:
        heard = self.status.current
        if not heard:
            return
        heard.ended = time.time()
        if self.recorder:
            saved = self.recorder.end()
            heard.recording = str(saved) if saved else None
        self.status.heard.appendleft(heard)
        self.status.current = None
        log.info("[%s] %s done, %.1f s", self.name, heard.talker, heard.seconds)
        if self.on_transmission_end:
            self.on_transmission_end(heard)

    # ========== PACKET HANDLING ==========

    def feed(self, pkt: YsfPacket) -> None:
        """Decode one voice packet (live from the client, or replayed from a capture)."""
        self._on_packet(pkt)

    def _on_packet(self, pkt: YsfPacket) -> None:
        fich = ysf.decode_fich(pkt.frame)
        if fich is None:
            # A frame with a damaged FICH still carries voice; assume it is
            # the same type as the previous good one.
            self.status.frames_bad_fich += 1
            dt, fi = self._dt, ysf.FI_COMMUNICATIONS
        else:
            dt, fi = fich.dt, fich.fi
            self._dt = dt

        cur = self.status.current
        if fi == ysf.FI_HEADER or cur is None or (pkt.src and pkt.src != cur.talker):
            self._begin(pkt)
            cur = self.status.current

        if fi == ysf.FI_COMMUNICATIONS:
            if dt == ysf.DT_VD_MODE2:
                cur.mode = "DN"
                voices = [self.vocoder.decode_ambe2450(v) for v in ysf.decode_vd2_voice(pkt.frame)]
            elif dt == ysf.DT_VOICE_FR:
                cur.mode = "VW"
                voices = [self.vocoder.decode_imbe7200x4400(v) for v in ysf.decode_vw_voice(pkt.frame, fich)]
            else:
                # V/D mode 1 and data frames: not decoded yet, counted so the
                # dashboard shows whether they actually occur.
                self.status.frames_unsupported += 1
                voices = []
            for pcm in voices:
                self.clock.push(pcm)
                if self.recorder:
                    self.recorder.write(pcm)
            self.status.frames_ok += 1

        self._last_frame_at = time.monotonic()
        if fi == ysf.FI_TERMINATOR or pkt.end_of_stream:
            self._end()

    async def _watchdog(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.25)
            self.status.linked = self.client.linked
            if self.status.current and time.monotonic() - self._last_frame_at > TRANSMISSION_TIMEOUT:
                self._end()

    def finish(self) -> None:
        """Close the transmission in progress (end of a replay)."""
        self._end()

    async def run(self, stop: asyncio.Event) -> None:
        try:
            await asyncio.gather(self.client.run(stop), self.clock.run(stop), self._watchdog(stop))
        finally:
            self._end()
            for sink in self.clock.sinks:
                sink.close()
