"""Runs the nets, the bundled Icecast and transcription (when configured),
and the dashboard.

Nets can be added, changed, started and stopped while hamcast runs: the
dashboard edits the StreamStore and calls apply(), which compares what
should run with what is running and starts, stops or restarts only the
difference. DMR nets on the same master share one login (DmrLink); a
link is re-formed only when its set of talkgroups changes.
"""

import asyncio
import logging
import time
from dataclasses import asdict
from pathlib import Path

from . import audio_files, icecast, icecast_server, legacy, schedule
from .audio import FfmpegSink
from .config import Config, StreamConfig
from .db import HistoryDB
from .dmr.radioid import CallsignCache
from .store import StreamStore
from .stream import DmrLink, DmrStream, VoiceStream, YsfStream
from .transcribe import Transcriber

log = logging.getLogger(__name__)

IDLE_TITLE = "Listening - no one transmitting"
# How often listeners and schedules are checked for nets linked only when needed.
CONTROL_INTERVAL = 5


class ManagedStream:
    """A stream plus its Icecast push, kept alive across ffmpeg crashes."""

    def __init__(self, cfg: Config, scfg: StreamConfig, push_base: str,
                 transcriber: Transcriber | None, callsigns: CallsignCache, db: HistoryDB,
                 working: set[int]) -> None:
        self.cfg = cfg
        self.db = db
        # Rows whose audio is being transcribed or compressed, shared by every
        # net and kept across a net's restart (editing it), so a WAV already
        # in the queue isn't queued twice.
        self.working = working
        self.scfg = scfg
        self.push_base = push_base
        self.sink = FfmpegSink(push_base.rstrip("/") + scfg.mount, cfg.icecast.bitrate, scfg.name, scfg.description)
        self.record_dir = cfg.data_dir / "recordings" / scfg.id
        record_dir = self.record_dir if scfg.record else None
        self.stream: VoiceStream
        if scfg.type == "dmr":
            self.stream = DmrStream(scfg.id, scfg.talkgroup, scfg.slot, sinks=[self.sink], record_dir=record_dir)
            self.stream.callsigns = callsigns
        else:
            self.stream = YsfStream(scfg.id, scfg.host, scfg.port, cfg.callsign,
                                    sinks=[self.sink], record_dir=record_dir)
        self.stream.on_transmission_start = self._title_for
        self.stream.on_transmission_end = self._ended
        self.transcriber = transcriber if scfg.record and scfg.transcribe else None
        self.listeners = 0
        self.last_listener = 0.0  # when someone was last listening
        self.started = time.time()
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None
        self._start_from_history()

    # ========== HISTORY ==========

    def _start_from_history(self) -> None:
        """Start with the latest transmissions from the database, so a restart
        doesn't empty the conversation, and finish any audio a restart left
        as WAV (transcribe, or compress, or delete)."""
        flag = f"imported:{self.scfg.id}"
        if not self.db.flag(flag):
            for heard in legacy.recordings(self.record_dir):
                self.db.add(self.scfg.id, heard)
            self.db.set_flag(flag)
        recent, _ = self.db.page(self.scfg.id, self.record_dir, limit=self.stream.status.heard.maxlen)
        self.stream.status.heard.extend(recent)
        shown = {h.id: h for h in recent}
        for heard in self.db.unfinished(self.scfg.id, self.record_dir):
            # Use the entry the page shows, so its status updates live.
            self._process(shown.get(heard.id, heard))

    def _process(self, heard) -> None:
        """A recorded transmission's audio: delete it if too short to be
        speech, else transcribe (when on) and then compress it."""
        if heard.id in self.working:
            return
        wav = Path(heard.recording)
        if not wav.exists():
            heard.recording = None
            self.db.update(heard)
            return
        if audio_files.duration(wav) < self.cfg.transcription.min_seconds:
            wav.unlink(missing_ok=True)
            heard.recording = None
            heard.transcript_status = "too_short" if self.transcriber else None
            self.db.update(heard)
            return
        self.working.add(heard.id)
        if self.transcriber and heard.transcript_status not in ("done", "no_speech", "failed"):
            self.transcriber.submit(heard, self._transcribed)
            self.db.update(heard)
        else:
            asyncio.get_running_loop().create_task(self._compress(heard))

    def _transcribed(self, heard, segments) -> None:
        self.db.update(heard, segments)
        asyncio.get_running_loop().create_task(self._compress(heard))

    async def _compress(self, heard) -> None:
        try:
            mp3 = await audio_files.compress(Path(heard.recording), self.cfg.icecast.bitrate)
            if mp3:
                heard.recording = str(mp3)
                self.db.update(heard)
        finally:
            self.working.discard(heard.id)

    @property
    def link_key(self) -> tuple | None:
        s = self.scfg
        return (s.host, s.port, s.password) if s.type == "dmr" else None

    def idle_title(self) -> str:
        if self.stream.wanted:
            return IDLE_TITLE
        return "Standby - press play to link" if self.scfg.on_listen else "Standby - not linked"

    def _title_for(self, heard) -> None:
        via = f" via {heard.gateway}" if heard.gateway else ""
        self._set_title(f"{heard.talker}{via}")

    def _ended(self, heard) -> None:
        self._set_title(self.idle_title())
        self.db.add(self.scfg.id, heard)
        if heard.recording:
            self._process(heard)

    def _set_title(self, title: str) -> None:
        asyncio.get_running_loop().run_in_executor(None, icecast.set_title, self.push_base, self.scfg.mount, title)

    async def _keep_ffmpeg(self) -> None:
        while not self.stop.is_set():
            if not self.sink.alive():
                await self.sink.start()
                # Icecast only accepts metadata once the source is connected,
                # which takes a few seconds after ffmpeg starts.
                await asyncio.sleep(10)
                self._set_title(self.idle_title())
            await asyncio.sleep(5)

    async def run(self) -> None:
        keeper = asyncio.create_task(self._keep_ffmpeg())
        try:
            await self.stream.run(self.stop)
        finally:
            keeper.cancel()


