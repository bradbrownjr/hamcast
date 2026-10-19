"""Configuration: config.yaml for the streams, environment variables for the
services around them.

Streams are a list and live in YAML. Everything about the services hamcast
talks to (Icecast, speech-to-text) and who it identifies as can also be set
with environment variables, which win over the YAML, so a Docker or Unraid
install can be configured from its template. See config.example.yaml and
the README's environment table.
"""

import os
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
    # DMR only. Streams on the same host, port and password share one login.
    password: str = ""
    talkgroup: int = 0
    slot: int = 0  # 0 = either timeslot
    options: str | None = None  # RPTO string; default is DMR+ static talkgroups


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


# Environment variable -> (section, field, type). Empty variables are ignored.
ENV = {
    "HAMCAST_CALLSIGN": (None, "callsign", str),
    "HAMCAST_DMR_ID": (None, "dmr_id", int),
    "HAMCAST_DATA_DIR": (None, "data_dir", Path),
    "HAMCAST_DASHBOARD_PORT": (None, "dashboard_port", int),
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
    for s in streams:
        if s.type not in ("ysf", "dmr"):
            raise ValueError(f"stream {s.id}: unsupported type {s.type!r} (supported: ysf, dmr)")
        if s.type == "dmr":
            if not dmr_id:
                raise ValueError(f"stream {s.id}: DMR streams need dmr_id (or HAMCAST_DMR_ID)")
            if not s.talkgroup or not s.password:
                raise ValueError(f"stream {s.id}: DMR streams need talkgroup and password")
        if not s.mount.startswith("/"):
            s.mount = "/" + s.mount
    ids = [s.id for s in streams]
    if len(ids) != len(set(ids)):
        raise ValueError("stream ids must be unique")

    return Config(
        callsign=str(raw["callsign"]).upper(),
        streams=streams,
        icecast=icecast,
        transcription=transcription,
        dmr_id=int(dmr_id) if dmr_id else None,
        data_dir=Path(raw.get("data_dir", "/data")),
        dashboard_port=int(raw.get("dashboard_port", 8080)),
    )
