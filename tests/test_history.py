"""The database of transmissions, the one-time import of older recordings,
what happens to each clip's audio, and audio retention."""

import asyncio
import json
import shutil
import time
import wave

import pytest

from hamcast.config import Config, IcecastConfig, StreamConfig, TranscriptionConfig
from hamcast.db import HistoryDB
from hamcast.dmr.radioid import CallsignCache
from hamcast.service import ManagedStream, Service
from hamcast.stream import Heard
from hamcast.transcribe import Transcriber

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


def _wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * int(8000 * seconds))
    return path


def _old(d, stamp, talker, seconds, text=None):
    """A recording as hamcast made them before the database."""
    wav = _wav(d / f"{stamp}_{talker}.wav", seconds)
    if text is not None:
        started = time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S"))
        wav.with_suffix(".json").write_text(json.dumps(
            {"talker": talker, "gateway": "GW", "mode": "DN", "started": started,
             "seconds": seconds, "text": text, "segments": []}))
    return wav


def _cfg(tmp_path, **kw):
    return Config(callsign="N0CALL", streams=[], data_dir=tmp_path,
                  icecast=IcecastConfig(push_url="icecast://source:x@127.0.0.1:9"),
                  transcription=TranscriptionConfig(enabled=True, url="http://unused"), **kw)


def test_page_newest_first(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    for i in range(5):
        db.add("a", Heard(talker=f"K{i}", gateway="", started=100 + i, ended=101 + i))
    db.add("b", Heard(talker="OTHER", gateway="", started=200, ended=201))
    page, more = db.page("a", tmp_path, limit=3)
    assert [h.talker for h in page] == ["K4", "K3", "K2"] and more
    page, more = db.page("a", tmp_path, before=page[-1].started, limit=3)
    assert [h.talker for h in page] == ["K1", "K0"] and not more


@needs_ffmpeg
def test_startup_imports_old_recordings_and_finishes_their_audio(tmp_path):
    rec = tmp_path / "recordings" / "ufb"
    rec.mkdir(parents=True)
    _old(rec, "20261019-100000", "K1AAA", 3, "hello")   # transcribed: compress
    _old(rec, "20261019-100100", "K1BBB", 3)            # not transcribed: queue
    _old(rec, "20261019-100200", "K1CCC", 0.5)          # kerchunk: delete audio
    _old(rec, "20261019-100300", "KC1JMH-M-2", 3)       # name suffix, no details

    async def go():
        cfg = _cfg(tmp_path)
        db = HistoryDB(tmp_path / "hamcast.db")
        transcriber = Transcriber(cfg.transcription, tmp_path)
        scfg = StreamConfig(id="ufb", name="UFB", type="ysf", host="127.0.0.1", port=1, mount="/ufb")
        ms = ManagedStream(cfg, scfg, cfg.icecast.push_url, transcriber, CallsignCache(tmp_path / "c.json"),
                           db, set())
        await asyncio.sleep(1.5)  # let ffmpeg finish
        return ms, db, transcriber

    ms, db, transcriber = asyncio.run(go())
    shown = {h.talker: h for h in ms.stream.status.heard}
    assert list(shown) == ["KC1JMH-M", "K1CCC", "K1BBB", "K1AAA"]
    assert shown["K1AAA"].transcript == "hello" and shown["K1AAA"].recording.endswith(".mp3")
    assert (rec / "20261019-100000_K1AAA.mp3").exists() and not (rec / "20261019-100000_K1AAA.wav").exists()
    assert shown["K1CCC"].recording is None and shown["K1CCC"].transcript_status == "too_short"
    assert not (rec / "20261019-100200_K1CCC.wav").exists()
    assert shown["K1BBB"].transcript_status == "queued" and transcriber.pending == 2
    # Stored, so a second start neither imports again nor loses anything.
    page, _ = db.page("ufb", rec)
    assert [h.talker for h in page] == list(shown)
    assert page[1].recording is None and page[3].recording.endswith(".mp3")


@needs_ffmpeg
def test_new_transmission_is_stored_and_compressed_without_transcription(tmp_path):
    rec = tmp_path / "recordings" / "ufb"
    rec.mkdir(parents=True)

    async def go():
        cfg = _cfg(tmp_path)
        db = HistoryDB(tmp_path / "hamcast.db")
        scfg = StreamConfig(id="ufb", name="UFB", type="ysf", host="127.0.0.1", port=1, mount="/ufb",
                            transcribe=False)
        ms = ManagedStream(cfg, scfg, cfg.icecast.push_url, None, CallsignCache(tmp_path / "c.json"), db, set())
        h = Heard(talker="K1ZZZ", gateway="GW", started=time.time() - 3, ended=time.time(),
                  recording=str(_wav(rec / "x_K1ZZZ.wav", 3)))
        db.add("ufb", h)
        ms._process(h)
        await asyncio.sleep(1.5)
        return db, h

    db, h = asyncio.run(go())
    assert h.recording.endswith(".mp3") and h.transcript_status is None
    (row,), _ = db.page("ufb", rec)
    assert row.recording.endswith("x_K1ZZZ.mp3") and row.gateway == "GW"


def test_audio_older_than_retention_is_deleted_but_the_row_stays(tmp_path):
    cfg = _cfg(tmp_path, audio_days=90)
    service = Service(cfg)
    rec = tmp_path / "recordings" / "ufb"
    rec.mkdir(parents=True)
    old, new = rec / "old.mp3", rec / "new.mp3"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    now = time.time()
    service.db.add("ufb", Heard(talker="OLD", gateway="", started=now - 91 * 86400, ended=now - 91 * 86400 + 3,
                                recording=str(old), transcript="kept", transcript_status="done"))
    service.db.add("ufb", Heard(talker="NEW", gateway="", started=now - 3600, ended=now - 3597,
                                recording=str(new)))

    async def one_pass():
        stop = asyncio.Event()
        task = asyncio.create_task(service._expire_audio(stop))
        await asyncio.sleep(0.1)
        stop.set()
        await task

    asyncio.run(one_pass())
    assert not old.exists() and new.exists()
    rows = {h.talker: h for h in service.db.page("ufb", rec)[0]}
    assert rows["OLD"].recording is None and rows["OLD"].transcript == "kept"
    assert rows["NEW"].recording.endswith("new.mp3")
