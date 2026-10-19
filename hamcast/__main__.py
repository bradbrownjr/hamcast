"""hamcast command line.

  python -m hamcast probe-ysf HOST PORT CALLSIGN [--seconds N] [--out DIR]
      Link to a YSF reflector receive-only, write each transmission to a WAV
      in DIR, and print what was heard. --capture FILE also keeps the raw
      packets so the same audio can be re-decoded with another vocoder.
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

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "probe-ysf":
        asyncio.run(_probe(args))


if __name__ == "__main__":
    main()
