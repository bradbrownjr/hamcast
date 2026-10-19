"""The nets hamcast streams, kept in <data_dir>/streams.json so they can be
changed from the dashboard while hamcast runs.

On first start the list is imported from config.yaml; after that
streams.json is the source of truth and config.yaml's streams are ignored
(a warning says so if they differ).
"""

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

from .config import Config, StreamConfig, validate_streams

log = logging.getLogger(__name__)


class StreamStore:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.path: Path = cfg.data_dir / "streams.json"
        if self.path.exists():
            self.streams = [StreamConfig(**s) for s in json.loads(self.path.read_text())]
            validate_streams(self.streams, cfg.dmr_id)
            if cfg.streams and [asdict(s) for s in cfg.streams] != [asdict(s) for s in self.streams]:
                log.warning("using nets from %s; the streams in config.yaml are only read on first start", self.path)
        else:
            self.streams = list(cfg.streams)
            self._save()

    def get(self, stream_id: str) -> StreamConfig | None:
        return next((s for s in self.streams if s.id == stream_id), None)

    def put(self, new: StreamConfig, replacing: str | None = None) -> None:
        """Add a stream, or replace the one with id `replacing` in place.
        Validates the whole list first, so a bad edit changes nothing."""
        streams = list(self.streams)
        if replacing is None:
            if self.get(new.id):
                raise ValueError(f"a stream with id {new.id!r} already exists")
            streams.append(new)
        else:
            index = next(i for i, s in enumerate(streams) if s.id == replacing)
            streams[index] = new
        validate_streams(streams, self.cfg.dmr_id)
        self.streams = streams
        self._save()

    def delete(self, stream_id: str) -> None:
        self.streams = [s for s in self.streams if s.id != stream_id]
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(s) for s in self.streams], indent=2))
        os.replace(tmp, self.path)
