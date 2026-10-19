# hamcast

Stream amateur digital voice nets to anyone with a web browser.

hamcast links to a digital voice reflector **receive-only**, decodes the
audio in software, and publishes it as an ordinary Icecast/Shoutcast MP3
stream. People without a radio, a hotspot, or an app can listen to a net from
a link, and net-logging tools such as [ECTLogger](https://github.com/bradbrownjr/ectlogger)
can play it in the page.

> **Status: early development.** YSF receive and software decode are
> verified on a live net (both DN and VW voice, intelligible enough for
> Whisper to transcribe callsigns and names). DMR Homebrew login and decode
> are verified against a DMR+ IPSC2 master, but not yet on a live net. The
> Icecast push and dashboard work. Connection modes and transcription are
> next.

## How it works

```
reflector --UDP--> protocol client --> voice frames --> software vocoder --> 8 kHz PCM
                                                                             |
                                    Icecast <-- MP3 encoder <-- real-time clock (fills silence)
                                                                             |
                                                       per-transmission WAVs (talker in the name)
```

- **One link per stream, never transmits.** hamcast looks like a single
  receive-only hotspot to the reflector. Icecast does the fan-out, so the
  reflector sees the same one connection whether 1 or 500 people listen.
- **Talker identification for free.** YSF and DMR frames carry the source
  callsign or ID, so every transmission is labelled with who sent it. DMR
  IDs are turned into callsigns with RadioID.net, looked up once per ID in
  the background and cached.
- **One DMR login per master.** Every talkgroup you stream from the same
  master shares a single receive-only login.

## Supported sources

| Source | Status | Identity needed |
|---|---|---|
| YSF reflector (YSFReflector, XLX YSF port) | Receive + decode working | Your callsign (no password) |
| DMR Homebrew/MMDVM (DMR+ IPSC2; XLX, FreeDMR, TGIF untested) | Login + decode working | Your DMR ID + hotspot suffix; the master's password |
| External Icecast source (e.g. BUTT feeding an EchoLink node) | Planned | n/a |

hamcast identifies itself with the callsign/ID of whoever runs it. Never
configure someone else's callsign or a made-up one: reflector operators watch
their dashboards.

## Vocoder and patents

Decoding uses [mbelib-neo](https://github.com/arancormonk/mbelib-neo)
(GPL-2.0-or-later), a maintained fork of mbelib that reimplements synthesis,
frame repeat and muting from the TIA-102.BABA specifications. It is built
from a pinned release by `native/build.sh` and wrapped in a small C shim.

It was chosen by decoding the same 45-minute live YSF capture with stock
mbelib and with mbelib-neo: stock mbelib produced 26 full-scale pops and 534
clipped samples, mbelib-neo 2 and 0, and Whisper transcribed the
mbelib-neo audio more accurately on every matched transmission.

**AMBE+2 is covered by DVSI patents** (US8359197 is cited as active until
2028-05-20; see mbelib-neo's
[patent record](https://github.com/arancormonk/mbelib-neo/blob/main/legal/patents.md)).
Software AMBE decoding is common practice for amateur and research use;
assess the patent position yourself before using hamcast commercially.

## Stream audio

The stream is high-passed at 150 Hz and level-normalized per talker
(ffmpeg `dynaudnorm`), so a quiet station and a loud one come out at about
the same volume and the silence between transmissions stays silent. This
adds about 2 seconds of delay. Recordings are kept unprocessed.

## Running

```sh
cp config.example.yaml config.yaml   # set your callsign and streams
cp .env.example .env                 # set Icecast passwords (and the same source password in config.yaml)
docker compose up -d --build
```

Dashboard on port 8080 (link state, who is talking, last heard, recordings,
and a player per stream). Icecast on port 8000.

## Development

```sh
native/build.sh                         # builds native/libhcmbe.so (needs git, curl, gcc)
python3 -m hamcast probe-ysf HOST PORT YOURCALL --seconds 120 --out recordings
python3 -m pytest tests
```

`probe-ysf` writes one WAV per transmission (`probe-dmr HOST PORT ID
PASSWORD --tg TG` does the same for DMR talkgroups). `--capture FILE` also saves the
raw packets, and `python3 -m hamcast replay-ysf FILE --out DIR` decodes them
again offline (`replay-dmr` for DMR captures), so decoder changes can be
compared on identical audio.

## Credits

The YSF framing, FEC and voice-channel layout are ported from
[DroidStar](https://github.com/nostar/DroidStar) (Doug McLain AD8DP) and
[MMDVM](https://github.com/g4klx) (Jonathan Naylor G4KLX); protocol details
were checked against [xlxd](https://github.com/LX3JL/xlxd). Voice decoding
is [mbelib-neo](https://github.com/arancormonk/mbelib-neo) (arancormonk),
built on [mbelib](https://github.com/szechyjs/mbelib).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
