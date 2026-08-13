from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from ..config import SearchConfig
from ..models import Job
from .base import Source

log = logging.getLogger(__name__)

API_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/1"


class AdzunaSource(Source):
    """Adzuna GB API (free key: https://developer.adzuna.com/). Gives minute-level
    posting timestamps and covers many boards, so it is the best 'freshness' signal."""

    name = "adzuna"

    def __init__(self, app_id: str, app_key: str, search: SearchConfig):
        self._app_id = app_id
        self._app_key = app_key
        self._search = search

    async def fetch(self, session: aiohttp.ClientSession) -> list[Job]:
        jobs: list[Job] = []
        keywords = self._search.keywords or [""]
        for keyword in keywords:
            for location in self._search.locations:
                params = {
                    "app_id": self._app_id,
                    "app_key": self._app_key,
                    "what": keyword,
                    "where": location,
                    "distance": int(self._search.distance_miles * 1.609),  # km
                    "sort_by": "date",
                    "results_per_page": 50,
                }
                if self._search.part_time_only:
                    params["part_time"] = 1
                async with session.get(
                    API_URL, params=params, timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                for item in data.get("results", []):
                    jobs.append(self._to_job(item))
        return jobs

    def _to_job(self, item: dict) -> Job:
        posted = None
        if item.get("created"):
            try:
                posted = datetime.fromisoformat(item["created"].replace("Z", "+00:00"))
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        salary = ""
        if item.get("salary_min"):
            salary = f"£{item['salary_min']:,.0f}"
            if item.get("salary_max") and item["salary_max"] != item["salary_min"]:
                salary += f"–£{item['salary_max']:,.0f}"
        contract_time = item.get("contract_time")  # "part_time" / "full_time" / None
        return Job(
            source=self.name,
            source_id=str(item["id"]),
            title=item.get("title", "").replace("<strong>", "").replace("</strong>", ""),
            company=(item.get("company") or {}).get("display_name", ""),
            location=(item.get("location") or {}).get("display_name", ""),
            url=item.get("redirect_url", ""),
            posted_at=posted,
            salary=salary,
            part_time=None if contract_time is None else contract_time == "part_time",
            raw=item,
        )
