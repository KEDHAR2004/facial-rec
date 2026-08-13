from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from ..config import SearchConfig
from ..models import Job
from .base import Source

log = logging.getLogger(__name__)

API_URL = "https://www.reed.co.uk/api/1.0/search"


class ReedSource(Source):
    """Reed.co.uk Jobseeker API (free key: https://www.reed.co.uk/developers/jobseeker)."""

    name = "reed"

    def __init__(self, api_key: str, search: SearchConfig):
        self._auth = aiohttp.BasicAuth(api_key, "")
        self._search = search

    async def fetch(self, session: aiohttp.ClientSession) -> list[Job]:
        jobs: list[Job] = []
        keywords = self._search.keywords or [""]
        for keyword in keywords:
            for location in self._search.locations:
                params = {
                    "keywords": keyword,
                    "locationName": location,
                    "distanceFromLocation": self._search.distance_miles,
                    "resultsToTake": 100,
                }
                if self._search.part_time_only:
                    params["partTime"] = "true"
                async with session.get(
                    API_URL, params=params, auth=self._auth,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                for item in data.get("results", []):
                    jobs.append(self._to_job(item))
        return jobs

    def _to_job(self, item: dict) -> Job:
        posted = None
        if item.get("date"):
            try:
                # Reed only provides day granularity, e.g. "12/08/2026"
                posted = datetime.strptime(item["date"], "%d/%m/%Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        salary = ""
        if item.get("minimumSalary"):
            salary = f"£{item['minimumSalary']:,.0f}"
            if item.get("maximumSalary") and item["maximumSalary"] != item["minimumSalary"]:
                salary += f"–£{item['maximumSalary']:,.0f}"
        return Job(
            source=self.name,
            source_id=str(item["jobId"]),
            title=item.get("jobTitle", ""),
            company=item.get("employerName", ""),
            location=item.get("locationName", ""),
            url=item.get("jobUrl", f"https://www.reed.co.uk/jobs/{item['jobId']}"),
            posted_at=posted,
            salary=salary,
            part_time=True if self._search.part_time_only else None,
            raw=item,
        )
