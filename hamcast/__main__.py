"""hamcast command line.

  python -m hamcast serve --config config.yaml
      Run every configured stream, push to Icecast, serve the dashboard.

  python -m hamcast probe-ysf HOST PORT CALLSIGN [--seconds N] [--out DIR]
      Link to a YSF reflector receive-only, write each transmission to a WAV
      in DIR, and print what was heard. --capture FILE also keeps the raw
      packets so the same audio can be re-decoded with another vocoder.

  python -m hamcast replay-ysf CAPTURE [--out DIR]
      Decode a --capture file offline into per-transmission WAVs.
"""

import argparse
import asyncio
import logging
from pathlib import Path

from .stream import YsfStream


async def _probe(args: argparse.Namespace) -> None:
    stream = YsfStream("probe", args.host, args.port, args.callsign, record_dir=Path(args.out))
    if args.capture:
        # Length-prefixed raw YSFD datagrams, replayable through the decoder offline.
        cap = open(args.capture, "ab")
        stream.client.on_raw = lambda d: (cap.write(len(d).to_bytes(2, "big") + d), cap.flush())
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(args.seconds, stop.set)
    await stream.run(stop)
    s = stream.status
    print(f"frames ok={s.frames_ok} bad_fich={s.frames_bad_fich} unsupported={s.frames_unsupported}")
    for h in reversed(s.heard):
        print(f"{h.talker:10} {h.gateway:10} {h.mode:3} {h.seconds:5.1f}s {h.recording}")


def _replay(args: argparse.Namespace) -> None:
    from .ysf.client import parse_voice

    stream = YsfStream("replay", "", 0, "", record_dir=Path(args.out))
    with open(args.capture, "rb") as cap:
        while header := cap.read(2):
            pkt = parse_voice(cap.read(int.from_bytes(header, "big")))
            if pkt:
                stream.feed(pkt)
    stream.finish()
    s = stream.status
    print(f"frames ok={s.frames_ok} bad_fich={s.frames_bad_fich} unsupported={s.frames_unsupported}")


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

    p = sub.add_parser("serve", help="run all configured streams and the dashboard")
    p.add_argument("--config", default="/config/config.yaml")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "probe-ysf":
        asyncio.run(_probe(args))
    elif args.command == "replay-ysf":
        _replay(args)
    elif args.command == "serve":
        asyncio.run(_serve(args))


if __name__ == "__main__":
    main()
