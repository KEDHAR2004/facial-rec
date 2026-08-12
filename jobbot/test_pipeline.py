"""Offline smoke test: mocks a job board and checks baseline, dedupe,
filtering and dispatch. Run: .venv/bin/python test_pipeline.py"""
import asyncio
import logging

from jobbot.config import ApplyConfig, Config, SearchConfig, SourceConfig
from jobbot.main import Bot
from jobbot.models import Job
from jobbot.sources.base import Source

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")


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

    print("\nPIPELINE_OK — baseline, dedupe and filters all behave correctly")


asyncio.run(main())
