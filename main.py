"""
Entry point — boots Pyrogram, initialises the DB, registers handlers.
"""

import asyncio
import logging

from pyrogram import Client

import config
from db.manager import init_db
from handlers import message_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


async def main() -> None:
    log.info("Initialising database …")
    await init_db()

    app = Client(
        name=config.SESSION_PATH,
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        phone_number=config.PHONE,
    )

    message_handler.register(app)

    log.info("Starting userbot …")
    async with app:
        log.info("Userbot is online. Listening for private messages.")
        await asyncio.Event().wait()  # run until killed


if __name__ == "__main__":
    asyncio.run(main())
