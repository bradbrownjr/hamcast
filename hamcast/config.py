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
    type: str  # "ysf" or "dmr"
    host: str
    port: int
    mount: str
    description: str = ""
    record: bool = True
    # DMR only. Streams on the same host, port and password share one login.
    password: str = ""
    talkgroup: int = 0
    slot: int = 0  # 0 = either timeslot
    options: str | None = None  # RPTO string; default is DMR+ static talkgroups


@dataclass
class Config:
    callsign: str
    icecast: IcecastConfig
    streams: list[StreamConfig]
    # Your DMR ID plus a 2-digit hotspot suffix, e.g. 312344699. Needed only
    # for DMR streams.
    dmr_id: int | None = None
    data_dir: Path = Path("/data")
    dashboard_port: int = 8080
    extra: dict = field(default_factory=dict)


def load(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    streams = [StreamConfig(**s) for s in raw.get("streams", [])]
    dmr_id = raw.get("dmr_id")
    for s in streams:
        if s.type not in ("ysf", "dmr"):
            raise ValueError(f"stream {s.id}: unsupported type {s.type!r} (supported: ysf, dmr)")
        if s.type == "dmr":
            if not dmr_id:
                raise ValueError(f"stream {s.id}: DMR streams need a top-level dmr_id")
            if not s.talkgroup or not s.password:
                raise ValueError(f"stream {s.id}: DMR streams need talkgroup and password")
        if not s.mount.startswith("/"):
            s.mount = "/" + s.mount
    ids = [s.id for s in streams]
    if len(ids) != len(set(ids)):
        raise ValueError("stream ids must be unique")
    return Config(
        callsign=raw["callsign"].upper(),
        icecast=IcecastConfig(**raw["icecast"]),
        streams=streams,
        dmr_id=int(dmr_id) if dmr_id else None,
        data_dir=Path(raw.get("data_dir", "/data")),
        dashboard_port=int(raw.get("dashboard_port", 8080)),
    )
