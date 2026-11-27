"""Telegram bot channel (long polling, so no public URL or port forwarding needed)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, MessageLimit
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from .base import Channel

log = logging.getLogger(__name__)


def split_message(text: str, limit: int = MessageLimit.MAX_TEXT_LENGTH) -> list[str]:
    """Split text into Telegram-sized chunks, preferring line breaks."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


class TelegramChannel(Channel):
    def __init__(self, assistant, cfg, **kw: Any) -> None:
        super().__init__(assistant, cfg, **kw)
        tg = cfg.get("channels", {}).get("telegram", {})
        self.token = tg.get("bot_token", "")
        if not self.token:
            raise ValueError("Telegram needs a bot token: set TELEGRAM_BOT_TOKEN or channels.telegram.bot_token.")
        self.allowed = {int(u) for u in tg.get("allowed_user_ids") or []}
        # Agent calls are blocking and the model handles one request at a time,
        # so serialize them instead of piling requests onto Ollama.
        self._lock = asyncio.Lock()

    def _authorized(self, update: Update) -> bool:
        user = update.effective_user
        return user is not None and user.id in self.allowed

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        user = update.effective_user
        if msg is None or not msg.text or user is None:
            return

        if not self._authorized(update):
            # Onboarding help: tell the user their id so the owner can allow it.
            log.warning("Rejected message from unauthorized user %s (@%s)", user.id, user.username)
            await msg.reply_text(
                f"Sorry, you're not authorized to use this assistant.\n"
                f"Your Telegram user id is {user.id}. Add it to channels.telegram.allowed_user_ids "
                f"(or TELEGRAM_ALLOWED_USERS) to get access."
            )
            return

        conversation = f"telegram:{msg.chat_id}"
        text = msg.text.strip()

        if text.startswith("/"):
            try:
                out = await asyncio.to_thread(self.handle_command, text, conversation)
            except Exception as e:
                out = f"Error: {e}"
            await msg.reply_text(out if out is not None else "Unknown command. Try /help.")
            return

        async with self._lock:
            typing = asyncio.create_task(self._keep_typing(context, msg.chat_id))
            try:
                reply = await asyncio.to_thread(self.assistant.reply, text, conversation)
            except Exception as e:
                log.exception("Agent error")
                reply = f"Something went wrong: {e}"
            finally:
                typing.cancel()

        for chunk in split_message(reply):
            await msg.reply_text(chunk)

    @staticmethod
    async def _keep_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
        """Telegram's 'typing…' indicator lasts ~5s, so refresh it while the model thinks."""
        while True:
            try:
                await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:
                pass
            await asyncio.sleep(4)

    def run(self) -> None:
        logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
        logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every poll, including the token URL
        if not self.allowed:
            log.warning("No allowed_user_ids set: the bot will reject everyone and reply with their user id.")
        app = Application.builder().token(self.token).build()
        app.add_handler(MessageHandler(filters.TEXT, self._on_message))
        log.info("Telegram bot running (model: %s). Ctrl+C to stop.", self.assistant.model_name)
        app.run_polling(allowed_updates=Update.ALL_TYPES)
