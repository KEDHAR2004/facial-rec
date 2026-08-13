from __future__ import annotations

from abc import ABC, abstractmethod

import aiohttp

from ..models import Job


class Source(ABC):
    """A job board that can be polled for current openings."""

    name: str = "base"

    @abstractmethod
    async def fetch(self, session: aiohttp.ClientSession) -> list[Job]:
        """Return the current search results (the poller handles dedupe)."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release any resources (browser sessions etc.). Default: nothing."""
