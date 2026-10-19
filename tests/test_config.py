import xml.dom.minidom

from hamcast import icecast_server
from hamcast.config import load


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p


def test_env_overrides_yaml(tmp_path):
    p = _write(tmp_path, "callsign: n0call\nstreams: []\n")
    cfg = load(p, environ={"HAMCAST_CALLSIGN": "kc1jmh", "HAMCAST_ICECAST_URL": "icecast://source:x@ice:8000",
                           "HAMCAST_TRANSCRIBE": "true", "HAMCAST_STT_URL": "http://stt:9000", "HAMCAST_DMR_ID": ""})
    assert cfg.callsign == "KC1JMH"
    assert not cfg.icecast.bundled and cfg.icecast.push_url == "icecast://source:x@ice:8000"
    assert cfg.transcription.enabled and cfg.transcription.url == "http://stt:9000"
    assert cfg.dmr_id is None  # empty variables are ignored


def test_runs_from_env_alone(tmp_path):
    cfg = load(tmp_path / "missing.yaml", environ={"HAMCAST_CALLSIGN": "KC1JMH"})
    assert cfg.streams == [] and cfg.icecast.bundled and not cfg.transcription.enabled


def test_bundled_icecast_passwords_persist_and_xml_is_valid(tmp_path):
    p = _write(tmp_path, f"callsign: KC1JMH\ndata_dir: {tmp_path}\nstreams: []\n")
    cfg = load(p, environ={})
    icecast_server.ensure_passwords(cfg)
    first = cfg.icecast.source_password
    cfg2 = load(p, environ={})
    icecast_server.ensure_passwords(cfg2)
    assert first and cfg2.icecast.source_password == first
    doc = xml.dom.minidom.parseString(icecast_server.render_xml(cfg2))
    assert doc.getElementsByTagName("source-password")[0].firstChild.data == first
    assert icecast_server.push_url(cfg2).startswith("icecast://source:")


def test_http_headers_block_has_only_header_children(tmp_path):
    # Icecast stops reading <http-headers> at the first non-<header> child,
    # so a comment there silently drops the CORS header.
    p = _write(tmp_path, f"callsign: KC1JMH\ndata_dir: {tmp_path}\nstreams: []\n")
    cfg = load(p, environ={"HAMCAST_PUBLIC_URL": "http://10.0.0.5:8010"})
    icecast_server.ensure_passwords(cfg)
    doc = xml.dom.minidom.parseString(icecast_server.render_xml(cfg))
    block = doc.getElementsByTagName("http-headers")[0]
    kids = [n for n in block.childNodes if n.nodeType != n.TEXT_NODE]
    assert [n.tagName for n in kids] == ["header"]
    assert doc.getElementsByTagName("hostname")[0].firstChild.data == "10.0.0.5"
