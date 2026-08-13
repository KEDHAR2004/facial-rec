from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Job:
    source: str            # "reed" | "adzuna"
    source_id: str         # id on the source board
    title: str
    company: str
    location: str
    url: str               # public page where the job can be viewed/applied
    posted_at: datetime | None = None   # best-known posting time (UTC)
    salary: str = ""
    part_time: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    def one_line(self) -> str:
        bits = [self.title, self.company, self.location]
        if self.salary:
            bits.append(self.salary)
        return " | ".join(b for b in bits if b)
