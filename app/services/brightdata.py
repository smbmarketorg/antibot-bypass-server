import asyncio
import logging
import random
import time
from typing import Optional, Tuple, Dict
from playwright.async_api import async_playwright, ViewportSize  # type: ignore[import-not-found]
from app.config import settings
from app.models import ScrapeResponse, ScraperType
from app.services.base import BaseScraper

logger = logging.getLogger(__name__)

BRIGHTDATA_SEMAPHORE = asyncio.Semaphore(50)

class BrightDataCDPScraper(BaseScraper):
    def __init__(self) -> None:
        self.cdp_endpoint = settings.BRIGHTDATA_CDP_ENDPOINT

    @property
    def name(self) -> ScraperType:
        return ScraperType.BRIGHTDATA_CDP

    async def initialize(self) -> None:
        # Playwright is started per-request inside _scrape_with_brightdata_cdp so the
        # driver subprocess never outlives a single scrape. A long-lived global instance
        # was observed to degrade after weeks of uptime and start returning
        # "connect_over_cdp: Timeout 180000ms" immediately on every call.
        logger.info("BrightData CDP scraper initialized (per-request Playwright lifecycle)")

    async def cleanup(self) -> None:
        logger.info("BrightData CDP scraper cleaned up")

    async def scrape(
        self,
        url: str,
        selector_to_wait_for: Optional[str] = None,
        timeout: int = 30000,
        headless: bool = True,
        proxy_url: Optional[str] = None,
        proxy_username: Optional[str] = None,
        proxy_password: Optional[str] = None,
        proxy_server: Optional[str] = None,
        wait_until: str = "networkidle",
        **kwargs,
    ) -> ScrapeResponse:
        start_time = time.time()
        retries = 0
        max_retries = 3

        for attempt in range(max_retries + 1):
            try:

                async with BRIGHTDATA_SEMAPHORE:
                    content, cookies = await self._scrape_with_brightdata_cdp(
                    url, selector_to_wait_for, timeout, headless, wait_until
                )

                execution_time = time.time() - start_time
                content_length = len(content) if content else 0

                # Validate content quality
                if content_length < 10000:
                    logger.warning(
                        f"Content too short ({content_length} chars) for {url}"
                    )
                    if attempt < max_retries:
                        retries += 1
                        await asyncio.sleep(2**attempt)  # Exponential backoff
                        continue

                return ScrapeResponse(
                    success=True,
                    html=content,
                    cookies=cookies,
                    content_length=content_length,
                    execution_time=execution_time,
                    scraper_used=self.name,
                    retries_attempted=retries,
                )

            except Exception as e:
                logger.error(
                    f"BrightData scrape attempt {attempt + 1} failed for {url}: {e}"
                )
                retries += 1

                if attempt < max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                else:
                    execution_time = time.time() - start_time
                    return ScrapeResponse(
                        success=False,
                        error=str(e),
                        execution_time=execution_time,
                        scraper_used=self.name,
                        retries_attempted=retries,
                    )

        # This shouldn't be reached, but just in case
        execution_time = time.time() - start_time
        return ScrapeResponse(
            success=False,
            error="Max retries exceeded",
            execution_time=execution_time,
            scraper_used=self.name,
            retries_attempted=retries,
        )

    async def _scrape_with_brightdata_cdp(
        self,
        url: str,
        selector_to_wait_for: Optional[str] = None,
        timeout: int = 30000,
        headless: bool = True,
        wait_until: str = "networkidle",
    ) -> Tuple[str, Dict[str, str]]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(self.cdp_endpoint)

            try:
                page = await browser.new_page()

                viewport_sizes = [
                    {"width": 1920, "height": 1080},  # Full HD
                    {"width": 1366, "height": 768},  # Laptop
                    {"width": 1440, "height": 900},  # MacBook
                    {"width": 1536, "height": 864},  # Windows laptop
                    {"width": 1280, "height": 720},  # HD
                    {"width": 1600, "height": 900},  # HD+
                ]

                viewport = random.choice(viewport_sizes)
                await page.set_viewport_size(
                    viewport_size=ViewportSize(
                        width=viewport["width"], height=viewport["height"]
                    )
                )
                logger.debug(
                    f"Set viewport size to viewport: {viewport['width']}x{viewport['height']}"
                )

                random_delay = random.uniform(3.0, 8.0)
                logger.debug(
                    f"Waiting for {random_delay} seconds before navigating to {url}"
                )
                await page.wait_for_timeout(random_delay * 1000)

                logger.info(f"Navigating to {url}")
                # await page.goto(url, timeout=timeout, wait_until="networkidle")
                print(f"logging wait_until: {wait_until}")
                await page.goto(url, timeout=timeout, wait_until=wait_until)
                await page.wait_for_timeout(5000)

                if selector_to_wait_for:
                    # Check for access denied BEFORE waiting for selector
                    page_title = await page.title()
                    if "access denied" in page_title.lower():
                        logger.warning(
                            f"⚠️ Access denied detected for {url} - skipping selector wait"
                        )
                        raise Exception(f"Access denied: {page_title}")

                    # Check content length - if too short, likely an error page
                    content = await page.content()
                    if len(content) < 2000:  # Most business pages are much longer
                        logger.warning(
                            f"⚠️ Page content too short ({len(content)} chars) - likely error page"
                        )
                        raise Exception(
                            f"Page content too short: {len(content)} characters"
                        )

                    # Now proceed with normal selector waiting
                    logger.info(f"Waiting for selector: {selector_to_wait_for}")

                    # Add comprehensive logging before waiting for selector
                    try:
                        # Log page title and URL
                        page_title = await page.title()
                        current_url = page.url
                        logger.info(
                            f"Page title: '{page_title}' | Current URL: {current_url}"
                        )

                        # Log page content length
                        content_before = await page.content()
                        logger.info(
                            f"Page content length before selector wait: {len(content_before)} characters"
                        )

                        # Log if selector exists in DOM (even if not visible)
                        selector_exists = await page.query_selector(selector_to_wait_for)
                        if selector_exists:
                            logger.info(
                                f"✅ Selector '{selector_to_wait_for}' found in DOM"
                            )
                            # Check if it's visible
                            is_visible = await selector_exists.is_visible()
                            logger.info(f"Selector visibility: {is_visible}")
                        else:
                            logger.warning(
                                f"❌ Selector '{selector_to_wait_for}' NOT found in DOM"
                            )

                            # Log alternative selectors that might exist
                            alternative_selectors = [
                                "h1",
                                ".title",
                                "[class*='title']",
                                "[class*='Title']",
                            ]
                            for alt_selector in alternative_selectors:
                                alt_element = await page.query_selector(alt_selector)
                                if alt_element:
                                    alt_text = await alt_element.text_content()
                                    logger.info(
                                        f"Alternative selector '{alt_selector}' found with text: '{alt_text[:100]}...'"
                                    )

                        # Log page HTML structure around where we expect the title
                        try:
                            # Look for any h1 elements
                            h1_elements = await page.query_selector_all("h1")
                            logger.info(f"Found {len(h1_elements)} h1 elements on page")
                            for i, h1 in enumerate(h1_elements):
                                h1_text = await h1.text_content()
                                h1_class = await h1.get_attribute("class")
                                logger.info(
                                    f"H1[{i}]: class='{h1_class}', text='{h1_text[:100]}...'"
                                )
                        except Exception as e:
                            logger.warning(f"Error checking h1 elements: {e}")

                        # Now wait for the selector with timeout
                        await page.wait_for_selector(selector_to_wait_for, timeout=timeout)
                        logger.info(
                            f"✅ Selector '{selector_to_wait_for}' successfully found and visible"
                        )

                    except Exception as e:
                        logger.error(
                            f"❌ Selector '{selector_to_wait_for}' timeout or error: {e}"
                        )

                        # Log final page state for debugging
                        try:
                            final_title = await page.title()
                            final_url = page.url
                            final_content = await page.content()

                            logger.error(f"=== PAGE STATE AT TIMEOUT ===")
                            logger.error(f"Final page title: '{final_title}'")
                            logger.error(f"Final URL: {final_url}")
                            logger.error(
                                f"Final content length: {len(final_content)} characters"
                            )

                            # Log first 1000 characters of content for debugging
                            content_preview = final_content[:1000]
                            logger.error(f"Content preview: {content_preview}")

                            # Check if page has any content at all
                            if len(final_content) < 1000:
                                logger.error(
                                    f"⚠️ Page content seems very short - possible loading issue"
                                )

                            # Log any error messages or challenge indicators
                            if "error" in final_content.lower():
                                logger.error("⚠️ Page contains error messages")
                            if "challenge" in final_content.lower():
                                logger.error("⚠️ Page contains challenge indicators")
                            if "access denied" in final_content.lower():
                                logger.error("⚠️ Page shows access denied")

                        except Exception as log_error:
                            logger.error(f"Error logging final page state: {log_error}")

                        raise e

                await page.wait_for_timeout(2000)

                await self._simulate_human_behavior(page, viewport)

                logger.info("Waiting for page to stabilize...")
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    logger.error("Network idle timeout - continuing anyway")

                await page.wait_for_timeout(3000)

                content = await page.content()

                # Handle anti-bot challenges
                if "chlgeId" in content or "challenge" in content.lower():
                    logger.info(f"Anti-bot challenge detected for {url}")
                    content = await self._handle_challenge(
                        page, selector_to_wait_for, timeout
                    )

                cookies_list = await page.context.cookies()
                cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies_list}

                content_length = len(content)
                logger.info(f"✅ Content length: {content_length} characters, cookies captured: {len(cookies_dict)}")

                return content, cookies_dict

            finally:
                await browser.close()
                logger.info("✅ Browser closed")

    async def _simulate_human_behavior(self, page, viewport):
        """Simulate human-like mouse movements and scrolling"""
        try:
            # Your existing human behavior simulation logic
            start_x, start_y = 400, 300
            num_points = random.randint(4, 8)
            points = []
            current_x, current_y = start_x, start_y

            for i in range(num_points):
                if i == 0:
                    x = current_x + random.randint(-100, 100)
                    y = current_y + random.randint(-80, 80)
                else:
                    max_jump = min(150, viewport["width"] // 6)
                    x = current_x + random.randint(-max_jump, max_jump)
                    y = current_y + random.randint(-max_jump, max_jump)

                x = max(50, min(viewport["width"] - 50, x))
                y = max(50, min(viewport["height"] - 50, y))
                points.append((x, y))
                current_x, current_y = x, y

            # Move through waypoints with realistic timing
            for i, (x, y) in enumerate(points):
                if i > 0:
                    prev_x, prev_y = points[i - 1]
                    distance = ((x - prev_x) ** 2 + (y - prev_y) ** 2) ** 0.5
                    speed = random.uniform(300, 700)
                    move_time = distance / speed * random.uniform(0.8, 1.2)
                else:
                    move_time = random.uniform(0.1, 0.3)

                await page.mouse.move(x, y)
                await page.wait_for_timeout(move_time * 1000)

                if random.random() < 0.3:
                    pause_time = random.uniform(0.2, 0.8)
                    await page.wait_for_timeout(pause_time * 1000)

            # Realistic scrolling
            if random.random() < 0.7:  # 70% chance to scroll
                await page.mouse.wheel(0, random.randint(-200, 200))
                await page.wait_for_timeout(random.uniform(200, 500))

            natural_pause = random.uniform(800, 2500)
            await page.wait_for_timeout(natural_pause)

        except Exception as e:
            logger.warning(f"Human behavior simulation failed: {e}")

    async def _handle_challenge(self, page, selector_to_wait_for, timeout) -> str:
        """Handle anti-bot challenges using staged waiting strategy"""
        logger.info("Using staged waiting strategy to resolve challenge...")

        for stage in range(3):
            logger.info(f"Challenge resolution stage {stage + 1}/3...")
            await page.wait_for_timeout(4000)

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                logger.info("Page still loading...")

            content = await page.content()

            challenge_gone = (
                "chlgeId" not in content and "challenge" not in content.lower()
            )
            title_element_found = False

            try:
                title_element = await page.query_selector(selector_to_wait_for)
                title_element_found = title_element is not None
                if title_element_found:
                    logger.info(
                        f"✅ Found {selector_to_wait_for} - page appears fully loaded!"
                    )
            except Exception:
                pass

            if challenge_gone or title_element_found:
                logger.info("✅ Challenge resolved!")
                break
            else:
                logger.info(f"Challenge still active after stage {stage + 1}")

        return await page.content()