from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from ..config import SearchConfig
from ..models import Job
from .base import Source

log = logging.getLogger(__name__)

SEARCH_PAGE = "https://www.jobsatamazon.co.uk/app#/jobSearch"
JOB_URL = "https://www.jobsatamazon.co.uk/app#/jobDetail?jobId={job_id}&locale=en-GB"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_FETCH_JS = """async ({ body, auth }) => {
    const r = await fetch('/graphql', {
        method: 'POST',
        headers: {
            'content-type': 'application/json',
            'authorization': auth,
            'country': 'United Kingdom',
            'iscanary': 'false',
        },
        body,
    });
    return { status: r.status, text: await r.text() };
}"""


class AmazonUkSource(Source):
    """Amazon's own hourly-hiring portal (jobsatamazon.co.uk) — where warehouse /
    sortation-centre roles are posted. These fill within minutes, and the site sits
    behind AWS WAF, so plain HTTP requests are rejected. Instead we keep one headless
    browser page open (it passes the WAF challenge like any visitor), capture the
    site's own GraphQL search request once, then replay it in-page on every poll —
    a ~200 ms same-origin call, no reload.

    Listings are country-wide (all of England/UK); most of the time the list is
    empty — the point is to be watching the moment a hiring burst starts.
    """

    name = "amazon_uk"

    def __init__(self, search: SearchConfig, headless: bool = True):
        self._search = search
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None
        self._template: str | None = None   # verbatim body of the site's own search request
        self._auth: str = ""

    async def fetch(self, session: aiohttp.ClientSession) -> list[Job]:
        if self._page is None:
            await self._start()
        try:
            return await self._query()
        except Exception as exc:
            log.info("amazon_uk: session refresh needed (%s)", exc)
            await self._refresh()
            return await self._query()

    async def aclose(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._pw = self._browser = self._page = None

    # -- internals -----------------------------------------------------------

    async def _start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)
        ctx = await self._browser.new_context(user_agent=USER_AGENT, locale="en-GB")
        self._page = await ctx.new_page()
        self._page.on("request", self._on_request)
        await self._refresh()
        log.info("amazon_uk: browser session ready")

    def _on_request(self, request) -> None:
        # Capture the site's own job search verbatim: body (query + variables)
        # and the freshest session authorization header.
        if request.method == "POST" and request.url.rstrip("/").endswith("graphql"):
            body = request.post_data or ""
            if '"searchJobCardsByLocation"' in body:
                auth = request.headers.get("authorization", "")
                if auth:
                    self._template = body
                    self._auth = auth

    async def _refresh(self) -> None:
        self._template = None
        await self._page.goto(SEARCH_PAGE, wait_until="domcontentloaded", timeout=60_000)
        for _ in range(60):   # the app fires its search within a few seconds
            if self._template:
                return
            await asyncio.sleep(0.5)
        raise RuntimeError("did not observe the site's job search request (WAF block?)")

    async def _query(self) -> list[Job]:
        result = await self._page.evaluate(_FETCH_JS, {"body": self._template, "auth": self._auth})
        if result["status"] != 200:
            raise RuntimeError(f"graphql status {result['status']}")
        data = json.loads(result["text"])
        if data.get("errors"):
            raise RuntimeError(f"graphql errors: {data['errors'][:1]}")
        cards = (data.get("data", {}).get("searchJobCardsByLocation") or {}).get("jobCards") or []
        return [self._to_job(c) for c in cards]

    def _to_job(self, card: dict) -> Job:
        pay = ""
        if card.get("totalPayRateMin") is not None:
            pay = f"£{card['totalPayRateMin']}/hr"
            if card.get("totalPayRateMax") and card["totalPayRateMax"] != card["totalPayRateMin"]:
                pay = f"£{card['totalPayRateMin']}–£{card['totalPayRateMax']}/hr"
        location = ", ".join(
            str(v) for v in (card.get("city"), card.get("state"), card.get("postalCode")) if v
        ) or str(card.get("locationName") or "")
        emp = str(card.get("employmentType") or card.get("jobType") or "").lower()
        part_time = True if "part" in emp else False if "full" in emp else None
        return Job(
            source=self.name,
            source_id=str(card["jobId"]),
            title=str(card.get("jobTitle") or "Amazon role"),
            company="Amazon",
            location=location,
            url=JOB_URL.format(job_id=card["jobId"]),
            salary=pay,
            part_time=part_time,
            raw=card,
        )
