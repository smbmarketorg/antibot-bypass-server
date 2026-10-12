"""Browser slots: /cookies never waits behind /scrape, and nobody waits forever."""
import asyncio
import time

from app.services import camoufox_scraper as c


def test_busy_slot_fails_fast():
    async def run():
        sem = asyncio.Semaphore(1)
        await sem.acquire()
        t = time.monotonic()
        try:
            async with c.browser_slot(sem, 0.3):
                raise AssertionError("should not get a slot")
        except c.BrowserBusy:
            pass
        return time.monotonic() - t
    assert asyncio.run(run()) < 1.0


def test_cookies_lane_is_free_while_scrape_lane_is_full():
    async def run():
        for _ in range(2):
            await c.BROWSER_SEMAPHORE.acquire()
        try:
            async with c.browser_slot(c.COOKIES_SEMAPHORE, 0.5):
                return True
        finally:
            for _ in range(2):
                c.BROWSER_SEMAPHORE.release()
    assert asyncio.run(run())


def test_slot_is_released_after_use_and_on_error():
    async def run():
        sem = asyncio.Semaphore(1)
        async with c.browser_slot(sem, 1):
            pass
        try:
            async with c.browser_slot(sem, 1):
                raise ValueError("boom")
        except ValueError:
            pass
        async with c.browser_slot(sem, 0.2):
            return True
    assert asyncio.run(run())
