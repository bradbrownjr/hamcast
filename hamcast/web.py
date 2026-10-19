"""Dashboard: the web app (Listen and Manage pages) plus its JSON API,
served by uvicorn.

Listening is public. Changing nets needs the admin password (see auth.py);
every change goes through the StreamStore and then Service.apply(), so the
running nets follow without a restart.
"""

import asyncio
import time
from dataclasses import asdict, fields
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import directory
from .auth import COOKIE, SESSION_SECONDS, Auth
from .config import StreamConfig

# The built web app (npm run build in web/ writes it here).
STATIC = Path(__file__).parent / "static"
_NOT_BUILT = ("<!doctype html><title>hamcast</title><p>The web app isn't built. "
              "Run <code>npm ci && npm run build</code> in hamcast's <code>web/</code> folder. "
              "The API is up: <a href=\"/api/status\">/api/status</a>.</p>")
_STREAM_FIELDS = {f.name for f in fields(StreamConfig)}


def _heard_json(h) -> dict:
    return {
        "talker": h.talker,
        "gateway": h.gateway,
        "mode": h.mode,
        "started": h.started,
        "seconds": round(h.seconds, 1),
        "recording": Path(h.recording).name if h.recording else None,
        "transcript": h.transcript,
    }


class StreamIn(BaseModel):
    id: str
    name: str
    type: str
    host: str
    port: int
    mount: str = ""
    description: str = ""
    record: bool = True
    transcribe: bool = True
    enabled: bool = True
    password: str = ""
    talkgroup: int = 0
    slot: int = 0
    options: str | None = None


class LoginIn(BaseModel):
    password: str


def build_app(service) -> FastAPI:
    app = FastAPI(title="hamcast", docs_url=None, redoc_url=None)
    cfg = service.cfg
    auth = Auth(cfg)
    public = (cfg.icecast.public_url or "").rstrip("/")

    def admin(request: Request) -> None:
        if not auth.valid(request.cookies.get(COOKIE)):
            raise HTTPException(401, "sign in to manage nets")

    # ========== STATUS (public) ==========

    def _stream_json(scfg: StreamConfig) -> dict:
        ms = service.running.get(scfg.id)
        out = {
            "id": scfg.id,
            "name": scfg.name,
            "description": scfg.description,
            "type": scfg.type,
            "source": f"{scfg.type.upper()} {scfg.host}:{scfg.port}"
                      + (f" TG{scfg.talkgroup}" if scfg.type == "dmr" else ""),
            "mount": scfg.mount,
            "listen_url": f"{public}{scfg.mount}" if public else None,
            "enabled": scfg.enabled,
            "running": ms is not None,
        }
        if ms:
            st = ms.stream.status
            out.update({
                "linked": st.linked,
                "encoder_up": ms.sink.alive(),
                "listeners": ms.listeners,
                "current": _heard_json(st.current) if st.current else None,
                "heard": [_heard_json(h) for h in st.heard],
                "frames": {"ok": st.frames_ok, "bad_fich": st.frames_bad_fich,
                           "unsupported": st.frames_unsupported},
            })
        return out

    @app.get("/api/status")
    def status() -> dict:
        return {"callsign": cfg.callsign, "now": time.time(),
                "streams": [_stream_json(s) for s in service.store.streams],
                # With no public URL the page builds player URLs from its own host.
                "icecast_port": cfg.icecast.port if cfg.icecast.bundled else None,
                "transcribing": service.transcriber.pending if service.transcriber else None}

    @app.get("/recordings/{stream_id}/{name}")
    def recording(stream_id: str, name: str) -> FileResponse:
        # Only plain filenames inside a configured stream's own directory.
        if not service.store.get(stream_id) or "/" in name or not name.endswith(".wav"):
            raise HTTPException(404)
        path = cfg.data_dir / "recordings" / stream_id / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="audio/wav")

    # ========== SIGN-IN ==========

    @app.get("/api/me")
    def me(request: Request) -> dict:
        return {"admin": auth.valid(request.cookies.get(COOKIE))}

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict:
        client = request.client.host if request.client else "?"
        if auth.throttled(client):
            raise HTTPException(429, "too many attempts; try again in 15 minutes")
        token = auth.login(body.password, client)
        if not token:
            raise HTTPException(401, "wrong password")
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            samesite="strict", secure=request.url.scheme == "https")
        return {"admin": True}

    @app.post("/api/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE)
        return {"admin": False}

    # ========== MANAGE NETS (admin) ==========

    def _config_json(s: StreamConfig) -> dict:
        return asdict(s)

    @app.get("/api/streams", dependencies=[Depends(admin)])
    def list_streams() -> dict:
        return {"streams": [_config_json(s) for s in service.store.streams],
                "callsign": cfg.callsign, "dmr_id": cfg.dmr_id}

    async def _save(body: StreamIn, replacing: str | None) -> dict:
        scfg = StreamConfig(**{k: v for k, v in body.model_dump().items() if k in _STREAM_FIELDS})
        try:
            service.store.put(scfg, replacing)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        await service.apply()
        return _config_json(service.store.get(scfg.id))

    @app.post("/api/streams", dependencies=[Depends(admin)])
    async def create_stream(body: StreamIn) -> dict:
        return await _save(body, None)

    @app.put("/api/streams/{stream_id}", dependencies=[Depends(admin)])
    async def update_stream(stream_id: str, body: StreamIn) -> dict:
        if not service.store.get(stream_id):
            raise HTTPException(404)
        return await _save(body, stream_id)

    @app.delete("/api/streams/{stream_id}", dependencies=[Depends(admin)])
    async def delete_stream(stream_id: str) -> dict:
        if not service.store.get(stream_id):
            raise HTTPException(404)
        service.store.delete(stream_id)
        await service.apply()
        return {"deleted": stream_id}

    @app.get("/api/directory/{kind}", dependencies=[Depends(admin)])
    async def host_directory(kind: str) -> dict:
        if kind not in directory.SOURCES:
            raise HTTPException(404)
        hosts = await asyncio.get_running_loop().run_in_executor(
            None, directory.listing, kind, cfg.data_dir / "directory")
        return {"hosts": hosts}

    @app.get("/api/settings", dependencies=[Depends(admin)])
    def settings() -> dict:
        """Read-only: these come from the environment or config.yaml."""
        ice, stt = cfg.icecast, cfg.transcription
        return {
            "callsign": cfg.callsign,
            "dmr_id": cfg.dmr_id,
            "icecast": {"bundled": ice.bundled, "public_url": ice.public_url or None,
                        "port": ice.port if ice.bundled else None, "bitrate": ice.bitrate},
            "transcription": {"enabled": stt.enabled,
                              "backend": ("external " + stt.url) if stt.url else "built-in faster-whisper",
                              "model": stt.model, "min_seconds": stt.min_seconds},
        }

    # ========== WEB APP ==========

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        if not (STATIC / "index.html").is_file():
            return HTMLResponse(_NOT_BUILT, status_code=503)
        target = (STATIC / path).resolve()
        if path and target.is_file() and STATIC.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(STATIC / "index.html")

    return app


async def serve_dashboard(service, stop: asyncio.Event) -> None:
    config = uvicorn.Config(build_app(service), host="0.0.0.0", port=service.cfg.dashboard_port,
                            log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await stop.wait()
    server.should_exit = True
    await task
