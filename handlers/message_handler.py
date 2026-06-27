"""
Core incoming-message handler.

Flow
----
1. Filter: private, not self, not paused, not over limit.
2. Persist user message to DB.
3. Show "typing" action.
4. Build prompt (contact vs. stranger) + fetch recent history.
5. Call Groq, receive reply.
6. Human-like delay.
7. Send reply, persist it to DB, increment counter.
8. If limit reached → send sign-off, pause user.
9. Notify owner in Saved Messages.
"""

import asyncio
import random
import logging

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatAction

from config import CONTEXT_WINDOW, MAX_MESSAGES_PER_SESSION
from db.manager import (
    add_message,
    get_recent_messages,
    get_reply_count,
    increment_reply_count,
    is_paused,
    pause_user,
)
from ai.prompts import build_system_prompt, wrap_user_message
from ai.client import generate_reply

log = logging.getLogger(__name__)

# Message that fires when the bot hits the per-session reply cap
_SIGNOFF_CONTACT = (
    "Слушай, я уже передаю контекст автору — он ответит тебе лично! 👋"
)
_SIGNOFF_STRANGER = (
    "Благодарю за обращение. Я передаю всю информацию хозяину аккаунта, "
    "он свяжется с вами в ближайшее время. Всего доброго!"
)


def register(app: Client) -> None:
    """Attach the handler to the Pyrogram client."""

    @app.on_message(
        filters.private & ~filters.me & filters.incoming & filters.text
    )
    async def handle_private(client: Client, message: Message) -> None:
        user = message.from_user
        user_id = user.id
        text = message.text.strip()

        if not text:
            return

        # ── Guard: paused user ────────────────────────────────────────────
        if await is_paused(user_id):
            log.debug("User %d is paused — skipping.", user_id)
            return

        # ── Guard: reply-count cap ────────────────────────────────────────
        count = await get_reply_count(user_id)
        if count >= MAX_MESSAGES_PER_SESSION:
            log.info("User %d hit session cap (%d). Signing off.", user_id, count)
            is_contact = getattr(user, "is_contact", False)
            signoff = _SIGNOFF_CONTACT if is_contact else _SIGNOFF_STRANGER
            await message.reply(signoff)
            await pause_user(user_id, seconds=3600)
            return

        # ── Persist incoming message ──────────────────────────────────────
        await add_message(user_id, "user", text)

        # ── Show "typing" while we wait for Groq ─────────────────────────
        await client.send_chat_action(user_id, ChatAction.TYPING)

        # ── Build prompt based on contact status ──────────────────────────
        is_contact: bool = getattr(user, "is_contact", False)
        system_prompt = build_system_prompt(is_contact)

        # ── Fetch recent context ──────────────────────────────────────────
        # We already added the current message above, so history already contains it.
        history = await get_recent_messages(user_id, limit=CONTEXT_WINDOW)
        # Remove the last entry (current message) — it will be sent as the
        # "user" turn explicitly by generate_reply, not as part of history.
        if history and history[-1]["role"] == "user":
            history = history[:-1]

        # ── Call Groq ─────────────────────────────────────────────────────
        wrapped = wrap_user_message(text)
        try:
            reply_text = await generate_reply(system_prompt, history, wrapped)
        except Exception as exc:
            log.error("Groq error for user %d: %s", user_id, exc)
            await message.reply("Секунду, небольшие технические шоколадки — скоро отвечу!")
            return

        # ── Human-like delay ──────────────────────────────────────────────
        await asyncio.sleep(random.uniform(2.0, 5.0))

        # ── Send reply ────────────────────────────────────────────────────
        await message.reply(reply_text)

        # ── Persist assistant reply + increment counter ───────────────────
        await add_message(user_id, "assistant", reply_text)
        new_count = await increment_reply_count(user_id)

        # ── Notify owner in Saved Messages ────────────────────────────────
        username = f"@{user.username}" if user.username else user.first_name
        notification = (
            f"🤖 **Автоответ отправлен**\n"
            f"👤 От: {username} (id: `{user_id}`)\n"
            f"💬 Вопрос: {text[:300]}\n"
            f"📝 Ответ: {reply_text[:300]}\n"
            f"🔢 Реплик в сессии: {new_count}/{MAX_MESSAGES_PER_SESSION}"
        )
        try:
            await client.send_message("me", notification)
        except Exception as exc:
            log.warning("Could not notify owner: %s", exc)

        # ── Auto sign-off on the final allowed reply ──────────────────────
        if new_count >= MAX_MESSAGES_PER_SESSION:
            signoff = _SIGNOFF_CONTACT if is_contact else _SIGNOFF_STRANGER
            await asyncio.sleep(random.uniform(1.0, 2.0))
            await message.reply(signoff)
            await pause_user(user_id, seconds=3600)
            log.info("Auto-signed off user %d after %d replies.", user_id, new_count)
