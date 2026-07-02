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
import os
import random
import logging

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatAction

import config
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
from ai.transcribe import transcribe_voice
from ai.tts import synthesize_voice

log = logging.getLogger(__name__)

# Message that fires when the bot hits the per-session reply cap (strangers only)
_SIGNOFF_STRANGER = (
    "Благодарю за обращение. Я передаю всю информацию хозяину аккаунта, "
    "он свяжется с вами в ближайшее время. Всего доброго!"
)


async def _resolve_text(message: Message, user_id: int) -> str | None:
    """
    Return the message text, transcribing voice notes via Deepgram.

    Returns None when there is nothing to act on (empty text, disabled voice,
    or a transcription failure already reported to the user).
    """
    if message.voice:
        if not config.VOICE_ENABLED:
            log.debug("Voice message from %d ignored — Deepgram disabled.", user_id)
            return None

        file_path = None
        try:
            file_path = await message.download(
                file_name=os.path.join(
                    config.DATA_DIR, f"voice_{user_id}_{message.id}.ogg"
                )
            )
            text = (await transcribe_voice(file_path)).strip()
        except Exception as exc:
            log.error("Voice transcription failed for user %d: %s", user_id, exc)
            await message.reply(
                "Не смог разобрать голосовое 🙈 Можешь написать текстом?"
            )
            return None
        finally:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass

        if not text:
            await message.reply(
                "Кажется, в голосовом ничего не расслышал — напиши текстом, пожалуйста 🙏"
            )
            return None

        log.info("Transcribed voice from %d: %s", user_id, text[:120])
        return text

    text = (message.text or "").strip()
    return text or None


async def _send_reply(message: Message, reply_text: str, as_voice: bool) -> None:
    """
    Send the reply as a voice note when `as_voice`, otherwise as text.

    Falls back to text if TTS/transcoding fails, so a synthesis error never
    leaves the user without an answer.
    """
    if as_voice and config.VOICE_REPLY_ENABLED:
        ogg_path = os.path.join(
            config.DATA_DIR, f"reply_{message.from_user.id}_{message.id}.ogg"
        )
        try:
            await synthesize_voice(reply_text, ogg_path)
            await message.reply_voice(ogg_path)
            return
        except Exception as exc:
            log.error("Voice reply synthesis failed: %s — falling back to text.", exc)
        finally:
            if os.path.exists(ogg_path):
                try:
                    os.remove(ogg_path)
                except OSError:
                    pass

    await message.reply(reply_text)


def register(app: Client) -> None:
    """Attach the handler to the Pyrogram client."""

    @app.on_message(
        filters.private
        & ~filters.me
        & filters.incoming
        & (filters.text | filters.voice)
    )
    async def handle_private(client: Client, message: Message) -> None:
        user = message.from_user
        user_id = user.id
        is_voice = bool(message.voice)  # reply in kind: voice → voice
        is_contact: bool = getattr(user, "is_contact", False)

        # ── Guard: paused user ────────────────────────────────────────────
        if await is_paused(user_id):
            log.debug("User %d is paused — skipping.", user_id)
            return

        # ── Guard: reply-count cap (strangers only) ───────────────────────
        # Contacts get an open-ended conversation — no cap, no sign-off. The
        # cap still applies to strangers so the professional flow wraps up.
        # Checked before any transcription so we never spend Deepgram credits
        # on a user who is already capped.
        if not is_contact:
            count = await get_reply_count(user_id)
            if count >= MAX_MESSAGES_PER_SESSION:
                log.info("User %d hit session cap (%d). Signing off.", user_id, count)
                await message.reply(_SIGNOFF_STRANGER)
                await pause_user(user_id, seconds=3600)
                return

        # ── Resolve message text (voice note → transcript) ────────────────
        text = await _resolve_text(message, user_id)
        if text is None:
            return

        # ── Persist incoming message ──────────────────────────────────────
        await add_message(user_id, "user", text)

        # ── Show "typing"/"recording" while we wait for Groq ──────────────
        action = ChatAction.RECORD_AUDIO if is_voice else ChatAction.TYPING
        await client.send_chat_action(user_id, action)

        # ── Build prompt based on contact status ──────────────────────────
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

        # ── Send reply (voice note if the incoming message was voice) ─────
        await _send_reply(message, reply_text, as_voice=is_voice)

        # ── Persist assistant reply ───────────────────────────────────────
        await add_message(user_id, "assistant", reply_text)

        # Counter/cap only matter for strangers (contacts chat freely).
        new_count = await increment_reply_count(user_id) if not is_contact else None

        # ── Notify owner in Saved Messages ────────────────────────────────
        username = f"@{user.username}" if user.username else user.first_name
        session_line = (
            f"🔢 Реплик в сессии: {new_count}/{MAX_MESSAGES_PER_SESSION}\n"
            if not is_contact
            else "👥 Контакт — свободный диалог\n"
        )
        notification = (
            f"🤖 **Автоответ отправлен**\n"
            f"👤 От: {username} (id: `{user_id}`)\n"
            f"💬 Вопрос: {text[:300]}\n"
            f"📝 Ответ: {reply_text[:300]}\n"
            f"{session_line}"
        )
        try:
            await client.send_message("me", notification)
        except Exception as exc:
            log.warning("Could not notify owner: %s", exc)

        # ── Auto sign-off on the final allowed reply (strangers only) ─────
        if not is_contact and new_count >= MAX_MESSAGES_PER_SESSION:
            await asyncio.sleep(random.uniform(1.0, 2.0))
            await message.reply(_SIGNOFF_STRANGER)
            await pause_user(user_id, seconds=3600)
            log.info("Auto-signed off user %d after %d replies.", user_id, new_count)
