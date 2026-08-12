from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import aiohttp

from ..config import PortalConfig
from ..models import Job
from .base import Source

log = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Runs in the page: returns [href, best-effort card text] for every link.
_EXTRACT_JS = """() => {
    const generic = /^(learn more|view (job|role|details)|apply( now)?|more info|details|save|read more)$/i;
    return Array.from(document.querySelectorAll('a[href]')).map(e => {
        let text = (e.innerText || '').trim();
        if (!text || text.length < 4 || generic.test(text)) {
            text = e.getAttribute('aria-label') || e.getAttribute('title') || text;
        }
        if (!text || text.length < 4 || generic.test(text)) {
            const card = e.closest('li,article,tr,[class*="card"],[class*="job"],[class*="vacancy"]');
            if (card) text = (card.innerText || '').trim();
        }
        return [e.getAttribute('href'), (text || '').slice(0, 300)];
    });
}"""


class _SharedBrowser:
    """One Chromium instance shared by every portal watcher (one page each)."""

    _pw = None
    _browser = None
    _refs = 0

    @classmethod
    async def new_context(cls):
        if cls._browser is None:
            from playwright.async_api import async_playwright
            cls._pw = await async_playwright().start()
            cls._browser = await cls._pw.chromium.launch(headless=True)
        cls._refs += 1
        return await cls._browser.new_context(user_agent=USER_AGENT, locale="en-GB")

    @classmethod
    async def release(cls) -> None:
        cls._refs -= 1
        if cls._refs <= 0 and cls._browser is not None:
            await cls._browser.close()
            await cls._pw.stop()
            cls._browser = cls._pw = None


class PortalSource(Source):
    """Watches ANY company's careers page directly — no API needed.

    Loads the search URL in a headless browser (so JavaScript-rendered lists
    and WAF checks behave like a normal visitor), collects every link whose
    href matches `link_pattern`, and treats each unique link as one listing.
    The poller's dedupe then flags brand-new postings the moment they appear.
    """

    def __init__(self, cfg: PortalConfig):
        self.cfg = cfg
        self.name = f"portal:{cfg.name}"
        self.poll_seconds = cfg.poll_seconds
        self._pattern = re.compile(cfg.link_pattern)
        self._ctx = None
        self._page = None

    async def fetch(self, session: aiohttp.ClientSession) -> list[Job]:
        if self._page is None:
            self._ctx = await _SharedBrowser.new_context()
            self._page = await self._ctx.new_page()
        try:
            return await self._scrape()
        except Exception:
            # Drop the session; a fresh one is created on the next poll.
            await self.aclose()
            raise

    async def aclose(self) -> None:
        if self._ctx is not None:
            await self._ctx.close()
            self._ctx = self._page = None
            await _SharedBrowser.release()

    async def _scrape(self) -> list[Job]:
        await self._page.goto(self.cfg.url, wait_until="domcontentloaded",
                              timeout=self.cfg.timeout_seconds * 1000)
        await self._page.wait_for_timeout(self.cfg.render_wait_seconds * 1000)
        anchors = await self._page.evaluate(_EXTRACT_JS)

        jobs: dict[str, Job] = {}
        for href, text in anchors:
            if not href or not self._pattern.search(href):
                continue
            url = urljoin(self.cfg.url, href)
            key = url.split("?")[0]
            if key in jobs:
                continue
            lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
            title = lines[0] if lines else key.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
            location = next((ln for ln in lines[1:3] if len(ln) < 80), "")
            jobs[key] = Job(
                source=self.name,
                source_id=key,
                title=title[:120],
                company=self.cfg.company or self.cfg.name.title(),
                location=location,
                url=url,
                part_time=None,   # portals rarely expose this in the list view
            )
        if not jobs:
            log.debug("%s: 0 links matched %r (page: %s)",
                      self.name, self.cfg.link_pattern, await self._page.title())
        return list(jobs.values())
