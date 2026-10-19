"""Configuration: config.yaml for the streams, environment variables for the
services around them.

Streams are a list and live in YAML. Everything about the services hamcast
talks to (Icecast, speech-to-text) and who it identifies as can also be set
with environment variables, which win over the YAML, so a Docker or Unraid
install can be configured from its template. See config.example.yaml and
the README's environment table.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class IcecastConfig:
    # External Icecast to push to, with its source password:
    # icecast://source:PASSWORD@host:8000. Empty = run the bundled Icecast.
    push_url: str = ""
    # Base URL listeners use, shown on the dashboard. Empty = the address the
    # dashboard was opened on, with the Icecast port.
    public_url: str = ""
    bitrate: str = "32k"
    # Bundled Icecast only.
    port: int = 8000
    source_password: str = ""  # empty = generated once and kept in data_dir
    admin_password: str = ""
    hostname: str = "localhost"

    @property
    def bundled(self) -> bool:
        return not self.push_url


@dataclass
class TranscriptionConfig:
    enabled: bool = False
    # An OpenAI-compatible /v1/audio/transcriptions endpoint (Speaches,
    # whisper.cpp server, OpenAI, ...). Empty = the bundled faster-whisper.
    url: str = ""
    model: str = "small.en"
    api_key: str = ""
    # Shorter transmissions (kerchunks, IDs) are not transcribed: Whisper
    # tends to invent text for near-silence.
    min_seconds: float = 1.5


@dataclass
class StreamConfig:
    id: str
    name: str
    type: str  # "ysf" or "dmr"
    host: str
    port: int
    mount: str
    description: str = ""
    record: bool = True
    transcribe: bool = True  # when transcription is enabled and record is on
    enabled: bool = True  # stopped nets stay configured but don't link
    # DMR only. Streams on the same host, port and password share one login.
    password: str = ""
    talkgroup: int = 0
    slot: int = 0  # 0 = either timeslot; 1 puts the talkgroup on TS1 (see dmr_plus_options)
    options: str | None = None  # RPTO string; default is DMR+ static talkgroups
    # When to be linked (see schedule.py). "always", or "needed": while
    # someone listens (on_listen, plus linger_minutes after the last one
    # leaves), or a scheduled window is open (schedule rules, or the
    # ECTLogger schedule with this id), from lead_minutes before it starts.
    connection: str = "always"
    on_listen: bool = True
    linger_minutes: int = 5
    lead_minutes: int = 10
    schedule: list = field(default_factory=list)
    ectlogger_schedule: int | None = None


@dataclass
class Config:
    callsign: str
    streams: list[StreamConfig]
    icecast: IcecastConfig = field(default_factory=IcecastConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    # Your DMR ID plus a 2-digit hotspot suffix, e.g. 312344699. Needed only
    # for DMR streams.
    dmr_id: int | None = None
    data_dir: Path = Path("/data")
    dashboard_port: int = 8080
    # Password for the dashboard's Manage pages. Empty = generated once and
    # saved in <data_dir>/admin-password.txt.
    admin_password: str = ""
    # Days to keep each transmission's audio; 0 keeps it forever. The
    # transcript and details are always kept.
    audio_days: int = 90
    # An ECTLogger site (https://app.ectlogger.us) whose schedules nets can
    # follow. Empty = off.
    ectlogger_url: str = ""


# Environment variable -> (section, field, type). Empty variables are ignored.
ENV = {
    "HAMCAST_CALLSIGN": (None, "callsign", str),
    "HAMCAST_DMR_ID": (None, "dmr_id", int),
    "HAMCAST_DATA_DIR": (None, "data_dir", Path),
    "HAMCAST_DASHBOARD_PORT": (None, "dashboard_port", int),
    "HAMCAST_ADMIN_PASSWORD": (None, "admin_password", str),
    "HAMCAST_AUDIO_DAYS": (None, "audio_days", int),
    "HAMCAST_ECTLOGGER_URL": (None, "ectlogger_url", str),
    "HAMCAST_ICECAST_URL": ("icecast", "push_url", str),
    "HAMCAST_PUBLIC_URL": ("icecast", "public_url", str),
    "HAMCAST_BITRATE": ("icecast", "bitrate", str),
    "HAMCAST_ICECAST_PORT": ("icecast", "port", int),
    "HAMCAST_ICECAST_HOSTNAME": ("icecast", "hostname", str),
    "ICECAST_SOURCE_PASSWORD": ("icecast", "source_password", str),
    "ICECAST_ADMIN_PASSWORD": ("icecast", "admin_password", str),
    "HAMCAST_TRANSCRIBE": ("transcription", "enabled", "bool"),
    "HAMCAST_STT_URL": ("transcription", "url", str),
    "HAMCAST_STT_MODEL": ("transcription", "model", str),
    "HAMCAST_STT_API_KEY": ("transcription", "api_key", str),
}


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _apply_env(raw: dict, environ) -> None:
    for var, (section, key, kind) in ENV.items():
        value = environ.get(var, "").strip()
        if not value:
            continue
        target = raw if section is None else raw.setdefault(section, {})
        target[key] = _bool(value) if kind == "bool" else value


STREAM_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def validate_stream(s: StreamConfig, dmr_id) -> None:
    """Raise ValueError with a message fit to show a user. Normalizes mount."""
    if not STREAM_ID.match(s.id or ""):
        raise ValueError("id must be 1-40 lowercase letters, digits or dashes")
    if not (s.name or "").strip():
        raise ValueError(f"stream {s.id}: name is required")
    if s.type not in ("ysf", "dmr"):
        raise ValueError(f"stream {s.id}: unsupported type {s.type!r} (supported: ysf, dmr)")
    if not s.host or not (0 < int(s.port) < 65536):
        raise ValueError(f"stream {s.id}: host and port are required")
    s.port = int(s.port)
    if s.type == "dmr":
        if not dmr_id:
            raise ValueError(f"stream {s.id}: DMR streams need dmr_id (or HAMCAST_DMR_ID)")
        if not s.talkgroup or not s.password:
            raise ValueError(f"stream {s.id}: DMR streams need talkgroup and password")
        s.talkgroup, s.slot = int(s.talkgroup), int(s.slot)
    s.mount = "/" + (s.mount or s.id).strip("/")
    if not STREAM_ID.match(s.mount[1:]):
        raise ValueError(f"stream {s.id}: mount must be /name with lowercase letters, digits or dashes")
    _validate_connection(s)


def _validate_connection(s: StreamConfig) -> None:
    from .schedule import validate_rule  # schedule.py imports this module
    if s.connection not in ("always", "needed"):
        raise ValueError(f"stream {s.id}: connection must be always or needed")
    s.linger_minutes, s.lead_minutes = int(s.linger_minutes), int(s.lead_minutes)
    if not 1 <= s.linger_minutes <= 240:
        raise ValueError(f"stream {s.id}: stay linked after listeners leave for 1 to 240 minutes")
    if not 0 <= s.lead_minutes <= 120:
        raise ValueError(f"stream {s.id}: link early by 0 to 120 minutes")
    s.schedule = [validate_rule(r, s.id) for r in (s.schedule or [])]
    if s.ectlogger_schedule in ("", 0):
        s.ectlogger_schedule = None
    if s.ectlogger_schedule is not None:
        s.ectlogger_schedule = int(s.ectlogger_schedule)
    if s.connection == "needed" and not (s.on_listen or s.schedule or s.ectlogger_schedule):
        raise ValueError(f"stream {s.id}: link when someone listens, or add a schedule, or it never links")


def validate_streams(streams: list[StreamConfig], dmr_id) -> None:
    for s in streams:
        validate_stream(s, dmr_id)
    for attr in ("id", "mount"):
        values = [getattr(s, attr) for s in streams]
        if len(values) != len(set(values)):
            raise ValueError(f"stream {attr}s must be unique")
    # DMR nets on one master share a single login, so they must agree on the
    # login's options (two logins with one DMR ID would knock each other off).
    options: dict[tuple, set] = {}
    for s in streams:
        if s.type == "dmr" and s.options is not None:
            options.setdefault((s.host, s.port), set()).add(s.options)
    for (host, port), opts in options.items():
        if len(opts) > 1:
            raise ValueError(f"DMR nets on {host}:{port} share one login and must use the same options")


def load(path: str | Path, environ=os.environ) -> Config:
    p = Path(path)
    raw = (yaml.safe_load(p.read_text()) if p.exists() else None) or {}
    _apply_env(raw, environ)

    if not raw.get("callsign"):
        raise ValueError("set your callsign (callsign: in config.yaml, or HAMCAST_CALLSIGN)")
    icecast = IcecastConfig(**raw.get("icecast", {}))
    icecast.port = int(icecast.port)
    transcription = TranscriptionConfig(**raw.get("transcription", {}))
    transcription.enabled = _bool(transcription.enabled)
    dmr_id = raw.get("dmr_id")

    streams = [StreamConfig(**s) for s in raw.get("streams", [])]
    validate_streams(streams, dmr_id)

    return Config(
        callsign=str(raw["callsign"]).upper(),
        streams=streams,
        icecast=icecast,
        transcription=transcription,
        dmr_id=int(dmr_id) if dmr_id else None,
        data_dir=Path(raw.get("data_dir", "/data")),
        dashboard_port=int(raw.get("dashboard_port", 8080)),
        admin_password=str(raw.get("admin_password", "")),
        audio_days=int(raw.get("audio_days", 90)),
        ectlogger_url=str(raw.get("ectlogger_url", "")).rstrip("/"),
    )
