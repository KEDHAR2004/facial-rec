"""Offline smoke test: mocks a job board and checks baseline, dedupe,
filtering, dispatch, and Telegram message parsing.
Run: .venv/bin/python test_pipeline.py"""
import asyncio
import logging

from jobbot.config import ApplyConfig, Config, SearchConfig, SourceConfig
from jobbot.main import Bot
from jobbot.models import Job
from jobbot.sources.base import Source
from jobbot.telegram_watch import jobs_from_message

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")


def test_telegram_parsing():
    # Amazon link in text -> amazon_uk job keyed by jobId (dedupes with the portal poller)
    msg = ("🔥 Amazon Warehouse Operative — Tilbury £13.50/hr\n"
           "Apply: https://www.jobsatamazon.co.uk/app#/jobDetail?jobId=JOB-GB-123&locale=en-GB")
    jobs = jobs_from_message(msg, [], "@amazonalerts")
    assert len(jobs) == 1, jobs
    assert jobs[0].source == "amazon_uk" and jobs[0].source_id == "JOB-GB-123", jobs[0]
    assert jobs[0].uid == "amazon_uk:JOB-GB-123"
    assert "Warehouse Operative" in jobs[0].title

    # Hidden/button link + non-amazon link; url list deduped with text urls
    jobs = jobs_from_message(
        "New shifts!", ["https://www.jobsatamazon.co.uk/app#/jobDetail?jobId=X9&locale=en-GB",
                        "https://example.org/some-job"], "chat")
    assert {j.source for j in jobs} == {"amazon_uk", "telegram"}, jobs

    # No links -> no jobs (ignore chatter)
    assert jobs_from_message("good morning all", [], "chat") == []
    print("TELEGRAM_PARSING_OK")


class FakeBoard(Source):
    name = "fake"

    def __init__(self):
        self.batch: list[Job] = []

    async def fetch(self, session):
        return list(self.batch)


def job(i: int, title: str) -> Job:
    return Job(source="fake", source_id=str(i), title=title, company="Acme",
               location="London", url=f"https://example.com/{i}", part_time=True)


async def main():
    cfg = Config(
        search=SearchConfig(exclude_title=["manager"]),
        sources={"fake": SourceConfig()},
        apply=ApplyConfig(),
        db_path="data/test.db",
    )
    bot = Bot(cfg, apply_enabled=False)
    board = FakeBoard()

    handled: list[str] = []
    async def fake_handle(j, session):
        handled.append(j.uid)
    bot.handle_new_job = fake_handle

    # Poll 1: two existing listings -> baseline only, nothing dispatched
    board.batch = [job(1, "Barista"), job(2, "Retail Assistant")]
    await bot.process(board, board.batch, session=None)
    assert handled == [], handled

    # Poll 2: same listings -> still nothing (dedupe)
    await bot.process(board, board.batch, session=None)
    assert handled == [], handled

    # Poll 3: two new jobs, one filtered out by exclude_title
    board.batch += [job(3, "Warehouse Operative"), job(4, "Store Manager")]
    await bot.process(board, board.batch, session=None)
    await asyncio.sleep(0.05)  # let the create_task dispatch run
    assert handled == ["fake:3"], handled

    # Push dispatch (telegram path): dedupe against poller, no baseline needed
    pushed: list[str] = []
    bot.handle_new_job = lambda j, s: pushed.append(j.uid) or asyncio.sleep(0)
    tg_jobs = jobs_from_message(
        "Warehouse shift!", ["https://www.jobsatamazon.co.uk/app#/jobDetail?jobId=NEW1"], "grp")
    await bot.dispatch_pushed(tg_jobs[0], session=None)
    await bot.dispatch_pushed(tg_jobs[0], session=None)  # duplicate — ignored
    await asyncio.sleep(0.05)
    assert pushed == ["amazon_uk:NEW1"], pushed

    print("\nPIPELINE_OK — baseline, dedupe, filters and push dispatch all behave correctly")


test_telegram_parsing()
asyncio.run(main())
