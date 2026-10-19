"""Receive-only YSF reflector client.

Protocol (from DroidStar ysf.cpp and xlxd cysfprotocol.cpp):
  link       -> "YSFP" + callsign padded to 10      (reflector answers 14 bytes)
  keepalive  -> the same "YSFP" packet every 5 s
  unlink     -> "YSFU" + callsign padded to 10
  voice      <- "YSFD" (155 bytes): gateway[4:14] src[14:24] dst[24:34]
                [34] = frame counter << 1 | end-of-transmission bit
                (xlxd cysfprotocol.cpp::EncodeDvLastPacket), then one
                120-byte YSF air frame

hamcast never sends YSFD, so it can never key up the reflector.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

PING_INTERVAL = 5.0
# xlxd drops a YSF client after 30 s of silence; reconnect well before
# anyone notices if the reflector stops answering us.
LINK_TIMEOUT = 20.0


@dataclass
class YsfPacket:
    gateway: str
    src: str
    dst: str
    frame: bytes  # 120-byte air frame
    end_of_stream: bool


def _pad(callsign: str) -> bytes:
    return callsign.upper().encode("ascii")[:10].ljust(10, b" ")


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, client: "YsfClient") -> None:
        self.client = client

    def datagram_received(self, data: bytes, addr) -> None:
        self.client._on_datagram(data)

    def error_received(self, exc: Exception) -> None:
        log.warning("YSF socket error: %s", exc)


class YsfClient:
    def __init__(self, host: str, port: int, callsign: str, on_packet: Callable[[YsfPacket], None]) -> None:
        self.host = host
        self.port = port
        self.callsign = callsign
        self.on_packet = on_packet
        self.on_raw: Callable[[bytes], None] | None = None  # every YSFD datagram, for capture/replay
        self.linked = False
        self.last_rx = 0.0
        self._transport: asyncio.DatagramTransport | None = None

    def _send(self, payload: bytes) -> None:
        if self._transport:
            self._transport.sendto(payload)

    def _on_datagram(self, data: bytes) -> None:
        self.last_rx = time.monotonic()
        if len(data) == 14 and data[:4] == b"YSFP":
            if not self.linked:
                log.info("linked to %s:%d as %s", self.host, self.port, self.callsign)
            self.linked = True
        elif len(data) == 155 and data[:4] == b"YSFD":
            if self.on_raw:
                self.on_raw(data)
            self.on_packet(YsfPacket(
                gateway=data[4:14].decode("ascii", "replace").strip(),
                src=data[14:24].decode("ascii", "replace").strip(),
                dst=data[24:34].decode("ascii", "replace").strip(),
                end_of_stream=bool(data[34] & 0x01),
                frame=data[35:155],
            ))

    async def run(self, stop: asyncio.Event) -> None:
        """Stay linked until stop is set, relinking whenever the reflector goes quiet."""
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            try:
                self._transport, _ = await loop.create_datagram_endpoint(
                    lambda: _Protocol(self), remote_addr=(self.host, self.port))
            except OSError as exc:
                log.warning("cannot open socket to %s:%d: %s", self.host, self.port, exc)
                await _sleep_or_stop(stop, 10)
                continue

            self.linked = False
            self.last_rx = time.monotonic()
            link = b"YSFP" + _pad(self.callsign)
            try:
                while not stop.is_set():
                    self._send(link)
                    await _sleep_or_stop(stop, PING_INTERVAL)
                    if time.monotonic() - self.last_rx > LINK_TIMEOUT:
                        log.warning("no reply from %s:%d, relinking", self.host, self.port)
                        break
            finally:
                self._send(b"YSFU" + _pad(self.callsign))
                self._transport.close()
                self._transport = None
                self.linked = False


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
