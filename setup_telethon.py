"""
One-time Telethon setup script.
Run this ONCE from CMD to authenticate with your Telegram account.
After that, main.py uses the saved session automatically.

Usage:
  python setup_telethon.py
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SESSION_FILE = str(Path(__file__).parent / "yoshanews_reader")


async def setup():
    from telethon import TelegramClient

    api_id   = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    phone    = os.getenv("TELEGRAM_PHONE", "")

    if not api_id or not api_hash or not phone:
        print("ERROR: TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE must be set in .env")
        return

    print(f"Connecting to Telegram as {phone}...")
    client = TelegramClient(SESSION_FILE, api_id, api_hash)

    await client.start(phone=phone)

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"\nSUCCESS — logged in as {me.first_name} ({me.username})")
        print(f"Session saved to: {SESSION_FILE}.session")
        print("\nYou can now run: python main.py")
    else:
        print("Authentication failed — try again.")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(setup())
