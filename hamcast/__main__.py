"""hamcast command line.

  python -m hamcast serve --config config.yaml
      Run every configured stream, push to Icecast, serve the dashboard.

  python -m hamcast probe-ysf HOST PORT CALLSIGN [--seconds N] [--out DIR]
      Link to a YSF reflector receive-only, write each transmission to a WAV
      in DIR, and print what was heard. --capture FILE also keeps the raw
      packets so the same audio can be re-decoded with another vocoder.

  python -m hamcast replay-ysf CAPTURE [--out DIR]
      Decode a --capture file offline into per-transmission WAVs.

  python -m hamcast probe-dmr HOST PORT RADIO_ID PASSWORD --tg TG [--tg TG ...]
      Log in to a DMR Homebrew master (DMR+ IPSC2, XLX, ...) receive-only
      with those static talkgroups, and record each one like probe-ysf.

  python -m hamcast replay-dmr CAPTURE --tg TG [--tg TG ...] [--out DIR]
      Decode a probe-dmr --capture file offline.
"""

import argparse
import asyncio
import logging
from pathlib import Path

from .stream import DmrLink, DmrStream, YsfStream


async def _probe(args: argparse.Namespace) -> None:
    stream = YsfStream("probe", args.host, args.port, args.callsign, record_dir=Path(args.out))
    if args.capture:
        stream.client.on_raw = _capture_hook(args.capture)
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(args.seconds, stop.set)
    await stream.run(stop)
    _print_summary([stream])


def _capture_hook(path: str):
    """Length-prefixed raw datagrams, replayable through the decoder offline."""
    cap = open(path, "ab")
    return lambda d: (cap.write(len(d).to_bytes(2, "big") + d), cap.flush())


def _read_capture(path: str):
    with open(path, "rb") as cap:
        while header := cap.read(2):
            yield cap.read(int.from_bytes(header, "big"))


def _print_summary(streams) -> None:
    for st in streams:
        s = st.status
        print(f"[{st.name}] frames ok={s.frames_ok} bad_fich={s.frames_bad_fich} unsupported={s.frames_unsupported}")
        for h in reversed(s.heard):
            print(f"{h.talker:10} {h.gateway:10} {h.mode:3} {h.seconds:5.1f}s {h.recording}")


def _dmr_streams(args: argparse.Namespace) -> list[DmrStream]:
    return [DmrStream(f"TG{tg}", tg, record_dir=Path(args.out) / f"TG{tg}") for tg in args.tg]


async def _probe_dmr(args: argparse.Namespace) -> None:
    streams = _dmr_streams(args)
    link = DmrLink(args.host, args.port, args.radio_id, args.password, args.callsign, streams,
                   options=args.options)
    log = logging.getLogger("hamcast")
    log.info("options: %s", link.client.options)
    from .dmr.radioid import CallsignCache
    cache = CallsignCache()
    for st in streams:
        st.callsigns = cache
    if args.capture:
        link.client.on_raw = _capture_hook(args.capture)
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(args.seconds, stop.set)
    await asyncio.gather(link.run(stop), *(s.run(stop) for s in streams))
    _print_summary(streams)
    print(f"packets for other talkgroups: {link.unrouted}")


def _replay_dmr(args: argparse.Namespace) -> None:
    from .dmr.client import parse_voice

    streams = _dmr_streams(args)
    link = DmrLink("", 0, 0, "", "", streams)
    for data in _read_capture(args.capture):
        if pkt := parse_voice(data):
            link.dispatch(pkt)
    for s in streams:
        s.finish()
    _print_summary(streams)


def _replay(args: argparse.Namespace) -> None:
    from .ysf.client import parse_voice

    stream = YsfStream("replay", "", 0, "", record_dir=Path(args.out))
    for data in _read_capture(args.capture):
        if pkt := parse_voice(data):
            stream.feed(pkt)
    stream.finish()
    _print_summary([stream])


async def _serve(args: argparse.Namespace) -> None:
    import signal

    from .config import load
    from .service import Service

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await Service(load(args.config)).run(stop)


def main() -> None:
    parser = argparse.ArgumentParser(prog="hamcast")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe-ysf", help="record a YSF reflector to WAV files")
    p.add_argument("host")
    p.add_argument("port", type=int)
    p.add_argument("callsign")
    p.add_argument("--seconds", type=float, default=120)
    p.add_argument("--out", default="recordings")
    p.add_argument("--capture", help="append raw YSFD packets to this file")

    p = sub.add_parser("replay-ysf", help="decode a probe-ysf --capture file to WAV files")
    p.add_argument("capture")
    p.add_argument("--out", default="recordings")

    p = sub.add_parser("probe-dmr", help="record DMR talkgroups from a Homebrew master to WAV files")
    p.add_argument("host")
    p.add_argument("port", type=int)
    p.add_argument("radio_id", type=int, help="your DMR ID, usually with a 2-digit hotspot suffix")
    p.add_argument("password")
    p.add_argument("--tg", type=int, action="append", required=True)
    p.add_argument("--callsign", default="N0CALL")
    p.add_argument("--options", help="RPTO options string (default: DMR+ static talkgroups)")
    p.add_argument("--seconds", type=float, default=120)
    p.add_argument("--out", default="recordings")
    p.add_argument("--capture", help="append raw DMRD packets to this file")

    p = sub.add_parser("replay-dmr", help="decode a probe-dmr --capture file to WAV files")
    p.add_argument("capture")
    p.add_argument("--tg", type=int, action="append", required=True)
    p.add_argument("--out", default="recordings")

    p = sub.add_parser("serve", help="run all configured streams and the dashboard")
    p.add_argument("--config", default="/config/config.yaml")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "probe-ysf":
        asyncio.run(_probe(args))
    elif args.command == "probe-dmr":
        asyncio.run(_probe_dmr(args))
    elif args.command == "replay-dmr":
        _replay_dmr(args)
    elif args.command == "replay-ysf":
        _replay(args)
    elif args.command == "serve":
        asyncio.run(_serve(args))


if __name__ == "__main__":
    main()
