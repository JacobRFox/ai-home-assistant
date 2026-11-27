"""A shared shopping list."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel

from home_assistant.plugins import Command, Plugin, PluginError


class ItemsBody(BaseModel):
    items: list[str]


class ShoppingListPlugin(Plugin):
    id = "shopping_list"
    name = "Shopping List"
    description = "Things to buy."

    def items(self) -> list[str]:
        return self.ctx.store.get("items", [])

    def _save(self, items: list[str]) -> None:
        self.ctx.store.set("items", items)
        self.ctx.emit("changed", {"items": items})

    def add(self, new: list[str]) -> str:
        items = self.items()
        existing = {i.lower() for i in items}
        added = [i.strip() for i in new if i.strip() and i.strip().lower() not in existing]
        if not added:
            return "Those are already on the list."
        self._save(items + added)
        return f"Added {', '.join(added)}. The list has {len(items) + len(added)} items."

    def remove(self, item: str) -> str:
        items = self.items()
        for existing in items:
            if existing.lower() == item.strip().lower():
                items.remove(existing)
                self._save(items)
                return f"Removed {existing}."
        raise PluginError(f"{item} is not on the list.")

    def clear(self) -> str:
        self._save([])
        return "Shopping list cleared."

    def tools(self) -> list[BaseTool]:
        @tool
        def add_to_shopping_list(items: list[str]) -> str:
            """Add one or more items to the shopping list."""
            return self.add(items)

        @tool
        def remove_from_shopping_list(item: str) -> str:
            """Remove an item from the shopping list (case-insensitive)."""
            return self.remove(item)

        @tool
        def get_shopping_list() -> str:
            """Read the current shopping list."""
            return ", ".join(self.items()) or "The shopping list is empty."

        @tool
        def clear_shopping_list() -> str:
            """Remove every item from the shopping list. Only use when explicitly asked."""
            return self.clear()

        return [add_to_shopping_list, remove_from_shopping_list, get_shopping_list, clear_shopping_list]

    def router(self) -> APIRouter:
        r = APIRouter()

        @r.get("/items")
        def get_items():
            return self.items()

        @r.post("/items")
        def add_items(body: ItemsBody):
            return {"message": self.add(body.items), "items": self.items()}

        @r.delete("/items/{item}")
        def delete_item(item: str):
            try:
                return {"message": self.remove(item), "items": self.items()}
            except PluginError as e:
                raise HTTPException(404, str(e))

        @r.delete("/items")
        def clear_items():
            return {"message": self.clear(), "items": []}

        return r

    def commands(self) -> dict[str, Command]:
        return {"list": Command("show the shopping list", lambda _: "\n".join(f"• {i}" for i in self.items()) or "The shopping list is empty.")}


plugin = ShoppingListPlugin