class _RunningLink:
    def __init__(self, link: DmrLink, members: frozenset[str]) -> None:
        self.link = link
        self.members = members
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(link.run(self.stop))


class Service:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.store = StreamStore(cfg)
        self.bundled_icecast = None
        if cfg.icecast.bundled:
            icecast_server.ensure_passwords(cfg)
            self.bundled_icecast = icecast_server.BundledIcecast(cfg)
            self.push_base = icecast_server.push_url(cfg)
        else:
            self.push_base = cfg.icecast.push_url
        self.transcriber = Transcriber(cfg.transcription, cfg.data_dir) if cfg.transcription.enabled else None
        self.callsigns = CallsignCache(cfg.data_dir / "radioid-cache.json")
        self.db = HistoryDB(cfg.data_dir / "hamcast.db")
        self.calendar = schedule.EctloggerCalendar(cfg.ectlogger_url) if cfg.ectlogger_url else None
        self.working: set[int] = set()
        self.running: dict[str, ManagedStream] = {}
        self._links: dict[tuple, _RunningLink] = {}
        self._lock = asyncio.Lock()

    # ========== RECONCILE ==========

    async def apply(self) -> None:
        """Make the running nets match the store."""
        async with self._lock:
            wanted = {s.id: s for s in self.store.streams if s.enabled}
            for sid, ms in list(self.running.items()):
                if sid not in wanted or asdict(wanted[sid]) != asdict(ms.scfg):
                    await self._stop_stream(sid)
            for sid, scfg in wanted.items():
                if sid not in self.running:
                    ms = ManagedStream(self.cfg, scfg, self.push_base, self.transcriber, self.callsigns,
                                       self.db, self.working)
                    ms.stream.set_wanted(schedule.wanted(scfg, 0, 0.0, self.calendar))
                    ms.task = asyncio.create_task(ms.run())
                    self.running[sid] = ms
                    log.info("started %s", sid)
            await self._apply_links()

    async def _stop_stream(self, sid: str) -> None:
        ms = self.running.pop(sid)
        ms.stop.set()
        if ms.task:
            await ms.task
        log.info("stopped %s", sid)

    async def _apply_links(self) -> None:
        # A DMR net is in its master's login only while it wants to be linked.
        groups: dict[tuple, list[ManagedStream]] = {}
        for ms in self.running.values():
            if ms.link_key and ms.stream.wanted:
                groups.setdefault(ms.link_key, []).append(ms)
        for key, rl in list(self._links.items()):
            members = frozenset(ms.scfg.id for ms in groups.get(key, []))
            # Streams that were restarted are new objects, so compare the
            # stream objects too, not just their ids.
            same_objects = members == rl.members and all(
                ms.stream in rl.link.streams for ms in groups.get(key, []))
            if not same_objects:
                rl.stop.set()
                await rl.task
                del self._links[key]
        for key, members in groups.items():
            if key not in self._links:
                host, port, password = key
                # validate_streams guarantees members agree on options.
                options = next((ms.scfg.options for ms in members if ms.scfg.options is not None), None)
                link = DmrLink(host, port, self.cfg.dmr_id, password, self.cfg.callsign,
                               [ms.stream for ms in members], options)
                self._links[key] = _RunningLink(link, frozenset(ms.scfg.id for ms in members))

    def link_for(self, sid: str) -> DmrLink | None:
        for rl in self._links.values():
            if sid in rl.members:
                return rl.link
        return None

    # ========== RUNNING ==========

    async def _control(self, stop: asyncio.Event) -> None:
        """Count listeners, and link or unlink each net that is linked only
        when needed (someone listening, or its schedule)."""
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            counts = await loop.run_in_executor(None, icecast.listener_counts, self.push_base)
            now = time.time()
            dmr_changed = False
            for ms in list(self.running.values()):
                ms.listeners = counts.get(ms.scfg.mount, 0)
                if ms.listeners:
                    ms.last_listener = now
                want = schedule.wanted(ms.scfg, ms.listeners, ms.last_listener, self.calendar, now)
                if want != ms.stream.wanted:
                    log.info("%s %s", "linking" if want else "unlinking", ms.scfg.id)
                    ms.stream.set_wanted(want)
                    ms._set_title(ms.idle_title())
                    dmr_changed |= ms.link_key is not None
            if dmr_changed:
                async with self._lock:
                    await self._apply_links()
            try:
                await asyncio.wait_for(stop.wait(), CONTROL_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def _expire_audio(self, stop: asyncio.Event) -> None:
        """Hourly: delete audio older than audio_days; rows and text stay."""
        while self.cfg.audio_days > 0 and not stop.is_set():
            cutoff = time.time() - self.cfg.audio_days * 86400
            for row_id, stream_id, audio in self.db.audio_before(cutoff):
                (self.cfg.data_dir / "recordings" / stream_id / audio).unlink(missing_ok=True)
                self.db.drop_audio(row_id)
            try:
                await asyncio.wait_for(stop.wait(), 3600)
            except asyncio.TimeoutError:
                pass

    async def run(self, stop: asyncio.Event) -> None:
        from .web import serve_dashboard
        await self.apply()
        try:
            await asyncio.gather(
                *([self.bundled_icecast.run(stop)] if self.bundled_icecast else []),
                *([self.transcriber.run(stop)] if self.transcriber else []),
                self._control(stop),
                *([self.calendar.run(stop)] if self.calendar else []),
                self._expire_audio(stop),
                serve_dashboard(self, stop),
            )
        finally:
            async with self._lock:
                for sid in list(self.running):
                    await self._stop_stream(sid)
                await self._apply_links()
