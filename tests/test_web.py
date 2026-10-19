import asyncio

import pytest
from fastapi.testclient import TestClient

from hamcast.config import Config, IcecastConfig, StreamConfig
from hamcast.service import Service
from hamcast import web
from hamcast.web import build_app

YSF = {"id": "ufb", "name": "UFB", "type": "ysf", "host": "127.0.0.1", "port": 42000,
       "mount": "", "enabled": False}


@pytest.fixture
def client(tmp_path):
    cfg = Config(callsign="N0CALL", streams=[StreamConfig(**YSF)], dmr_id=312344699,
                 icecast=IcecastConfig(push_url="icecast://source:x@127.0.0.1:9"),
                 data_dir=tmp_path, admin_password="secret")
    service = Service(cfg)
    asyncio.run(service.apply())
    with TestClient(build_app(service)) as c:
        c.service = service
        yield c


def login(c, pw="secret"):
    return c.post("/api/login", json={"password": pw})


def test_status_is_public_and_hides_passwords(client):
    body = client.get("/api/status").json()
    assert body["streams"][0]["id"] == "ufb"
    assert body["streams"][0]["running"] is False
    assert "password" not in body["streams"][0]


def test_manage_needs_sign_in(client):
    assert client.get("/api/streams").status_code == 401
    assert client.post("/api/streams", json=YSF | {"id": "x"}).status_code == 401
    assert client.get("/api/me").json() == {"admin": False}


def test_wrong_password_is_throttled(client):
    for _ in range(5):
        assert login(client, "nope").status_code == 401
    assert login(client).status_code == 429


def test_crud_persists_and_validates(client):
    assert login(client).status_code == 200
    assert client.get("/api/me").json() == {"admin": True}
    dmr = {"id": "officehours", "name": "Office Hours", "type": "dmr", "host": "127.0.0.1",
           "port": 55555, "password": "PASSWORD", "talkgroup": 8801, "enabled": False}
    r = client.post("/api/streams", json=dmr)
    assert r.status_code == 200 and r.json()["mount"] == "/officehours"
    # Duplicate mount is refused and changes nothing.
    assert client.post("/api/streams", json=dmr | {"id": "other", "mount": "/officehours"}).status_code == 400
    assert client.put("/api/streams/officehours", json=dmr | {"talkgroup": 3123}).json()["talkgroup"] == 3123
    assert client.service.store.path.exists()
    assert client.delete("/api/streams/ufb").status_code == 200
    assert [s["id"] for s in client.get("/api/streams").json()["streams"]] == ["officehours"]


def test_history_is_public_and_paged(client):
    from hamcast.stream import Heard
    db = client.service.db
    for i in range(3):
        db.add("ufb", Heard(talker=f"K1BB{i}", gateway="", started=1000 + i, ended=1003 + i,
                            recording=f"/x/2026_K1BB{i}.mp3", transcript="hi", transcript_status="done"))
    r = client.get("/api/history/ufb?limit=2").json()
    assert [h["talker"] for h in r["heard"]] == ["K1BB2", "K1BB1"] and r["more"]
    assert r["heard"][0]["recording"] == "2026_K1BB2.mp3" and r["heard"][0]["id"]
    r = client.get(f"/api/history/ufb?limit=2&before={r['heard'][-1]['started']}").json()
    assert [h["talker"] for h in r["heard"]] == ["K1BB0"] and not r["more"]
    assert client.get("/api/history/nope").status_code == 404


def test_logout(client):
    login(client)
    client.post("/api/logout")
    assert client.get("/api/me").json() == {"admin": False}


def test_spa_serves_build_and_never_outside_it(client, tmp_path, monkeypatch):
    static = tmp_path / "site" / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("INDEX")
    (static / "assets" / "app.js").write_text("JS")
    (tmp_path / "site" / "secret.txt").write_text("SECRET")
    monkeypatch.setattr(web, "STATIC", static)
    assert client.get("/").text == "INDEX"
    assert client.get("/manage").text == "INDEX"
    assert client.get("/assets/app.js").text == "JS"
    assert client.get("/api/nope").status_code == 404
    for path in ("/../secret.txt", "/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt"):
        assert "SECRET" not in client.get(path).text


def test_unbuilt_web_app_says_so(client, tmp_path, monkeypatch):
    monkeypatch.setattr(web, "STATIC", tmp_path / "missing")
    r = client.get("/")
    assert r.status_code == 503 and "npm run build" in r.text
