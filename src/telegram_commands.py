"""Poll Telegram for commands you send back (e.g. '/bet 7f3a 50' after
placing a bet on an alert, or '/stats' for a running ROI summary). Uses a
stored offset so each run only processes messages it hasn't seen yet."""

import json
import re
from pathlib import Path

import requests

from . import config

OFFSET_FILE = "data/telegram_offset.json"
BET_PATTERN = re.compile(r"^/bet\s+([a-f0-9]+)\s+([\d.]+)\s*$", re.IGNORECASE)


def _load_offset() -> int:
    p = Path(OFFSET_FILE)
    if not p.exists():
        return 0
    try:
        return json.loads(p.read_text()).get("offset", 0)
    except json.JSONDecodeError:
        return 0


def _save_offset(offset: int):
    p = Path(OFFSET_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"offset": offset}))


def get_new_messages() -> list[str]:
    """Return new message texts from the configured chat since the last
    processed update, and advance the stored offset so they aren't re-read
    on the next run."""
    offset = _load_offset()
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": 0}, timeout=15)
    resp.raise_for_status()
    updates = resp.json().get("result", [])

    texts = []
    max_update_id = offset - 1
    for update in updates:
        max_update_id = max(max_update_id, update["update_id"])
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")
        if chat_id == str(config.TELEGRAM_CHAT_ID) and text:
            texts.append(text.strip())

    if updates:
        _save_offset(max_update_id + 1)
    return texts


def parse_bet_command(text: str):
    """Return (short_id, stake) if text matches '/bet <id> <stake>', else None."""
    m = BET_PATTERN.match(text)
    if not m:
        return None
    return m.group(1).lower(), float(m.group(2))


def is_stats_command(text: str) -> bool:
    return text.strip().lower() == "/stats"


def send_message(text: str):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text}, timeout=15)
    resp.raise_for_status()
