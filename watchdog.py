"""
YoshaNewsBot watchdog.
Runs every 5 minutes via Windows Task Scheduler.
If the main bot process (pythonw main.py) is not running, restarts it
and sends a Telegram notification to the channel.

Task Scheduler entry created by setup_watchdog.py (run once).
"""

import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_DIR    = Path(__file__).parent
MAIN_SCRIPT = "main.py"
BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")


def _send_telegram(text: str) -> None:
    """Send a plain message to the configured Telegram channel."""
    if not BOT_TOKEN or not CHANNEL_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass   # watchdog must not crash on notification failure


def _is_bot_running() -> bool:
    """
    Return True if a pythonw process with 'main.py' in its command line is alive.
    Uses tasklist + WMIC for reliable detection on Windows.
    """
    try:
        # wmic gives us command-line args — more reliable than tasklist alone
        result = subprocess.run(
            ["wmic", "process", "where", "name='pythonw.exe'", "get", "CommandLine", "/value"],
            capture_output=True, text=True, timeout=10,
        )
        return MAIN_SCRIPT in result.stdout
    except Exception:
        # Fallback: just check if pythonw.exe is running at all
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq pythonw.exe"],
            capture_output=True, text=True, timeout=10,
        )
        return "pythonw.exe" in result.stdout


def _start_bot() -> None:
    """Start the bot silently in the background (no window)."""
    subprocess.Popen(
        ["pythonw", MAIN_SCRIPT],
        cwd=str(BOT_DIR),
        creationflags=0x00000008,  # DETACHED_PROCESS — no console window
    )


if __name__ == "__main__":
    if not _is_bot_running():
        _start_bot()
        _send_telegram(
            "🔄 <b>הבוט הופעל מחדש אוטומטית</b>\n\n"
            "הווatchdog זיהה שהתהליך לא היה פעיל והפעיל אותו מחדש."
        )
        sys.exit(0)
    # Bot is running — nothing to do
    sys.exit(0)
