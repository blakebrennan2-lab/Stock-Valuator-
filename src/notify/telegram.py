"""Telegram delivery for the top undervalued names.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env (same pattern as the FMP
key). Sends via the Bot API using only the stdlib. Never raises on a send
failure -- returns False and logs, so a scheduled run won't crash on a transient
network/credential issue.

Get credentials:
  1. Telegram -> @BotFather -> /newbot -> copy the bot token.
  2. Message your new bot, then message @userinfobot -> it returns your chat id.
Put both in .env:
  TELEGRAM_BOT_TOKEN=123456:ABC...
  TELEGRAM_CHAT_ID=123456789
"""

from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import List, Optional

from src.valuation.blender import BlendResult

API_BASE = "https://api.telegram.org"


def _load_env(env_path: str) -> None:
    if not os.path.exists(env_path):
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


class TelegramNotifier:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        _load_env(os.path.join(project_root, ".env"))
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------ #
    def format_top(self, top: List[BlendResult], as_of: Optional[str] = None) -> str:
        as_of = as_of or date.today().isoformat()
        header = (
            f"<b>📉 Top {len(top) or 5} Undervalued — S&amp;P 500</b>\n"
            f"<i>as of {as_of} · DCF·DDM·Comps blend · ≥20% margin of safety</i>\n"
        )
        if not top:
            return (
                header
                + "\nNo names cleared the 20% margin-of-safety floor.\n"
                "Nothing looks cheap enough right now — that's the floor doing its job."
            )

        lines = [header]
        for i, b in enumerate(top, 1):
            name = html.escape(b.company_name or "")
            lines.append(
                f"\n<b>{i}. {b.ticker}</b> — {name}\n"
                f"   ${b.price:,.2f} → intrinsic <b>${b.intrinsic_value:,.2f}</b> "
                f"(<b>+{b.margin_of_safety*100:.0f}% MoS</b>)\n"
                f"   <i>{b.confidence} confidence · {b.n_models} models</i>"
            )
        lines.append("\n\n<i>Not investment advice. Mechanical model output.</i>")
        return "".join(lines)

    # ------------------------------------------------------------------ #
    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.configured:
            print("Telegram not configured (set TELEGRAM_BOT_TOKEN / "
                  "TELEGRAM_CHAT_ID in .env); skipping send.")
            return False
        url = f"{API_BASE}/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": "true",
        }).encode()
        try:
            req = urllib.request.Request(url, data=payload)
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
            if not body.get("ok"):
                print(f"Telegram API error: {body}")
                return False
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"Telegram send failed: {e}")
            return False

    def send_top(self, top: List[BlendResult], as_of: Optional[str] = None) -> bool:
        return self.send_message(self.format_top(top, as_of))

    def send_many(self, messages: List[str]) -> bool:
        """Send a sequence of messages (e.g. header + one per stock). Returns
        True only if all were delivered."""
        ok = True
        for m in messages:
            if not self.send_message(m):
                ok = False
        return ok
