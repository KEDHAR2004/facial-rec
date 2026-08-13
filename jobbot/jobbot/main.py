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
from .sources import AdzunaSource, AmazonUkSource, PortalSource, ReedSource, Source
from .store import Store

log = logging.getLogger("jobbot")


class Bot:
    def __init__(self, cfg: Config, apply_enabled: bool, amazon_apply_enabled: bool | None = None):
        self.cfg = cfg
        self.store = Store(cfg.db_path)
        self.notifier = TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
        self.apply_enabled = apply_enabled
        self.amazon_apply_enabled = (cfg.apply.amazon_enabled
                                     if amazon_apply_enabled is None else amazon_apply_enabled)
        self.applier = None
        self.amazon_applier = None
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
        browser_wanted = []
        amazon_cfg = self.cfg.sources.get("amazon_uk")
        if amazon_cfg and amazon_cfg.enabled:
            browser_wanted.append(lambda: AmazonUkSource(self.cfg.search, headless=self.cfg.apply.headless))
        for portal in self.cfg.portals:
            browser_wanted.append(lambda p=portal: PortalSource(p))
        if browser_wanted:
            try:
                import playwright  # noqa: F401
                sources.extend(factory() for factory in browser_wanted)
            except ImportError:
                log.warning("amazon_uk/portals need playwright "
                            "(pip install playwright && playwright install chromium) — skipping them")
        return sources

    async def start_applier(self) -> None:
        if self.apply_enabled:
            if not (self.cfg.reed_email and self.cfg.reed_password):
                log.warning("apply.enabled but REED_EMAIL/REED_PASSWORD not set — notify-only mode")
                self.apply_enabled = False
            else:
                from .applier import ReedApplier  # lazy so notify-only mode needs no playwright

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

        if self.amazon_apply_enabled:
            from .applier import AmazonApplier

            self.amazon_applier = AmazonApplier(
                self.cfg.apply.amazon_profile, headless=self.cfg.apply.headless)
            await self.amazon_applier.start()
            log.info("Amazon auto-apply enabled (EXPERIMENTAL, max %d/hour). "
                     "Log in once with `python -m jobbot amazon-login` if you haven't.",
                     self.cfg.apply.max_per_hour)

    async def poll_source(self, source: Source, session: aiohttp.ClientSession) -> None:
        src_cfg = self.cfg.sources.get(source.name)
        interval = src_cfg.poll_seconds if src_cfg else getattr(source, "poll_seconds", 60.0)
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

    async def dispatch_pushed(self, job: Job, session: aiohttp.ClientSession) -> None:
        """Entry point for push sources (Telegram groups) — no baseline, no
        search filters: the group already curated the job, speed is everything."""
        if not self.store.mark_seen(job.uid, job.title, job.url):
            log.info("push  %s — already seen, skipping", job.uid)
            return
        log.info("PUSH  %s  [%s]", job.one_line(), job.url)
        asyncio.create_task(self.handle_new_job(job, session))

    def _apply_capped(self, job: Job) -> bool:
        if self.store.applications_in_last(3600) >= self.cfg.apply.max_per_hour:
            self.store.record(job.uid, "skipped", "hourly apply cap")
            return True
        return False

    async def handle_new_job(self, job: Job, session: aiohttp.ClientSession) -> None:
        t0 = time.monotonic()
        applied = False
        note = ""

        if job.source == "amazon_uk":
            note = "Amazon roles fill within minutes — apply NOW"
        elif job.source.startswith("portal:"):
            note = "Direct from the company's own careers site — apply early"

        applier = None
        if job.source == "reed" and self.apply_enabled and self.applier:
            applier = self.applier
        elif job.source == "amazon_uk" and self.amazon_applier:
            applier = self.amazon_applier

        if applier is not None:
            if self._apply_capped(job):
                note = "hourly apply cap reached — apply manually: " + note
            else:
                ok, detail = await applier.apply(job)
                applied = ok
                note = f"AUTO-APPLIED ({detail})" if ok else f"auto-apply failed: {detail} — {note}"
                self.store.record(job.uid, "applied" if ok else "failed", detail)
                log.info("%s %s — %s", "APPLIED" if ok else "FAILED ", job.one_line(), detail)

        if self.notifier.enabled:
            await self.notifier.send_job(session, job, note=note)
            if not applied:
                self.store.record(job.uid, "notified", "telegram")

        log.info("handled %s in %.1fs", job.uid, time.monotonic() - t0)

    async def watch_telegram(self, session: aiohttp.ClientSession) -> None:
        from .telegram_watch import TelegramWatcher

        async def on_job(job: Job) -> None:
            await self.dispatch_pushed(job, session)

        watcher = TelegramWatcher(self.cfg, on_job)
        while True:
            try:
                await watcher.run()
                return  # clean exit (e.g. not logged in) — error already logged
            except Exception as exc:
                log.error("telegram watcher crashed: %s — reconnecting in 15s", exc)
            await asyncio.sleep(15)

    def telegram_watch_ready(self) -> bool:
        if not self.cfg.telegram_watch.enabled:
            return False
        if not (self.cfg.telegram_api_id and self.cfg.telegram_api_hash):
            log.warning("telegram_watch enabled but TELEGRAM_API_ID/TELEGRAM_API_HASH not set — skipping")
            return False
        try:
            import telethon  # noqa: F401
            return True
        except ImportError:
            log.warning("telegram_watch enabled but telethon is not installed (pip install telethon) — skipping")
            return False

    async def run(self) -> None:
        sources = self.build_sources()
        tg_ready = self.telegram_watch_ready()
        if not sources and not tg_ready:
            raise SystemExit("No sources configured — set API keys in .env and/or enable telegram_watch (see .env.example)")
        if not self.notifier.enabled:
            log.warning("Telegram alerts not configured — new jobs will only be logged to the console")
        await self.start_applier()
        try:
            async with aiohttp.ClientSession() as session:
                tasks = [self.poll_source(s, session) for s in sources]
                if tg_ready:
                    tasks.append(self.watch_telegram(session))
                await asyncio.gather(*tasks)
        finally:
            for s in sources:
                await s.aclose()
            if self.applier:
                await self.applier.close()
            if self.amazon_applier:
                await self.amazon_applier.close()


