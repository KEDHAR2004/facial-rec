from __future__ import annotations

from datetime import datetime, timezone

from .config import SearchConfig
from .models import Job


def passes_filters(job: Job, cfg: SearchConfig) -> tuple[bool, str]:
    """Return (keep, reason_if_dropped)."""
    title = job.title.lower()

    if cfg.include_title and not any(k.lower() in title for k in cfg.include_title):
        return False, "title does not match include_title"

    for k in cfg.exclude_title:
        if k.lower() in title:
            return False, f"title matches exclude_title '{k}'"

    if cfg.part_time_only and job.part_time is False:
        return False, "not part-time"

    if cfg.max_age_minutes and job.posted_at is not None:
        age = (datetime.now(timezone.utc) - job.posted_at).total_seconds() / 60
        if age > cfg.max_age_minutes:
            return False, f"posted {age:.0f} min ago (> {cfg.max_age_minutes})"

    return True, ""
