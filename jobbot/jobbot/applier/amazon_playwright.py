from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from ..models import Job

log = logging.getLogger(__name__)

LOGIN_URL = "https://www.jobsatamazon.co.uk/app#/login"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Buttons that advance the application, tried in priority order each step.
STEP_LABELS = [
    "apply", "select this job", "select job", "create application",
    "next", "continue", "confirm", "submit", "agree and continue", "i agree",
]
SUCCESS_RE = re.compile(
    r"application (submitted|received|complete)|thank you for applying|"
    r"you('|’)ve applied|appointment (scheduled|confirmed)", re.I)
NEEDS_LOGIN_RE = re.compile(r"sign in|log in|create account|verify.*(pin|code)", re.I)


class AmazonApplier:
    """EXPERIMENTAL one-click apply on jobsatamazon.co.uk.

    Uses a persistent browser profile: log in ONCE with
    `python -m jobbot amazon-login` (Amazon sends a PIN to your email/phone —
    that step needs a human, which is why the session is then kept on disk).

    Afterwards, when a new Amazon job appears, this opens the job page in the
    logged-in profile and clicks through the shift-selection/apply steps.
    Amazon changes this flow regularly and may inject checks a bot can't pass,
    so every attempt is screenshotted and the Telegram alert always goes out
    too — worst case you finish the application by hand with a head start.
    """

    def __init__(self, profile_dir: str, headless: bool = True):
        self._profile_dir = Path(profile_dir)
        self._headless = headless
        self._pw = None
        self._ctx = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(self._profile_dir), headless=self._headless,
            user_agent=USER_AGENT, locale="en-GB",
        )

    async def close(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()
        self._ctx = self._pw = None

    async def apply(self, job: Job) -> tuple[bool, str]:
        if self._ctx is None:
            await self.start()
        t0 = time.monotonic()
        page = await self._ctx.new_page()
        try:
            await page.goto(job.url, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(2_500)

            for step in range(12):
                content = await page.content()
                if SUCCESS_RE.search(content):
                    return True, f"submitted in {time.monotonic() - t0:.1f}s ({step} steps)"
                if "app#/login" in page.url or NEEDS_LOGIN_RE.search(await self._visible_text(page)):
                    return False, "session not logged in — run `python -m jobbot amazon-login`"

                if not (await self._advance(page)):
                    break
                await page.wait_for_timeout(1_800)

            await self._screenshot(page, job)
            return False, "could not reach confirmation (see data/screenshots) — finish manually"
        except Exception as exc:
            await self._screenshot(page, job)
            return False, f"error: {exc}"
        finally:
            await page.close()

    async def _advance(self, page) -> bool:
        """Click the most apply-like actionable element visible right now."""
        for label in STEP_LABELS:
            loc = page.get_by_role("button", name=re.compile(rf"\b{re.escape(label)}\b", re.I)).first
            try:
                await loc.wait_for(state="visible", timeout=1_200)
                await loc.click()
                return True
            except Exception:
                pass
        # No button? Probably the schedule/shift list — pick the first card.
        for sel in ('[data-test-id*="schedule"] >> nth=0',
                    '[data-test-component="StencilReactCard"] >> nth=0',
                    'li[class*="schedule"] >> nth=0'):
            loc = page.locator(sel)
            try:
                await loc.wait_for(state="visible", timeout=1_200)
                await loc.click()
                return True
            except Exception:
                pass
        return False

    @staticmethod
    async def _visible_text(page) -> str:
        try:
            return (await page.inner_text("body"))[:4000]
        except Exception:
            return ""

    @staticmethod
    async def _screenshot(page, job: Job) -> None:
        try:
            out = Path("data/screenshots")
            out.mkdir(parents=True, exist_ok=True)
            path = out / f"amazon_{job.source_id}_{int(time.time())}.png"
            await page.screenshot(path=str(path))
            log.info("saved screenshot %s", path)
        except Exception:
            pass


async def login(profile_dir: str) -> None:
    """Open a visible browser so the user can log in once (PIN and all)."""
    from playwright.async_api import async_playwright

    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            profile_dir, headless=False, user_agent=USER_AGENT, locale="en-GB")
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print("A browser window is open. Log in to your Amazon jobs account")
        print("(email + the PIN they send you). When you can see your account/")
        print("profile page, simply CLOSE the browser window — the session is")
        print("saved automatically and the bot will reuse it.")
        try:
            await ctx.wait_for_event("close", timeout=0)
        except Exception:
            pass
    print(f"Session stored in {profile_dir}. Test it with: python -m jobbot run --apply")
