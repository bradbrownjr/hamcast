"""Dashboard: one status page plus a JSON API, served by uvicorn."""

import asyncio
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

_PAGE = (Path(__file__).parent / "dashboard.html").read_text()


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


def build_app(service) -> FastAPI:
    app = FastAPI(title="hamcast", docs_url=None, redoc_url=None)
    public = (service.cfg.icecast.public_url or "").rstrip("/")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE

    @app.get("/api/status")
    def status() -> dict:
        out = []
        for ms in service.streams:
            st = ms.stream.status
            out.append({
                "id": ms.scfg.id,
                "name": ms.scfg.name,
                "source": f"{ms.scfg.type.upper()} {ms.scfg.host}:{ms.scfg.port}"
                          + (f" TG{ms.scfg.talkgroup}" if ms.scfg.type == "dmr" else ""),
                "listen_url": f"{public}{ms.scfg.mount}" if public else None,
                "mount": ms.scfg.mount,
                "linked": st.linked,
                "encoder_up": ms.sink.alive(),
                "listeners": ms.listeners,
                "current": _heard_json(st.current) if st.current else None,
                "heard": [_heard_json(h) for h in st.heard],
                "frames": {"ok": st.frames_ok, "bad_fich": st.frames_bad_fich,
                           "unsupported": st.frames_unsupported},
            })
        return {"callsign": service.cfg.callsign, "now": time.time(), "streams": out,
                # With no public URL the page builds player URLs from its own host.
                "icecast_port": service.cfg.icecast.port if service.cfg.icecast.bundled else None,
                "transcribing": service.transcriber.pending if service.transcriber else None}

    @app.get("/recordings/{stream_id}/{name}")
    def recording(stream_id: str, name: str) -> FileResponse:
        # Only plain filenames inside a configured stream's own directory.
        if stream_id not in {ms.scfg.id for ms in service.streams} or "/" in name or not name.endswith(".wav"):
            raise HTTPException(404)
        path = service.cfg.data_dir / "recordings" / stream_id / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="audio/wav")

    return app


async def serve_dashboard(service, stop: asyncio.Event) -> None:
    config = uvicorn.Config(build_app(service), host="0.0.0.0", port=service.cfg.dashboard_port,
                            log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await stop.wait()
    server.should_exit = True
    await task
