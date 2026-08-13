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
class PortalConfig:
    """A company careers page to watch directly (any employer's own portal)."""
    name: str                     # short id, e.g. "mcdonalds"
    url: str                      # the search/results page to watch
    link_pattern: str             # regex; hrefs matching this are job listings
    company: str = ""             # display name (defaults to capitalized name)
    poll_seconds: float = 60.0    # full page load per poll — keep >= 30s
    render_wait_seconds: float = 6.0   # extra wait for JS-rendered lists
    timeout_seconds: float = 45.0


@dataclass
class ApplyConfig:
    enabled: bool = False           # when False the bot only notifies
    max_per_hour: int = 12
    headless: bool = True
    cover_letter_template: str = ""  # optional path to a text file with {title}/{company} placeholders
    storage_state: str = "data/reed_login.json"
    amazon_enabled: bool = False    # EXPERIMENTAL: auto-apply on jobsatamazon.co.uk
    amazon_profile: str = "data/amazon_profile"   # persistent logged-in browser profile


@dataclass
class TelegramWatchConfig:
    """Real-time watching of Telegram groups/channels that post job links."""
    enabled: bool = False
    chats: list = field(default_factory=list)   # e.g. ["@amazonjobsuk", -1001234567890]


@dataclass
class Config:
    search: SearchConfig
    sources: dict[str, SourceConfig]
    apply: ApplyConfig
    portals: list[PortalConfig] = field(default_factory=list)
    telegram_watch: TelegramWatchConfig = field(default_factory=TelegramWatchConfig)
    db_path: str = "data/jobbot.db"

    # secrets (from environment / .env)
    reed_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    reed_email: str = ""
    reed_password: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_session: str = "data/telegram"

    @property
    def telegram_watch_chats(self) -> list:
        return self.telegram_watch.chats


def load_config(path: str | Path) -> Config:
    load_dotenv()
    data = yaml.safe_load(Path(path).read_text()) or {}

    search = SearchConfig(**(data.get("search") or {}))
    apply_cfg = ApplyConfig(**(data.get("apply") or {}))
    sources = {
        name: SourceConfig(**(cfg or {}))
        for name, cfg in (data.get("sources") or {"reed": {}, "adzuna": {}, "amazon_uk": {}}).items()
    }

    portals = [PortalConfig(**p) for p in (data.get("portals") or [])]
    tg_watch = TelegramWatchConfig(**(data.get("telegram_watch") or {}))

    cfg = Config(
        search=search,
        sources=sources,
        apply=apply_cfg,
        portals=portals,
        telegram_watch=tg_watch,
        db_path=data.get("db_path", "data/jobbot.db"),
        reed_api_key=os.getenv("REED_API_KEY", ""),
        adzuna_app_id=os.getenv("ADZUNA_APP_ID", ""),
        adzuna_app_key=os.getenv("ADZUNA_APP_KEY", ""),
        reed_email=os.getenv("REED_EMAIL", ""),
        reed_password=os.getenv("REED_PASSWORD", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        telegram_api_id=os.getenv("TELEGRAM_API_ID", ""),
        telegram_api_hash=os.getenv("TELEGRAM_API_HASH", ""),
    )
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
    return cfg