async def run_once(cfg: Config) -> None:
    """Single fetch, print matches, no state changes — for testing your search."""
    bot = Bot(cfg, apply_enabled=False)
    sources = bot.build_sources()
    if not sources:
        raise SystemExit("No sources configured — set API keys in .env (see .env.example)")
    async with aiohttp.ClientSession() as session:
        try:
            for source in sources:
                try:
                    jobs = await source.fetch(session)
                except Exception as exc:
                    print(f"\n=== {source.name}: FAILED — {exc}")
                    continue
                matches = [j for j in jobs if passes_filters(j, cfg.search)[0]]
                print(f"\n=== {source.name}: {len(jobs)} results, {len(matches)} match filters ===")
                for j in matches[:20]:
                    when = j.posted_at.strftime("%Y-%m-%d %H:%M") if j.posted_at else "?"
                    print(f"  [{when}] {j.one_line()}\n           {j.url}")
        finally:
            for source in sources:
                await source.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="jobbot", description="Fast part-time job watcher & auto-applier (London/England)")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "once", "telegram-login", "amazon-login"],
                        help="run (default) | once = single search | "
                             "telegram-login / amazon-login = one-time session setup")
    parser.add_argument("-c", "--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--once", action="store_true", help="alias for the `once` command")
    parser.add_argument("--apply", action="store_true", help="enable Reed auto-apply (overrides config)")
    parser.add_argument("--no-apply", action="store_true", help="disable ALL auto-apply (overrides config)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    cfg = load_config(args.config)

    if args.command == "telegram-login":
        from .telegram_watch import login as tg_login
        asyncio.run(tg_login(cfg))
        return
    if args.command == "amazon-login":
        from .applier.amazon_playwright import login as amz_login
        asyncio.run(amz_login(cfg.apply.amazon_profile))
        return
    if args.once or args.command == "once":
        asyncio.run(run_once(cfg))
        return

    apply_enabled = cfg.apply.enabled
    if args.apply:
        apply_enabled = True
    amazon_apply = None
    if args.no_apply:
        apply_enabled = False
        amazon_apply = False

    bot = Bot(cfg, apply_enabled=apply_enabled, amazon_apply_enabled=amazon_apply)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
