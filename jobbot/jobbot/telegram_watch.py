from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable

from .config import Config
from .models import Job

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
JOB_ID_RE = re.compile(r"jobId=([A-Za-z0-9_%-]+)")

AMAZON_HOSTS = ("jobsatamazon.co.uk", "hiring.amazon.", "hvr.amazon.")


def is_amazon_url(url: str) -> bool:
    return any(h in url for h in AMAZON_HOSTS)


def jobs_from_message(text: str, urls: list[str], chat: str) -> list[Job]:
    """Turn one Telegram message into Job objects (pure function, unit-tested).

    Amazon links are normalised onto the `amazon_uk` source with the jobId as
    the id, so a job seen here and the same job seen by the portal poller
    dedupe to a single application. Other links become generic `telegram` jobs.
    """
    all_urls = list(dict.fromkeys(urls + URL_RE.findall(text or "")))
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    title = (lines[0] if lines else "Job alert")[:120]

    jobs: list[Job] = []
    for url in all_urls:
        url = url.rstrip(".,;")
        if is_amazon_url(url):
            m = JOB_ID_RE.search(url)
            job_id = m.group(1) if m else url
            jobs.append(Job(
                source="amazon_uk", source_id=job_id,
                title=title, company="Amazon", location="",
                url=url, part_time=None,
                raw={"telegram_chat": chat, "message": (text or "")[:500]},
            ))
        else:
            jobs.append(Job(
                source="telegram", source_id=url,
                title=title, company="", location="",
                url=url, part_time=None,
                raw={"telegram_chat": chat},
            ))
    return jobs


class TelegramWatcher:
    """Listens to Telegram groups/channels for job posts and pushes them into
    the pipeline the second they arrive (true push — no polling delay).

    Needs a Telegram *user* session (bots can't read groups they aren't in):
    get api credentials at https://my.telegram.org → API development tools,
    then log in once with `python -m jobbot telegram-login`.
    """

    def __init__(self, cfg: Config, on_job: Callable[[Job], Awaitable[None]]):
        self.cfg = cfg
        self.on_job = on_job

    async def run(self) -> None:
        from telethon import TelegramClient, events

        client = TelegramClient(self.cfg.telegram_session, int(self.cfg.telegram_api_id),
                                self.cfg.telegram_api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            log.error("Telegram watcher: not logged in — run `python -m jobbot telegram-login` first")
            await client.disconnect()
            return

        chats = self.cfg.telegram_watch_chats

        @client.on(events.NewMessage(chats=chats or None))
        async def handler(event) -> None:
            msg = event.message
            urls: list[str] = []
            for ent, ent_text in (msg.get_entities_text() or []):
                url = getattr(ent, "url", None) or (ent_text if ent_text.startswith("http") else None)
                if url:
                    urls.append(url)
            if msg.buttons:
                for row in msg.buttons:
                    for btn in row:
                        if getattr(btn, "url", None):
                            urls.append(btn.url)
            chat_name = getattr(event.chat, "username", None) or str(event.chat_id)
            found = jobs_from_message(msg.raw_text or "", urls, chat_name)
            if found:
                log.info("telegram: %d job link(s) in message from %s", len(found), chat_name)
            for job in found:
                await self.on_job(job)

        me = await client.get_me()
        log.info("Telegram watcher: logged in as %s, watching %s",
                 getattr(me, "username", None) or me.first_name,
                 ", ".join(str(c) for c in chats) if chats else "ALL chats")
        await client.run_until_disconnected()


async def login(cfg: Config) -> None:
    """Interactive one-time login (asks for phone + code in the terminal)."""
    from telethon import TelegramClient

    if not (cfg.telegram_api_id and cfg.telegram_api_hash):
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first "
                         "(get them at https://my.telegram.org → API development tools)")
    client = TelegramClient(cfg.telegram_session, int(cfg.telegram_api_id), cfg.telegram_api_hash)
    await client.start()   # prompts for phone number and login code
    me = await client.get_me()
    print(f"Logged in as {getattr(me, 'username', None) or me.first_name}. "
          f"Session saved to {cfg.telegram_session}.session — the watcher can now run.")
    print("\nYour recent chats (use these names/ids in telegram_watch.chats):")
    async for dialog in client.iter_dialogs(limit=25):
        kind = "channel" if dialog.is_channel else "group" if dialog.is_group else "chat"
        uname = f"@{dialog.entity.username}" if getattr(dialog.entity, "username", None) else dialog.id
        print(f"  [{kind:7s}] {uname}  —  {dialog.name}")
    await client.disconnect()
