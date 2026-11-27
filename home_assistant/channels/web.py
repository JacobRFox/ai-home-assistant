"""Web dashboard channel: chat plus every plugin's frontend, served by FastAPI.

Routes:
    GET  /                          dashboard shell
    GET  /api/status                assistant name and model
    GET  /api/plugins               loaded plugins and their frontend modules
    POST /api/chat                  {"message": "..."} -> {"reply", "steps"}
    POST /api/chat/reset
    WS   /api/events                live event stream (plugin state changes)
    *    /api/plugins/<id>/...      each plugin's own backend router
    GET  /plugins/<id>/...          each plugin's frontend files
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .base import Channel

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "web"


class ChatBody(BaseModel):
    message: str


def create_app(channel: "WebChannel") -> FastAPI:
    assistant = channel.assistant
    app = FastAPI(title="Home Assistant", docs_url="/api/docs", openapi_url="/api/openapi.json")
    conversation = "web"

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {"name": assistant.cfg["assistant"].get("name", "Assistant"), "model": assistant.model_name}

    @app.get("/api/plugins")
    def plugins() -> list[dict[str, Any]]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "version": p.version,
                "element": p.element_tag(),
                "module": f"/plugins/{p.id}/index.js" if p.frontend_dir() else None,
                "tools": [t.name for t in p.tools()],
            }
            for p in assistant.plugins
        ]

    # Sync handlers run in FastAPI's threadpool, so the blocking agent call is fine here.
    @app.post("/api/chat")
    def chat(body: ChatBody) -> dict[str, Any]:
        text = body.message.strip()
        if text.startswith("/"):
            try:
                out = channel.handle_command(text, conversation)
            except Exception as e:
                out = f"Error: {e}"
            return {"reply": out if out is not None else "Unknown command. Try /help.", "steps": []}
        steps, reply = [], "(no response)"
        for kind, content in assistant.chat(text, conversation):
            if kind == "reply":
                reply = content
            else:
                steps.append({"kind": kind, "content": content})
        return {"reply": reply, "steps": steps}

    @app.post("/api/chat/reset")
    def reset() -> dict[str, bool]:
        assistant.reset(conversation)
        return {"ok": True}

    @app.websocket("/api/events")
    async def events(ws: WebSocket) -> None:
        await ws.accept()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)

        def forward(event: dict) -> None:  # called from whichever thread published
            loop.call_soon_threadsafe(lambda: queue.full() or queue.put_nowait(event))

        unsubscribe = assistant.events.subscribe(forward)
        try:
            while True:
                await ws.send_json(await queue.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            unsubscribe()

    for p in assistant.plugins:
        if (router := p.router()) is not None:
            app.include_router(router, prefix=f"/api/plugins/{p.id}", tags=[p.name])
        if (frontend := p.frontend_dir()) is not None:
            app.mount(f"/plugins/{p.id}", StaticFiles(directory=frontend), name=f"plugin-{p.id}")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


class WebChannel(Channel):
    def __init__(self, assistant, cfg, **kw: Any) -> None:
        super().__init__(assistant, cfg, **kw)
        web = cfg.get("channels", {}).get("web", {})
        self.host = web.get("host", "127.0.0.1")
        self.port = int(web.get("port", 8765))
        self.app = create_app(self)

    def run(self) -> None:
        if self.host not in ("127.0.0.1", "localhost", "::1"):
            log.warning("Dashboard is listening on %s with no login: anyone on your network can use it.", self.host)
        log.info("Dashboard at http://%s:%d", "localhost" if self.host in ("0.0.0.0", "127.0.0.1") else self.host, self.port)
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="warning")
