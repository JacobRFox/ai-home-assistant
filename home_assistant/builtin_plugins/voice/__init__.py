"""Hands-free voice control for the web dashboard.

The browser streams microphone audio to this plugin over a WebSocket. Everything
runs locally: openWakeWord listens for the wake word, then the command is
transcribed with Whisper (faster-whisper) and sent to the assistant, like typed chat.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from home_assistant.plugins import Plugin

if TYPE_CHECKING:
    from .engine import Transcriber, WakeWordDetector

# The speech packages (numpy, openwakeword, faster-whisper) are optional and imported
# lazily, so the plugin still loads without them and its card shows how to install them.
INSTALL_HINT = "Voice needs extra packages: pip install -r requirements-voice.txt"


def phrase_from_model(name_or_path: str) -> str:
    """'hey_jarvis' or '/models/hey_jarvis_v0.1.onnx' -> 'hey jarvis'."""
    stem = Path(name_or_path).name.split(".onnx")[0].split(".tflite")[0]
    return re.sub(r"_v\d+(\.\d+)*$", "", stem).replace("_", " ")


class VoicePlugin(Plugin):
    id = "voice"
    name = "Voice"
    description = "Wake word and spoken commands. All audio stays on this computer."

    def setup(self) -> None:
        c = self.ctx.config
        self.wake_word = c.get("wake_word", "hey_jarvis")
        self.wake_phrase = c.get("wake_phrase") or phrase_from_model(self.wake_word)
        self.threshold = float(c.get("threshold", 0.5))
        self.silence_s = float(c.get("silence_seconds", 0.8))
        self.max_s = float(c.get("max_command_seconds", 10))
        self.conversation = c.get("conversation", "web")  # share history with the dashboard's typed chat
        self.wake_model = ""
        self.transcriber: Transcriber | None = None
        self.error: str | None = None
        self.ready = threading.Event()
        # Model downloads can take a while on first run, so don't block startup.
        threading.Thread(target=self._load, name="voice-models", daemon=True).start()

    def _load(self) -> None:
        try:
            try:
                from .engine import Transcriber, WakeWordDetector, prepare_wake_word
            except ImportError as e:
                raise RuntimeError(INSTALL_HINT) from e
            self.wake_model = prepare_wake_word(self.wake_word)
            WakeWordDetector(self.wake_model, self.threshold)  # fail early if the model can't load
            c = self.ctx.config
            self.transcriber = Transcriber(c.get("stt_model", "base.en"), c.get("device", "auto"), c.get("language", "en"))
            self.ready.set()
            self.ctx.log.info("Voice ready: say '%s' (speech-to-text on %s)", self.wake_phrase, self.transcriber.device)
        except Exception as e:
            self.error = str(e)
            self.ctx.log.error("Voice unavailable: %s", e)
        self.ctx.emit("status", self.status())

    def status(self) -> dict[str, Any]:
        return {"ready": self.ready.is_set(), "error": self.error, "wake_phrase": self.wake_phrase}

    def _ask(self, text: str) -> dict[str, Any]:
        steps, reply = [], "(no response)"
        for kind, content in self.ctx.assistant.chat(text, self.conversation):
            if kind == "reply":
                reply = content
            else:
                steps.append({"kind": kind, "content": content})
        return {"text": reply, "steps": steps}

    def router(self) -> APIRouter:
        r = APIRouter()

        @r.get("/status")
        def get_status():
            return self.status()

        @r.websocket("/stream")
        async def stream(ws: WebSocket) -> None:
            await ws.accept()
            await VoiceSession(self, ws).run()

        return r


class VoiceSession:
    """One browser's audio stream: listening -> recording -> processing -> listening."""

    def __init__(self, plugin: VoicePlugin, ws: WebSocket) -> None:
        self.p = plugin
        self.ws = ws
        self.state = "loading"
        # Created once the models are ready (the speech packages may not be installed).
        self.detector: WakeWordDetector | None = None
        self.recorder: Any = None
        self.engine: Any = None
        self.task: asyncio.Task | None = None

    async def send(self, type: str, **data: Any) -> None:
        try:
            await self.ws.send_json({"type": type, **data})
        except Exception:
            pass  # browser went away; the receive loop will notice

    async def run(self) -> None:
        await self.send("status", **self.p.status())
        if self.p.error:
            await self.ws.close()
            return
        loader = asyncio.create_task(self._when_ready())
        try:
            while True:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    if self.engine:  # audio before the models are ready is dropped
                        await self._on_audio(self.engine.pcm_frame(msg["bytes"]))
                elif msg.get("text"):
                    await self._on_control(json.loads(msg["text"]))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            loader.cancel()
            if self.task:
                self.task.cancel()

    async def _when_ready(self) -> None:
        await asyncio.to_thread(self.p.ready.wait)
        from . import engine

        self.detector = await asyncio.to_thread(engine.WakeWordDetector, self.p.wake_model, self.p.threshold)
        self.recorder = engine.CommandRecorder(self.p.silence_s, self.p.max_s)
        self.engine = engine
        self.state = "listening"
        await self.send("status", **self.p.status())

    async def _on_control(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "talk" and self.state == "listening":  # push-to-talk: skip the wake word
            self._start_recording()
            await self.send("wake", score=None)
        elif kind in ("resume", "cancel") and self.state != "processing":
            self._listen()
            await self.send("listening")

    async def _on_audio(self, frame: np.ndarray) -> None:
        if self.state == "listening" and self.detector:
            self.recorder.observe_background(frame)
            score = await asyncio.to_thread(self.detector, frame)
            if score is not None:
                self._start_recording()
                await self.send("wake", score=round(score, 3))
        elif self.state == "recording" and self.recorder.add(frame):
            self.state = "processing"
            await self.send("processing")
            self.task = asyncio.create_task(self._process(self.recorder.audio()))

    def _start_recording(self) -> None:
        self.recorder.reset()
        self.state = "recording"

    def _listen(self) -> None:
        if self.detector:
            self.detector.reset()  # forget audio from before, so the wake word can't re-fire on it
        self.state = "listening"

    async def _process(self, audio: np.ndarray) -> None:
        try:
            text = await asyncio.to_thread(self.p.transcriber, audio) if self.p.transcriber else ""
            if not text:
                await self.send("nothing_heard")
                return
            await self.send("transcript", text=text)
            reply = await asyncio.to_thread(self.p._ask, text)
            await self.send("reply", **reply)
        except Exception as e:
            self.p.ctx.log.exception("Voice command failed")
            await self.send("error", message=f"Voice command failed: {e}")
        finally:
            self._listen()
            await self.send("listening")


plugin = VoicePlugin
