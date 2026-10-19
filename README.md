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
> Icecast push, transcription and the web app work. Connection modes
> (on demand, scheduled) are next.

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

**Joining a net yourself while hamcast listens** is fine. YSF reflectors
(xlxd and YSFReflector) tell clients apart by IP address and port, not by
callsign, so your radio and hamcast are separate links even behind the same
router, and hamcast still receives your transmissions. You will appear
twice on the reflector's dashboard. Use your plain callsign: xlxd accepts
only letters and digits in a YSF callsign, so a tag like `-HC` is refused.
For DMR, give hamcast a hotspot suffix none of your own hotspots use.

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

hamcast is all in one: it runs its own Icecast and can transcribe every
transmission with a built-in Whisper. Either can be replaced by a service
you already run.

```sh
mkdir -p config data
cp config.example.yaml config/config.yaml   # your nets
docker run -d --name hamcast \
  -e HAMCAST_CALLSIGN=N0CALL -e HAMCAST_DMR_ID=312345699 \
  -v $PWD/config:/config:ro -v $PWD/data:/data \
  -p 8080:8080 -p 8000:8000 ghcr.io/bradbrownjr/hamcast:latest
```

The web app is on port 8080 and the streams on port 8000
(`http://host:8000/<mount>`). `docker-compose.yml` does the same with compose.

### The web app

- **Listen** (public): every net with a player, who is talking, and the
  conversation so far with each transmission's recording and transcript.
  The full view pages back through every recording kept on disk, and a
  restart picks up where it left off.
- **Manage** (password): add, edit, start, stop and delete nets while
  hamcast runs. Pick a YSF reflector or DMR master from Pi-Star's public
  host lists, or type a host and port. The password is
  `HAMCAST_ADMIN_PASSWORD`, or one generated on first start into
  `data/admin-password.txt`.

Light, dark, or follow the system: the button at the top right.

On Unraid, add the template from `unraid/hamcast.xml` (Docker > Add
Container > Template URL:
`https://raw.githubusercontent.com/bradbrownjr/hamcast/main/unraid/hamcast.xml`)
and put `config.yaml` in the Config path.

### Configuration

Nets are managed in the web app and saved in `data/streams.json`. On first
start, the nets in `config.yaml` (if any) are imported; after that
`streams.json` is used and `config.yaml`'s nets are ignored. Everything else
can be set in `config.yaml` or with these environment variables, which win:

| Variable | Default | Purpose |
|---|---|---|
| `HAMCAST_CALLSIGN` | | Your callsign (required) |
| `HAMCAST_DMR_ID` | | Your DMR ID + 2-digit hotspot suffix (DMR streams only) |
| `HAMCAST_ADMIN_PASSWORD` | generated | Password for the Manage pages (saved in `data/admin-password.txt`) |
| `HAMCAST_ICECAST_URL` | bundled | External Icecast, `icecast://source:PASSWORD@host:8000` |
| `HAMCAST_PUBLIC_URL` | this host | Base URL listeners use for streams |
| `HAMCAST_ICECAST_PORT` | 8000 | Bundled Icecast port |
| `ICECAST_SOURCE_PASSWORD`, `ICECAST_ADMIN_PASSWORD` | generated | Bundled Icecast passwords (saved in `data/icecast-passwords.json`) |
| `HAMCAST_BITRATE` | 32k | MP3 bitrate |
| `HAMCAST_TRANSCRIBE` | false | Transcribe each recorded transmission |
| `HAMCAST_STT_URL` | built-in | Any OpenAI-compatible `/v1/audio/transcriptions` server. The built-in Whisper downloads its model into `data/models` on first use, so image updates don't download it again |
| `HAMCAST_STT_MODEL` | small.en | Whisper model |
| `HAMCAST_STT_API_KEY` | | If the STT server needs one |
| `PUID`, `PGID` | 99, 100 | Owner of files in `/data` (Docker) |
| `TZ` | UTC | Time zone for file names |

Transcripts are saved beside each recording as JSON (text and timed
segments), and per stream per day as `transcript-YYYYMMDD.txt` lines of
`HH:MM:SS CALLSIGN: text`.

## Development

```sh
native/build.sh                         # builds native/libhcmbe.so (needs git, curl, gcc)
(cd web && npm ci && npm run build)     # builds the web app into hamcast/static (Node 20.19+)
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
