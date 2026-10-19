"""Listenable streams: a network source, its decoder, and its outputs.

VoiceStream holds everything that doesn't depend on the network: who is
talking, recordings, the real-time clock and the end-of-transmission
watchdog. YsfStream and DmrStream turn their protocol's packets into
begin / play / end calls on it.
"""

import asyncio
import collections
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .audio import JitterClock, PcmSink, TransmissionRecorder
from .dmr import client as dmr_client
from .dmr import frame as dmr_frame
from .dmr.client import DmrPacket, HomebrewClient
from .dmr.radioid import CallsignCache
from .vocoder import Vocoder
from .ysf import frame as ysf
from .ysf.client import YsfClient, YsfPacket

log = logging.getLogger(__name__)

# A transmission with no new frames for this long is over, even if its
# terminator was lost.
TRANSMISSION_TIMEOUT = 1.5


@dataclass
class Heard:
    talker: str
    gateway: str
    started: float
    ended: float | None = None
    mode: str = ""
    recording: str | None = None
    transcript: str | None = None
    # None when not transcribed at all; else queued, transcribing, done,
    # no_speech (nothing recognizable), too_short or failed.
    transcript_status: str | None = None
    id: int | None = None  # its row in the database (db.py)

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


async def _first(*waitables) -> None:
    """Wait until any event is set or task finishes."""
    tasks = [w if isinstance(w, asyncio.Task) else asyncio.create_task(w.wait()) for w in waitables]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for w, t in zip(waitables, tasks):
        if t is not w:
            t.cancel()


class VoiceStream:
    def __init__(self, name: str, sinks: list[PcmSink] | None = None, record_dir: Path | None = None) -> None:
        self.name = name
        self.status = StreamStatus()
        self.vocoder = Vocoder()
        self.clock = JitterClock(sinks or [])
        self.recorder = TransmissionRecorder(record_dir) if record_dir else None
        self._last_frame_at = 0.0
        self.on_transmission_start = None  # optional callback(Heard)
        self.on_transmission_end = None  # optional callback(Heard)
        # Whether to be linked. The audio clock (and so the Icecast stream)
        # runs either way; only the reflector link follows this.
        self.wanted = True
        self._wanted_changed = asyncio.Event()

    def set_wanted(self, wanted: bool) -> None:
        if wanted != self.wanted:
            self.wanted = wanted
            self._wanted_changed.set()

    def _is_linked(self) -> bool:
        raise NotImplementedError

    async def _run_source(self, stop: asyncio.Event) -> None:
        raise NotImplementedError

    # ========== TRANSMISSION TRACKING ==========

    def _begin(self, talker: str, gateway: str = "") -> Heard:
        self._end()
        self.vocoder.reset()
        heard = Heard(talker=talker or "unknown", gateway=gateway, started=time.time())
        if self.recorder:
            heard.recording = str(self.recorder.begin(heard.talker))
        self.status.current = heard
        log.info("[%s] %s%s", self.name, heard.talker, f" via {gateway}" if gateway else "")
        if self.on_transmission_start:
            self.on_transmission_start(heard)
        return heard

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

    def _play(self, pcms: list[bytes]) -> None:
        for pcm in pcms:
            self.clock.push(pcm)
            if self.recorder:
                self.recorder.write(pcm)

    def _touch(self) -> None:
        self._last_frame_at = time.monotonic()

    def finish(self) -> None:
        """Close the transmission in progress (end of a replay)."""
        self._end()

    # ========== RUNNING ==========

    async def _watchdog(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.25)
            self.status.linked = self._is_linked()
            if self.status.current and time.monotonic() - self._last_frame_at > TRANSMISSION_TIMEOUT:
                self._end()

    async def _run_source_when_wanted(self, stop: asyncio.Event) -> None:
        """Run the link while wanted; unlink (stop it) when not."""
        while not stop.is_set():
            if not self.wanted:
                await _first(stop, self._wanted_changed)
                self._wanted_changed.clear()
                continue
            link_stop = asyncio.Event()
            link = asyncio.create_task(self._run_source(link_stop))
            await _first(stop, self._wanted_changed, link)
            self._wanted_changed.clear()
            link_stop.set()
            await link

    async def run(self, stop: asyncio.Event) -> None:
        try:
            await asyncio.gather(self._run_source_when_wanted(stop), self.clock.run(stop), self._watchdog(stop))
        finally:
            self._end()
            for sink in self.clock.sinks:
                sink.close()


# ========== YSF ==========

