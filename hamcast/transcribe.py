"""Transcription of finished transmissions.

Each recorded transmission is queued and transcribed one at a time, by an
OpenAI-compatible HTTP endpoint (TranscriptionConfig.url: Speaches,
hwdsl2/docker-whisper, whisper.cpp server, OpenAI...) or, with no URL, by
the bundled faster-whisper. Results go on the Heard entry, to the caller's
on_done (which saves them in the database), and into the net's daily
transcript-YYYYmmdd.txt as "HH:MM:SS TALKER: text".
"""

import asyncio
import json
import logging
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

from .config import TranscriptionConfig

log = logging.getLogger(__name__)


class HttpBackend:
    def __init__(self, cfg: TranscriptionConfig) -> None:
        base = cfg.url.rstrip("/")
        self.url = base if base.endswith("/audio/transcriptions") else base + "/v1/audio/transcriptions"
        self.cfg = cfg

    def transcribe(self, path: Path) -> dict:
        boundary = uuid.uuid4().hex
        fields = {"model": self.cfg.model, "response_format": "verbose_json", "temperature": "0"}
        body = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in fields.items()
        )
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                 "Content-Type: audio/wav\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "hamcast"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.load(resp)
        return {
            "text": (data.get("text") or "").strip(),
            "segments": [{"start": s.get("start"), "end": s.get("end"), "text": (s.get("text") or "").strip()}
                         for s in data.get("segments") or []],
        }


class LocalBackend:
    """faster-whisper in-process, CPU int8. The model downloads into
    <data_dir>/models on first use."""

    def __init__(self, cfg: TranscriptionConfig, model_dir: Path) -> None:
        self.cfg = cfg
        self.model_dir = model_dir
        self._model = None

    def transcribe(self, path: Path) -> dict:
        if self._model is None:
            from faster_whisper import WhisperModel  # heavy import, only when used
            log.info("loading Whisper model %s (first use downloads it)", self.cfg.model)
            self._model = WhisperModel(self.cfg.model, device="cpu", compute_type="int8",
                                       download_root=str(self.model_dir))
        segments, _ = self._model.transcribe(str(path), beam_size=5, temperature=0, vad_filter=True)
        segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
        return {"text": " ".join(s["text"] for s in segs).strip(), "segments": segs}


class Transcriber:
    def __init__(self, cfg: TranscriptionConfig, data_dir: Path) -> None:
        self.cfg = cfg
        self.backend = HttpBackend(cfg) if cfg.url else LocalBackend(cfg, data_dir / "models")
        self._queue: asyncio.Queue = asyncio.Queue()
        self.pending = 0

    def submit(self, heard, on_done: Callable[[object, list | None], None]) -> None:
        """Queue a recorded transmission. on_done(heard, segments) runs once
        it has a transcript or has failed (segments is None then)."""
        heard.transcript_status = "queued"
        self.pending += 1
        self._queue.put_nowait((heard, on_done))

    async def run(self, stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            getter = asyncio.create_task(self._queue.get())
            stopper = asyncio.create_task(stop.wait())
            await asyncio.wait({getter, stopper}, return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel()
            if not getter.done():
                getter.cancel()
                break
            heard, on_done = getter.result()
            heard.transcript_status = "transcribing"
            segments = None
            try:
                result = await loop.run_in_executor(None, self.backend.transcribe, Path(heard.recording))
                heard.transcript = result["text"] or None
                heard.transcript_status = "done" if result["text"] else "no_speech"
                segments = result["segments"]
                if result["text"]:
                    _append_daily(heard)
            except Exception as exc:
                heard.transcript_status = "failed"
                log.warning("transcribing %s failed: %s", Path(heard.recording).name, exc)
            finally:
                self.pending -= 1
            on_done(heard, segments)


def _append_daily(heard) -> None:
    """The net's human-readable log: transcript-YYYYmmdd.txt beside its audio."""
    day = time.strftime("%Y%m%d", time.localtime(heard.started))
    stamp = time.strftime("%H:%M:%S", time.localtime(heard.started))
    with open(Path(heard.recording).parent / f"transcript-{day}.txt", "a") as f:
        f.write(f"{stamp} {heard.talker}: {heard.transcript}\n")
