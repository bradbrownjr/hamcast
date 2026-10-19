"""Runs every configured stream plus the dashboard."""

import asyncio
import logging
import time

from . import icecast
from .audio import FfmpegSink
from .config import Config, StreamConfig
from .dmr.radioid import CallsignCache
from .stream import DmrLink, DmrStream, VoiceStream, YsfStream

log = logging.getLogger(__name__)

IDLE_TITLE = "Listening - no one transmitting"


class ManagedStream:
    """A stream plus its Icecast push, kept alive across ffmpeg crashes."""

    def __init__(self, cfg: Config, scfg: StreamConfig) -> None:
        self.cfg = cfg
        self.scfg = scfg
        self.push_url = cfg.icecast.push_url.rstrip("/") + scfg.mount
        self.sink = FfmpegSink(self.push_url, cfg.icecast.bitrate, scfg.name, scfg.description)
        record_dir = cfg.data_dir / "recordings" / scfg.id if scfg.record else None
        self.stream: VoiceStream
        if scfg.type == "dmr":
            self.stream = DmrStream(scfg.id, scfg.talkgroup, scfg.slot, sinks=[self.sink], record_dir=record_dir)
        else:
            self.stream = YsfStream(scfg.id, scfg.host, scfg.port, cfg.callsign,
                                    sinks=[self.sink], record_dir=record_dir)
        self.stream.on_transmission_start = self._title_for
        self.stream.on_transmission_end = lambda heard: self._set_title(IDLE_TITLE)
        self.listeners = 0
        self.started = time.time()

    def _title_for(self, heard) -> None:
        via = f" via {heard.gateway}" if heard.gateway else ""
        self._set_title(f"{heard.talker}{via}")

    def _set_title(self, title: str) -> None:
        asyncio.get_running_loop().run_in_executor(None, icecast.set_title, self.cfg.icecast.push_url, self.scfg.mount, title)

    async def _keep_ffmpeg(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            if not self.sink.alive():
                await self.sink.start()
                await asyncio.sleep(2)
                self._set_title(IDLE_TITLE)
            await asyncio.sleep(5)

    async def run(self, stop: asyncio.Event) -> None:
        await asyncio.gather(self.stream.run(stop), self._keep_ffmpeg(stop))


def _dmr_links(cfg: Config, streams: list[ManagedStream]) -> list[DmrLink]:
    """One login per master: DMR streams on the same host, port and password
    share it, so the master sees one hotspot for all their talkgroups."""
    groups: dict[tuple, list[ManagedStream]] = {}
    for ms in streams:
        if ms.scfg.type == "dmr":
            groups.setdefault((ms.scfg.host, ms.scfg.port, ms.scfg.password), []).append(ms)
    callsigns = CallsignCache(cfg.data_dir / "radioid-cache.json")
    links = []
    for (host, port, password), members in groups.items():
        options = {ms.scfg.options for ms in members if ms.scfg.options is not None}
        if len(options) > 1:
            raise ValueError(f"DMR streams on {host}:{port} set different options")
        for ms in members:
            ms.stream.callsigns = callsigns
        links.append(DmrLink(host, port, cfg.dmr_id, password, cfg.callsign,
                             [ms.stream for ms in members], options.pop() if options else None))
    return links


class Service:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.streams = [ManagedStream(cfg, s) for s in cfg.streams]
        self.dmr_links = _dmr_links(cfg, self.streams)

    async def _poll_listeners(self, stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            counts = await loop.run_in_executor(None, icecast.listener_counts, self.cfg.icecast.push_url)
            for ms in self.streams:
                ms.listeners = counts.get(ms.scfg.mount, 0)
            await asyncio.sleep(15)

    async def run(self, stop: asyncio.Event) -> None:
        from .web import serve_dashboard
        await asyncio.gather(
            *(ms.run(stop) for ms in self.streams),
            *(link.run(stop) for link in self.dmr_links),
            self._poll_listeners(stop),
            serve_dashboard(self, stop),
        )
