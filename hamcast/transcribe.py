"""Transcription of finished transmissions.

Each recorded transmission is queued and transcribed one at a time, by an
OpenAI-compatible HTTP endpoint (TranscriptionConfig.url: Speaches,
hwdsl2/docker-whisper, whisper.cpp server, OpenAI...) or, with no URL, by
the bundled faster-whisper. Results are written next to the WAV as
<name>.json, appended to the stream's daily transcript-YYYYmmdd.txt as
"HH:MM:SS TALKER: text", and attached to the Heard entry for the dashboard.
"""

import asyncio
import json
import logging
import time
import urllib.request
import uuid
import wave
from pathlib import Path

from .config import TranscriptionConfig

log = logging.getLogger(__name__)


def _duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


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

    def submit(self, heard, stream_dir: Path) -> None:
        """Queue a finished, recorded transmission."""
        if not heard.recording:
            return
        self.pending += 1
        self._queue.put_nowait((heard, Path(heard.recording), stream_dir))

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
            heard, wav, stream_dir = getter.result()
            try:
                if _duration(wav) < self.cfg.min_seconds:
                    continue
                result = await loop.run_in_executor(None, self.backend.transcribe, wav)
                self._store(heard, wav, stream_dir, result)
            except Exception as exc:
                log.warning("transcribing %s failed: %s", wav.name, exc)
            finally:
                self.pending -= 1

    def _store(self, heard, wav: Path, stream_dir: Path, result: dict) -> None:
        heard.transcript = result["text"]
        record = {"talker": heard.talker, "gateway": heard.gateway, "mode": heard.mode,
                  "started": heard.started, "seconds": round(heard.seconds, 1), **result}
        wav.with_suffix(".json").write_text(json.dumps(record, indent=1))
        if result["text"]:
            day = time.strftime("%Y%m%d", time.localtime(heard.started))
            stamp = time.strftime("%H:%M:%S", time.localtime(heard.started))
            with open(stream_dir / f"transcript-{day}.txt", "a") as f:
                f.write(f"{stamp} {heard.talker}: {result['text']}\n")
