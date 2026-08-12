from __future__ import annotations

import logging
import time
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..models import Job

log = logging.getLogger(__name__)

SIGNIN_URL = "https://www.reed.co.uk/account/signin"

# Reed's markup changes occasionally; each step tries a list of selectors in order.
APPLY_BUTTON_SELECTORS = [
    '[data-qa="applyButton"]',
    'button:has-text("Apply now")',
    'a:has-text("Apply now")',
    '#applyButton',
]
SUBMIT_BUTTON_SELECTORS = [
    '[data-qa="submitApplicationButton"]',
    'button:has-text("Submit application")',
    'button:has-text("Submit Application")',
    'button[type="submit"]:has-text("Submit")',
]


class ReedApplier:
    """One-click apply on reed.co.uk with a signed-in account.

    Prerequisite: complete your Reed profile ONCE by hand (upload CV, set your
    details) so that job pages show the one-click "Apply now" flow. The login
    session is persisted to `storage_state` so sign-in only happens when the
    session expires.
    """

    def __init__(self, email: str, password: str, storage_state: str,
                 headless: bool = True, cover_letter: str = ""):
        self._email = email
        self._password = password
        self._storage_state = Path(storage_state)
        self._headless = headless
        self._cover_letter = cover_letter
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)
        state = str(self._storage_state) if self._storage_state.exists() else None
        self._context = await self._browser.new_context(storage_state=state)

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def apply(self, job: Job) -> tuple[bool, str]:
        """Attempt a one-click apply. Returns (success, detail)."""
        assert self._context is not None, "call start() first"
        t0 = time.monotonic()
        page = await self._context.new_page()
        try:
            await page.goto(job.url, wait_until="domcontentloaded", timeout=30_000)

            if await self._needs_login(page):
                await self._login(page)
                await page.goto(job.url, wait_until="domcontentloaded", timeout=30_000)

            if not await self._click_first(page, APPLY_BUTTON_SELECTORS):
                return False, "no Apply button found (external application?)"

            # Optional cover-letter box on the confirmation step.
            if self._cover_letter:
                box = page.locator("textarea").first
                try:
                    await box.wait_for(state="visible", timeout=3_000)
                    await box.fill(self._cover_letter.format(
                        title=job.title, company=job.company, location=job.location))
                except Exception:
                    pass  # no cover-letter step for this job

            if await self._click_first(page, SUBMIT_BUTTON_SELECTORS, timeout_ms=8_000):
                elapsed = time.monotonic() - t0
                return True, f"submitted in {elapsed:.1f}s"

            # Some listings apply immediately on the first click.
            if await page.locator("text=/application (sent|submitted|complete)/i").count():
                elapsed = time.monotonic() - t0
                return True, f"submitted in {elapsed:.1f}s"

            await self._screenshot(page, job)
            return False, "apply clicked but no confirmation detected (see screenshot)"
        except Exception as exc:
            await self._screenshot(page, job)
            return False, f"error: {exc}"
        finally:
            await page.close()

    async def _needs_login(self, page: Page) -> bool:
        return await page.locator('a[href*="account/signin"], a:has-text("Sign in")').count() > 0

    async def _login(self, page: Page) -> None:
        log.info("Signing in to Reed as %s", self._email)
        await page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        await page.fill('input[type="email"], #signin_email', self._email)
        await page.fill('input[type="password"], #signin_password', self._password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle", timeout=20_000)
        self._storage_state.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(self._storage_state))

    @staticmethod
    async def _click_first(page: Page, selectors: list[str], timeout_ms: int = 5_000) -> bool:
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                await loc.wait_for(state="visible", timeout=timeout_ms)
                await loc.click()
                return True
            except Exception:
                continue
        return False

    @staticmethod
    async def _screenshot(page: Page, job: Job) -> None:
        try:
            out = Path("data/screenshots")
            out.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(out / f"{job.uid.replace(':', '_')}.png"))
        except Exception:
            pass
