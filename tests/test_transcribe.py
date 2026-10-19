import asyncio
import wave

from hamcast.config import TranscriptionConfig
from hamcast.stream import Heard
from hamcast.transcribe import Transcriber


def _wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * int(8000 * seconds))
    return path


class FakeBackend:
    def __init__(self, results):
        self.results = results

    def transcribe(self, wav):
        r = self.results[wav.stem]
        if isinstance(r, Exception):
            raise r
        return {"text": r, "segments": []}


def test_status_follows_each_transmission(tmp_path):
    t = Transcriber(TranscriptionConfig(enabled=True, url="http://unused"), tmp_path)
    t.backend = FakeBackend({"talk": "hello", "kerchunk": "", "broken": RuntimeError("down")})
    heard = {}
    for name, secs in (("talk", 3), ("kerchunk", 2), ("broken", 2), ("short", 0.5)):
        h = Heard(talker="N0CALL", gateway="", started=0, ended=secs,
                  recording=str(_wav(tmp_path / f"{name}.wav", secs)))
        t.submit(h, tmp_path)
        heard[name] = h
    assert heard["short"].transcript_status == "too_short"
    assert heard["talk"].transcript_status == "queued"

    async def drain():
        stop = asyncio.Event()
        task = asyncio.create_task(t.run(stop))
        while t.pending:
            await asyncio.sleep(0.01)
        stop.set()
        await task

    asyncio.run(drain())
    assert {k: h.transcript_status for k, h in heard.items()} == {
        "talk": "done", "kerchunk": "no_speech", "broken": "failed", "short": "too_short"}
    assert heard["talk"].transcript == "hello"
