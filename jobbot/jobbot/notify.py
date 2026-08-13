from __future__ import annotations

import html
import logging

import aiohttp

from .models import Job

log = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends instant alerts so you can apply within seconds even on boards
    the bot cannot auto-apply to. Create a bot with @BotFather to get a token."""

    def __init__(self, token: str, chat_id: str):
        self._token = token
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    async def send_job(self, session: aiohttp.ClientSession, job: Job, note: str = "") -> None:
        lines = [f"<b>{html.escape(job.title)}</b>"]
        if job.company:
            lines.append(html.escape(job.company))
        if job.location:
            lines.append(f"📍 {html.escape(job.location)}")
        if job.salary:
            lines.append(f"💰 {html.escape(job.salary)}")
        if note:
            lines.append(html.escape(note))
        lines.append(f'<a href="{html.escape(job.url)}">Apply now →</a>')
        await self._send(session, "\n".join(lines))

    async def _send(self, session: aiohttp.ClientSession, text: str) -> None:
        try:
            async with session.post(
                self._url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    log.warning("Telegram send failed (%s): %s", resp.status, await resp.text())
        except aiohttp.ClientError as exc:
            log.warning("Telegram send error: %s", exc)
