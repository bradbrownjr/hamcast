import json
import time
import wave

from hamcast import history
from hamcast.stream import Heard


def _wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * int(8000 * seconds))
    return path


def _recorded(d, stamp, talker, seconds, text=None):
    wav = _wav(d / f"{stamp}_{talker}.wav", seconds)
    started = time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S"))
    h = Heard(talker=talker, gateway="GW", started=started, ended=started + seconds,
              mode="DN", recording=str(wav))
    history.write_metadata(h)
    if text is not None:
        meta = json.loads(wav.with_suffix(".json").read_text())
        wav.with_suffix(".json").write_text(json.dumps(meta | {"text": text, "segments": []}))
    return wav


def test_load_pages_newest_first_with_status(tmp_path):
    _recorded(tmp_path, "20261019-100000", "K1AAA", 3, "hello")
    _recorded(tmp_path, "20261019-100100", "K1BBB", 3, "")
    _recorded(tmp_path, "20261019-100200", "K1CCC", 0.5)
    _recorded(tmp_path, "20261019-100300", "K1DDD", 3)
    # A recording from before metadata files existed, with a name suffix.
    _wav(tmp_path / "20261019-100400_KC1JMH-M-2.wav", 2)

    page, more = history.load(tmp_path, limit=3)
    assert [h.talker for h in page] == ["KC1JMH-M", "K1DDD", "K1CCC"] and more
    assert page[0].gateway == "" and round(page[0].seconds) == 2
    assert [h.transcript_status for h in page] == ["not_transcribed", "not_transcribed", "too_short"]

    older, more = history.load(tmp_path, before=page[-1].recording.rsplit("/", 1)[1], limit=3)
    assert [(h.talker, h.transcript_status, h.transcript) for h in older] == [
        ("K1BBB", "no_speech", None), ("K1AAA", "done", "hello")]
    assert older[1].gateway == "GW" and not more


def test_load_without_transcription_has_no_status(tmp_path):
    _recorded(tmp_path, "20261019-100000", "K1AAA", 3)
    (h,), _ = history.load(tmp_path, transcribed=False)
    assert h.transcript_status is None


def test_missing_folder_is_empty(tmp_path):
    assert history.load(tmp_path / "nope") == ([], False)


def test_startup_loads_recent_and_requeues_untranscribed(tmp_path):
    from hamcast.config import Config, IcecastConfig, StreamConfig, TranscriptionConfig
    from hamcast.dmr.radioid import CallsignCache
    from hamcast.service import ManagedStream
    from hamcast.transcribe import Transcriber

    rec = tmp_path / "recordings" / "ufb"
    rec.mkdir(parents=True)
    _recorded(rec, "20261019-100000", "K1AAA", 3, "hello")
    _recorded(rec, "20261019-100100", "K1BBB", 3)
    cfg = Config(callsign="N0CALL", streams=[], data_dir=tmp_path,
                 icecast=IcecastConfig(push_url="icecast://source:x@127.0.0.1:9"),
                 transcription=TranscriptionConfig(enabled=True, url="http://unused"))
    scfg = StreamConfig(id="ufb", name="UFB", type="ysf", host="127.0.0.1", port=1, mount="/ufb")
    transcriber = Transcriber(cfg.transcription, tmp_path)
    ms = ManagedStream(cfg, scfg, cfg.icecast.push_url, transcriber, CallsignCache(tmp_path / "c.json"))
    assert [h.talker for h in ms.stream.status.heard] == ["K1BBB", "K1AAA"]
    assert ms.stream.status.heard[0].transcript_status == "queued" and transcriber.pending == 1
    assert ms.stream.status.heard[1].transcript == "hello"
