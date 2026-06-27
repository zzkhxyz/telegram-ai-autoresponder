# telegram-ai-autoresponder

A Telegram **userbot** that auto-replies to your private messages while you're away, powered by an LLM. It speaks in two different personas depending on *who* is writing:

- 👋 **Friends** (people in your Telegram contacts) get a casual, friendly tone.
- 💼 **Strangers** (recruiters, business contacts) get a professional assistant that qualifies the request and promises a personal follow-up.

Built as a pet project to automate handling incoming messages — with conversation memory, per-chat rate limiting, human-like typing delays, and Docker deployment.

## Features

- **Audience-aware replies** — picks a friendly or professional system prompt based on whether the sender is a saved contact.
- **Conversation context** — keeps a sliding window of recent messages per user (SQLite) so replies stay coherent.
- **Per-session reply cap** — after N replies the bot signs off gracefully and pauses, so it never spams.
- **Human-like behaviour** — shows a "typing…" action and adds a randomized delay before answering.
- **Owner notifications** — forwards a summary of every auto-reply to your Saved Messages.
- **Prompt-injection hardening** — incoming text is wrapped and an anchor instruction is appended to every system prompt.
- **Dockerized** — `docker compose up` and it runs, persisting session + history to a volume.

## Tech stack

- **Python 3.11**
- [Pyrogram](https://docs.pyrogram.org/) — Telegram MTProto client
- [Groq](https://groq.com/) — LLM inference (`llama-3.1-8b-instant`)
- [aiosqlite](https://aiosqlite.omnilib.dev/) — async SQLite for message history
- Docker / docker-compose

## Architecture

```
main.py                 # boots Pyrogram, inits DB, registers handlers
config.py               # loads & validates env vars
handlers/
  message_handler.py    # core flow: filter → store → prompt → LLM → reply
ai/
  prompts.py            # friendly / professional system prompts + injection anchor
  client.py             # Groq API wrapper
db/
  manager.py            # async SQLite: history, reply counts, pause state
```

## Getting started

### 1. Prerequisites

- A Telegram account + API credentials from <https://my.telegram.org/apps>
- A Groq API key from <https://console.groq.com/keys>

### 2. Configure

```bash
cp .env.example .env
# then fill in your real credentials in .env
```

| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | From my.telegram.org |
| `TELEGRAM_PHONE` | Your phone number (with country code) |
| `GROQ_API_KEY` | Groq API key |
| `CONTEXT_WINDOW` | How many recent messages to send to the LLM (default 6) |
| `MAX_MESSAGES_PER_SESSION` | Replies before the bot signs off (default 6) |

### 3. Run

**Locally:**

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |   Unix: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

On first launch Pyrogram will ask you to log in (code sent to your Telegram).

**With Docker:**

```bash
docker compose up --build
```

## How it works

1. An incoming private text message is filtered (must be private, not from you, not paused, under the session cap).
2. The message is stored in SQLite.
3. The bot decides the persona from the sender's contact status and builds the matching system prompt.
4. Recent history is loaded and sent to Groq along with the new message.
5. After a short human-like delay, the reply is sent and saved.
6. A summary is forwarded to your Saved Messages.
7. Once the per-session cap is hit, the bot sends a sign-off and pauses that chat for an hour.

## Disclaimer

This is a **userbot** — it logs in as your personal Telegram account, which is against Telegram's ToS for some use cases. Use responsibly and at your own risk. Built for learning and personal automation.

## License

MIT
