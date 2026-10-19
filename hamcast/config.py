"""YAML configuration. See config.example.yaml for every field."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class IcecastConfig:
    # Where ffmpeg pushes, including source credentials:
    # icecast://source:PASSWORD@host:8000
    push_url: str
    # Base URL listeners use, shown on the dashboard. Defaults to the push host.
    public_url: str = ""
    bitrate: str = "32k"


@dataclass
class StreamConfig:
    id: str
    name: str
    type: str  # "ysf"
    host: str
    port: int
    mount: str
    description: str = ""
    record: bool = True


@dataclass
class Config:
    callsign: str
    icecast: IcecastConfig
    streams: list[StreamConfig]
    data_dir: Path = Path("/data")
    dashboard_port: int = 8080
    extra: dict = field(default_factory=dict)


def load(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    streams = [StreamConfig(**s) for s in raw.get("streams", [])]
    for s in streams:
        if s.type != "ysf":
            raise ValueError(f"stream {s.id}: unsupported type {s.type!r} (supported: ysf)")
        if not s.mount.startswith("/"):
            s.mount = "/" + s.mount
    ids = [s.id for s in streams]
    if len(ids) != len(set(ids)):
        raise ValueError("stream ids must be unique")
    return Config(
        callsign=raw["callsign"].upper(),
        icecast=IcecastConfig(**raw["icecast"]),
        streams=streams,
        data_dir=Path(raw.get("data_dir", "/data")),
        dashboard_port=int(raw.get("dashboard_port", 8080)),
    )
