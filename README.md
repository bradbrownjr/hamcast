# hamcast

Stream amateur digital voice nets to anyone with a web browser.

hamcast links to a digital voice reflector **receive-only**, decodes the
audio in software, and publishes it as an ordinary Icecast/Shoutcast MP3
stream. People without a radio, a hotspot, or an app can listen to a net from
a link, and net-logging tools such as [ECTLogger](https://github.com/bradbrownjr/ectlogger)
can play it in the page.

> **Status: early development.** YSF receive and software decode work; the
> stream service, dashboard, DMR, recording and transcription are in progress.

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
  callsign or ID, so every transmission is labelled with who sent it.

## Supported sources

| Source | Status | Identity needed |
|---|---|---|
| YSF reflector (YSFReflector, XLX YSF port) | Receive + decode working | Your callsign (no password) |
| DMR Homebrew/MMDVM (DMR+ IPSC2, XLX, FreeDMR, TGIF) | Planned | Your DMR ID + hotspot suffix; network's public password |
| External Icecast source (e.g. BUTT feeding an EchoLink node) | Planned | n/a |

hamcast identifies itself with the callsign/ID of whoever runs it. Never
configure someone else's callsign or a made-up one: reflector operators watch
their dashboards.

## Vocoder and patents

Decoding uses [mbelib](https://github.com/szechyjs/mbelib), a clean-room
software implementation of the IMBE/AMBE codec family (ISC license), loaded
through a small C shim in `native/`. **AMBE+2 is covered by DVSI patents**
(US8359197 is cited as active until 2028-05-20 by the
[blip25-mbe](https://github.com/openBLIP25/blip25-mbe) project). Software AMBE
decoding is common practice for amateur and research use; assess the
patent position yourself before using hamcast commercially.

## Development

```sh
native/build.sh                         # builds native/libhcmbe.so (needs git, gcc)
python3 -m hamcast probe-ysf HOST PORT YOURCALL --seconds 120 --out recordings
python3 -m pytest tests
```

`probe-ysf` writes one WAV per transmission. `--capture FILE` also saves the
raw packets so the same audio can be re-decoded later.

## Credits

The YSF framing, FEC and voice-channel layout are ported from
[DroidStar](https://github.com/nostar/DroidStar) (Doug McLain AD8DP) and
[MMDVM](https://github.com/g4klx) (Jonathan Naylor G4KLX); protocol details
were checked against [xlxd](https://github.com/LX3JL/xlxd).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
