"""Receive-only DMR Homebrew (MMDVM) client, as used by DMR+ IPSC2, XLX,
FreeDMR, HBlink and TGIF masters.

Protocol (from g4klx/DMRGateway DMRNetwork.cpp and DMRGateway.cpp):
  login     -> "RPTL" + id                       <- "RPTACK" + 4-byte salt
  auth      -> "RPTK" + id + sha256(salt + password)       <- "RPTACK"
  config    -> "RPTC" + id + 294-byte station description   <- "RPTACK"
  options   -> "RPTO" + id + "KEY=value;..."   (if any)     <- "RPTACK"
  keepalive -> "RPTPING" + id every 10 s                   <- "MSTPONG"
  close     -> "RPTCL" + id                    master may send "MSTCL"
  rejection <- "MSTNAK" at any step
  voice     <- "DMRD" (55 bytes):
                [4] seq  [5:8] src id  [8:11] dst id  [11:15] repeater id
                [15] bit 7 slot 2, bit 6 private call, bit 5 data sync,
                     bit 4 voice sync, bits 0-3 data type or voice seq
                [16:20] stream id  [20:53] 33-byte burst  [53] BER  [54] RSSI

hamcast never sends DMRD, so it can never key up the master. Unanswered
steps are retried every 10 s, and the link is restarted after 60 s with no
reply at all, as DMRGateway does.
"""

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

RETRY_INTERVAL = 10.0
LINK_TIMEOUT = 60.0

# DMRD byte 15 frame types (bits 4-5) and the data types we care about.
DATA_TYPE_VOICE_LC_HEADER = 1
DATA_TYPE_TERMINATOR_WITH_LC = 2


@dataclass
class DmrPacket:
    seq: int
    src: int
    dst: int
    slot: int
    group: bool
    voice: bool  # carries three AMBE+2 frames
    data_type: int | None  # for data-sync bursts (header, terminator)
    stream_id: int
    burst: bytes  # 33 bytes


def parse_voice(data: bytes) -> DmrPacket | None:
    """Parse one DMRD datagram, or None if it isn't one."""
    if len(data) < 55 or data[:4] != b"DMRD":
        return None
    flags = data[15]
    data_sync = bool(flags & 0x20)
    return DmrPacket(
        seq=data[4],
        src=int.from_bytes(data[5:8], "big"),
        dst=int.from_bytes(data[8:11], "big"),
        slot=2 if flags & 0x80 else 1,
        group=not flags & 0x40,
        voice=not data_sync,
        data_type=flags & 0x0F if data_sync else None,
        stream_id=int.from_bytes(data[16:20], "big"),
        burst=data[20:53],
    )


def station_config(callsign: str, software: str, url: str) -> bytes:
    """The 294-byte RPTC body, laid out as DMRGateway.cpp builds it:
    callsign 8, rx 9, tx 9, power 2, colour code 2, latitude 8,
    longitude 9, height 3, location 20, description 19, slots 1, url 124,
    software id 40, package id 40. Frequencies, power and position are
    zero: this is not a radio. Slots '4' means a simplex hotspot."""
    body = (
        f"{callsign[:8]:<8}"
        f"{0:09d}{0:09d}{0:02d}{1:02d}"
        f"{0.0:08f}{0.0:09f}{0:03d}"
        f"{'Internet':<20.20}{'Receive-only stream':<19.19}4"
        f"{url:<124.124}{software:<40.40}{'hamcast':<40.40}"
    )
    return body.encode("ascii")


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, client: "HomebrewClient") -> None:
        self.client = client

    def datagram_received(self, data: bytes, addr) -> None:
        self.client._on_datagram(data)

    def error_received(self, exc: Exception) -> None:
        log.warning("DMR socket error: %s", exc)


class HomebrewClient:
    def __init__(self, host: str, port: int, radio_id: int, password: str, callsign: str,
                 options: str, on_packet: Callable[[DmrPacket], None],
                 software: str = "hamcast", url: str = "https://github.com/bradbrownjr/hamcast") -> None:
        self.host = host
        self.port = port
        self.radio_id = radio_id
        self.password = password
        self.options = options
        self.on_packet = on_packet
        self.on_raw: Callable[[bytes], None] | None = None  # every DMRD datagram, for capture/replay
        self._config = station_config(callsign, software, url)
        self._id = radio_id.to_bytes(4, "big")
        self.state = "idle"
        self.linked = False
        self.last_rx = 0.0
        self._transport: asyncio.DatagramTransport | None = None

    # ========== HANDSHAKE ==========

    def _send(self, payload: bytes) -> None:
        if self._transport:
            self._transport.sendto(payload)

    def _send_step(self) -> None:
        """(Re)send whatever the current handshake state is waiting on."""
        if self.state == "login":
            self._send(b"RPTL" + self._id)
        elif self.state == "auth":
            digest = hashlib.sha256(self._salt + self.password.encode("ascii")).digest()
            self._send(b"RPTK" + self._id + digest)
        elif self.state == "config":
            self._send(b"RPTC" + self._id + self._config)
        elif self.state == "options":
            self._send(b"RPTO" + self._id + self.options.encode("ascii"))
        elif self.state == "running":
            self._send(b"RPTPING" + self._id)

    def _on_datagram(self, data: bytes) -> None:
        self.last_rx = time.monotonic()
        if data[:4] == b"DMRD":
            if self.state == "running" and (pkt := parse_voice(data)) is not None:
                if self.on_raw:
                    self.on_raw(data)
                self.on_packet(pkt)
        elif data[:6] == b"RPTACK":
            if self.state == "login":
                self._salt = data[6:10]
                self.state = "auth"
            elif self.state == "auth":
                self.state = "config"
            elif self.state == "config":
                self.state = "options" if self.options else "running"
            elif self.state == "options":
                self.state = "running"
            else:
                return
            if self.state == "running":
                log.info("logged in to %s:%d as %d", self.host, self.port, self.radio_id)
                self.linked = True
            else:
                self._send_step()
        elif data[:6] == b"MSTNAK":
            log.warning("%s:%d rejected us during %s", self.host, self.port, self.state)
            self._restart = True
        elif data[:5] == b"MSTCL":
            log.warning("%s:%d is closing the connection", self.host, self.port)
            self._restart = True
        # MSTPONG needs nothing beyond the last_rx update above.

    # ========== MAIN LOOP ==========

    async def run(self, stop: asyncio.Event) -> None:
        """Stay logged in until stop is set, starting over whenever the master
        rejects us, closes, or goes quiet."""
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            try:
                self._transport, _ = await loop.create_datagram_endpoint(
                    lambda: _Protocol(self), remote_addr=(self.host, self.port))
            except OSError as exc:
                log.warning("cannot open socket to %s:%d: %s", self.host, self.port, exc)
                await _sleep_or_stop(stop, RETRY_INTERVAL)
                continue

            self.state = "login"
            self.linked = False
            self._restart = False
            self.last_rx = time.monotonic()
            try:
                while not stop.is_set() and not self._restart:
                    self._send_step()
                    await _sleep_or_stop(stop, RETRY_INTERVAL)
                    if time.monotonic() - self.last_rx > LINK_TIMEOUT:
                        log.warning("no reply from %s:%d, reconnecting", self.host, self.port)
                        break
            finally:
                if self.state == "running":
                    self._send(b"RPTCL" + self._id)
                self._transport.close()
                self._transport = None
                self.state = "idle"
                self.linked = False
            if self._restart and not stop.is_set():
                # Don't hammer a master that just refused us.
                await _sleep_or_stop(stop, RETRY_INTERVAL)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