class YsfStream(VoiceStream):
    def __init__(self, name: str, host: str, port: int, callsign: str,
                 sinks: list[PcmSink] | None = None, record_dir: Path | None = None) -> None:
        super().__init__(name, sinks, record_dir)
        self.client = YsfClient(host, port, callsign, self.feed)
        self._dt = ysf.DT_VD_MODE2

    def _is_linked(self) -> bool:
        return self.client.linked

    async def _run_source(self, stop: asyncio.Event) -> None:
        await self.client.run(stop)

    def feed(self, pkt: YsfPacket) -> None:
        """Decode one voice packet (live from the client, or replayed from a capture)."""
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
            cur = self._begin(pkt.src, pkt.gateway)

        if fi == ysf.FI_COMMUNICATIONS:
            if dt == ysf.DT_VD_MODE2:
                cur.mode = "DN"
                self._play([self.vocoder.decode_ambe2450(v) for v in ysf.decode_vd2_voice(pkt.frame)])
            elif dt == ysf.DT_VOICE_FR:
                cur.mode = "VW"
                self._play([self.vocoder.decode_imbe7200x4400(v) for v in ysf.decode_vw_voice(pkt.frame, fich)])
            else:
                # V/D mode 1 and data frames: not decoded yet, counted so the
                # dashboard shows whether they actually occur.
                self.status.frames_unsupported += 1
            self.status.frames_ok += 1

        self._touch()
        if fi == ysf.FI_TERMINATOR or pkt.end_of_stream:
            self._end()


# ========== DMR ==========

class DmrStream(VoiceStream):
    """One talkgroup on a DmrLink. slot 0 accepts the talkgroup on either
    timeslot (a hotspot link normally gets everything on TS2)."""

    def __init__(self, name: str, talkgroup: int, slot: int = 0,
                 sinks: list[PcmSink] | None = None, record_dir: Path | None = None) -> None:
        super().__init__(name, sinks, record_dir)
        self.talkgroup = talkgroup
        self.slot = slot
        self.link: "DmrLink | None" = None
        self._stream_id: int | None = None
        self.callsigns: CallsignCache | None = None  # without one, talkers show as DMR IDs

    def _is_linked(self) -> bool:
        return bool(self.link and self.link.client and self.link.client.linked)

    async def _run_source(self, stop: asyncio.Event) -> None:
        await stop.wait()  # the shared DmrLink does the networking

    def feed(self, pkt: DmrPacket) -> None:
        if pkt.data_type == dmr_client.DATA_TYPE_TERMINATOR_WITH_LC:
            if pkt.stream_id == self._stream_id:
                self._end()
                self._stream_id = None
            return

        if pkt.stream_id != self._stream_id or self.status.current is None:
            self._stream_id = pkt.stream_id
            self._begin(self._talker(pkt), f"TG{pkt.dst}").mode = "DMR"

        if pkt.voice:
            self._play([self.vocoder.decode_ambe3600x2450(f) for f in dmr_frame.decode_voice_burst(pkt.burst)])
            self.status.frames_ok += 1
        elif pkt.data_type != dmr_client.DATA_TYPE_VOICE_LC_HEADER:
            self.status.frames_unsupported += 1
        self._touch()


    def _talker(self, pkt: DmrPacket) -> str:
        if not self.callsigns:
            return str(pkt.src)
        return self.callsigns.lookup(pkt.src, lambda cs, sid=pkt.stream_id: self._resolved(sid, cs))

    def _resolved(self, stream_id: int, callsign: str) -> None:
        """A lookup finished while (maybe) still in the same transmission."""
        cur = self.status.current
        if cur and self._stream_id == stream_id:
            cur.talker = callsign
            if self.on_transmission_start:
                self.on_transmission_start(cur)  # refresh the stream title


def dmr_plus_options(streams: list[DmrStream]) -> str:
    """DMR+ IPSC2 static talkgroups (TSn_1..TSn_5), no startup reflector
    (4000) and no user relinking. Syntax from Pi-Star's DMR+ option guides.

    A talkgroup goes on TS1 when its net's timeslot is 1, otherwise TS2.
    Each timeslot carries one call at a time, so nets that may talk at the
    same moment belong on different timeslots; using TS1 at all makes the
    login a duplex hotspot (see client.station_config)."""
    out = "StartRef=4000;RelinkTime=60;UserLink=0;"
    for ts in (1, 2):
        tgs = sorted({s.talkgroup for s in streams if (s.slot == 1) == (ts == 1)})
        if len(tgs) > 5:
            raise ValueError(f"DMR+ allows at most 5 static talkgroups on TS{ts} of one link")
        out += "".join(f"TS{ts}_{i}={tg};" for i, tg in enumerate(tgs, 1))
    return out


class DmrLink:
    """One Homebrew login, shared by every stream on the same master so the
    master sees a single receive-only hotspot however many talkgroups we
    stream. With no host it only dispatches (offline replay)."""

    def __init__(self, host: str, port: int, radio_id: int, password: str, callsign: str,
                 streams: list[DmrStream], options: str | None = None) -> None:
        self.streams = streams
        for s in streams:
            s.link = self
        self.client = HomebrewClient(host, port, radio_id, password, callsign,
                                     options if options is not None else dmr_plus_options(streams),
                                     self.dispatch) if host else None
        self.unrouted = 0

    def dispatch(self, pkt: DmrPacket) -> None:
        for s in self.streams:
            if pkt.group and pkt.dst == s.talkgroup and s.slot in (0, pkt.slot):
                s.feed(pkt)
                return
        self.unrouted += 1

    async def run(self, stop: asyncio.Event) -> None:
        await self.client.run(stop)
