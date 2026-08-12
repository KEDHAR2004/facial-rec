from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

import aiohttp

from .config import Config, load_config
from .filters import passes_filters
from .models import Job
from .notify import TelegramNotifier
from .sources import AdzunaSource, ReedSource, Source
from .store import Store

log = logging.getLogger("jobbot")


class Bot:
    def __init__(self, cfg: Config, apply_enabled: bool):
        self.cfg = cfg
        self.store = Store(cfg.db_path)
        self.notifier = TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
        self.apply_enabled = apply_enabled
        self.applier = None
        self._baselined: set[str] = set()  # sources that finished their first poll

    def build_sources(self) -> list[Source]:
        sources: list[Source] = []
        reed_cfg = self.cfg.sources.get("reed")
        if reed_cfg and reed_cfg.enabled:
            if self.cfg.reed_api_key:
                sources.append(ReedSource(self.cfg.reed_api_key, self.cfg.search))
            else:
                log.warning("Reed enabled but REED_API_KEY is not set — skipping")
        adzuna_cfg = self.cfg.sources.get("adzuna")
        if adzuna_cfg and adzuna_cfg.enabled:
            if self.cfg.adzuna_app_id and self.cfg.adzuna_app_key:
                sources.append(AdzunaSource(self.cfg.adzuna_app_id, self.cfg.adzuna_app_key, self.cfg.search))
            else:
                log.warning("Adzuna enabled but ADZUNA_APP_ID/ADZUNA_APP_KEY not set — skipping")
        return sources

    async def start_applier(self) -> None:
        if not self.apply_enabled:
            return
        if not (self.cfg.reed_email and self.cfg.reed_password):
            log.warning("apply.enabled but REED_EMAIL/REED_PASSWORD not set — notify-only mode")
            self.apply_enabled = False
            return
        from .applier import ReedApplier  # import lazily so notify-only mode needs no playwright

        cover = ""
        if self.cfg.apply.cover_letter_template:
            cover = Path(self.cfg.apply.cover_letter_template).read_text()
        self.applier = ReedApplier(
            self.cfg.reed_email, self.cfg.reed_password,
            storage_state=self.cfg.apply.storage_state,
            headless=self.cfg.apply.headless,
            cover_letter=cover,
        )
        await self.applier.start()
        log.info("Reed auto-apply enabled (max %d/hour)", self.cfg.apply.max_per_hour)

    async def poll_source(self, source: Source, session: aiohttp.ClientSession) -> None:
        interval = self.cfg.sources[source.name].poll_seconds
        log.info("Watching %s every %.0fs", source.name, interval)
        while True:
            started = time.monotonic()
            try:
                jobs = await source.fetch(session)
                await self.process(source, jobs, session)
            except Exception as exc:
                log.error("%s poll failed: %s", source.name, exc)
            await asyncio.sleep(max(1.0, interval - (time.monotonic() - started)))

    async def process(self, source: Source, jobs: list[Job], session: aiohttp.ClientSession) -> None:
        first_poll = source.name not in self._baselined
        new_jobs = [j for j in jobs if self.store.mark_seen(j.uid, j.title, j.url)]

        if first_poll:
            # Baseline pass: everything currently listed is "old", don't blast
            # applications at the whole backlog.
            self._baselined.add(source.name)
            log.info("%s: baseline captured (%d listings). Now watching for NEW posts.",
                     source.name, len(new_jobs))
            return

        for job in new_jobs:
            keep, reason = passes_filters(job, self.cfg.search)
            if not keep:
                log.info("skip  %s — %s", job.one_line(), reason)
                self.store.record(job.uid, "skipped", reason)
                continue
            log.info("NEW   %s  [%s]", job.one_line(), job.url)
            # Fire-and-forget so one slow application never delays the next poll.
            asyncio.create_task(self.handle_new_job(job, session))

    async def handle_new_job(self, job: Job, session: aiohttp.ClientSession) -> None:
        t0 = time.monotonic()
        applied = False
        note = ""

        if self.apply_enabled and self.applier and job.source == "reed":
            if self.store.applications_in_last(3600) >= self.cfg.apply.max_per_hour:
                note = "rate limit reached — apply manually"
                self.store.record(job.uid, "skipped", "hourly apply cap")
            else:
                ok, detail = await self.applier.apply(job)
                applied = ok
                note = f"auto-applied ({detail})" if ok else f"auto-apply failed: {detail}"
                self.store.record(job.uid, "applied" if ok else "failed", detail)
                log.info("%s %s — %s", "APPLIED" if ok else "FAILED ", job.one_line(), detail)

        if self.notifier.enabled:
            await self.notifier.send_job(session, job, note=note)
            if not applied:
                self.store.record(job.uid, "notified", "telegram")

        log.info("handled %s in %.1fs", job.uid, time.monotonic() - t0)

    async def run(self) -> None:
        sources = self.build_sources()
        if not sources:
            raise SystemExit("No sources configured — set REED_API_KEY and/or ADZUNA_APP_ID+ADZUNA_APP_KEY (see .env.example)")
        if not self.notifier.enabled:
            log.warning("Telegram not configured — new jobs will only be logged to the console")
        await self.start_applier()
        try:
            async with aiohttp.ClientSession() as session:
                await asyncio.gather(*(self.poll_source(s, session) for s in sources))
        finally:
            if self.applier:
                await self.applier.close()


async def run_once(cfg: Config) -> None:
    """Single fetch, print matches, no state changes — for testing your search."""
    bot = Bot(cfg, apply_enabled=False)
    sources = bot.build_sources()
    if not sources:
        raise SystemExit("No sources configured — set API keys in .env (see .env.example)")
    async with aiohttp.ClientSession() as session:
        for source in sources:
            jobs = await source.fetch(session)
            matches = [j for j in jobs if passes_filters(j, cfg.search)[0]]
            print(f"\n=== {source.name}: {len(jobs)} results, {len(matches)} match filters ===")
            for j in matches[:20]:
                when = j.posted_at.strftime("%Y-%m-%d %H:%M") if j.posted_at else "?"
                print(f"  [{when}] {j.one_line()}\n           {j.url}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="jobbot", description="Fast part-time job watcher & auto-applier (London/England)")
    parser.add_argument("-c", "--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--once", action="store_true", help="run one search and print results, then exit")
    parser.add_argument("--apply", action="store_true", help="enable auto-apply (overrides config)")
    parser.add_argument("--no-apply", action="store_true", help="disable auto-apply (overrides config)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    cfg = load_config(args.config)

    if args.once:
        asyncio.run(run_once(cfg))
        return

    apply_enabled = cfg.apply.enabled
    if args.apply:
        apply_enabled = True
    if args.no_apply:
        apply_enabled = False

    bot = Bot(cfg, apply_enabled=apply_enabled)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
