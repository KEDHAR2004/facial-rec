from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class SearchConfig:
    keywords: list[str] = field(default_factory=list)      # one search per keyword ("" = all jobs)
    locations: list[str] = field(default_factory=lambda: ["London"])
    distance_miles: int = 15
    part_time_only: bool = True
    include_title: list[str] = field(default_factory=list)  # keep only if title matches any (empty = keep all)
    exclude_title: list[str] = field(default_factory=list)  # drop if title matches any
    max_age_minutes: int = 0   # 0 = disabled; else skip jobs whose posted time is older than this


@dataclass
class SourceConfig:
    enabled: bool = True
    poll_seconds: float = 30.0


@dataclass
class ApplyConfig:
    enabled: bool = False           # when False the bot only notifies
    max_per_hour: int = 12
    headless: bool = True
    cover_letter_template: str = ""  # optional path to a text file with {title}/{company} placeholders
    storage_state: str = "data/reed_login.json"


@dataclass
class Config:
    search: SearchConfig
    sources: dict[str, SourceConfig]
    apply: ApplyConfig
    db_path: str = "data/jobbot.db"

    # secrets (from environment / .env)
    reed_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    reed_email: str = ""
    reed_password: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def load_config(path: str | Path) -> Config:
    load_dotenv()
    data = yaml.safe_load(Path(path).read_text()) or {}

    search = SearchConfig(**(data.get("search") or {}))
    apply_cfg = ApplyConfig(**(data.get("apply") or {}))
    sources = {
        name: SourceConfig(**(cfg or {}))
        for name, cfg in (data.get("sources") or {"reed": {}, "adzuna": {}}).items()
    }

    cfg = Config(
        search=search,
        sources=sources,
        apply=apply_cfg,
        db_path=data.get("db_path", "data/jobbot.db"),
        reed_api_key=os.getenv("REED_API_KEY", ""),
        adzuna_app_id=os.getenv("ADZUNA_APP_ID", ""),
        adzuna_app_key=os.getenv("ADZUNA_APP_KEY", ""),
        reed_email=os.getenv("REED_EMAIL", ""),
        reed_password=os.getenv("REED_PASSWORD", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
    return cfg
