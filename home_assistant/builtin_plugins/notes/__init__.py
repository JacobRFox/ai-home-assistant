"""Notes and reminders to read back later."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel

from home_assistant.plugins import Command, Plugin, PluginError


class NoteBody(BaseModel):
    text: str


class NotesPlugin(Plugin):
    id = "notes"
    name = "Notes"
    description = "Notes and reminders."

    def notes(self) -> list[dict]:
        return self.ctx.store.get("notes", [])

    def _save(self, notes: list[dict]) -> None:
        self.ctx.store.set("notes", notes)
        self.ctx.emit("changed", {"notes": notes})

    def add(self, text: str) -> dict:
        if not text.strip():
            raise PluginError("A note needs some text.")
        note = {"id": uuid.uuid4().hex[:8], "text": text.strip(), "created": datetime.now().isoformat(timespec="minutes")}
        self._save(self.notes() + [note])
        return note

    def delete(self, note_id: str) -> None:
        notes = self.notes()
        remaining = [n for n in notes if n["id"] != note_id]
        if len(remaining) == len(notes):
            raise PluginError(f"No note with id {note_id}.")
        self._save(remaining)

    def tools(self) -> list[BaseTool]:
        @tool
        def save_note(text: str) -> str:
            """Save a note or reminder for later."""
            self.add(text)
            return "Note saved."

        @tool
        def get_notes() -> list[dict]:
            """Read all saved notes (each has an id, text and creation time)."""
            return self.notes()

        @tool
        def delete_note(note_id: str) -> str:
            """Delete a note by its id (call get_notes first to find it)."""
            self.delete(note_id)
            return "Note deleted."

        return [save_note, get_notes, delete_note]

    def router(self) -> APIRouter:
        r = APIRouter()

        @r.get("/notes")
        def list_notes():
            return self.notes()

        @r.post("/notes")
        def create(body: NoteBody):
            try:
                return self.add(body.text)
            except PluginError as e:
                raise HTTPException(400, str(e))

        @r.delete("/notes/{note_id}")
        def remove(note_id: str):
            try:
                self.delete(note_id)
            except PluginError as e:
                raise HTTPException(404, str(e))
            return {"ok": True}

        return r

    def commands(self) -> dict[str, Command]:
        return {"notes": Command("show saved notes", lambda _: "\n".join(f"• {n['text']}" for n in self.notes()) or "No notes saved.")}


plugin = NotesPlugin
