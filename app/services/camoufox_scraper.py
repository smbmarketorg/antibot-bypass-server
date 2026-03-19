import asyncio
import logging
import random
import re
import time
from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Browser, Page, ViewportSize
from typing import Optional, Tuple, Dict
from app.models import ScraperType, ScrapeResponse
from app.services.base import BaseScraper

logger = logging.getLogger(__name__)

BROWSER_SEMAPHORE = asyncio.Semaphore(5)

# Akamai response size thresholds (based on observed data from LoopNet)
# ~230-507 chars = instant 403 "Access Denied" block (IP flagged)
# ~2500 chars = Akamai JS challenge page (needs time to resolve)
# >10000 chars = real page content
AKAMAI_BLOCK_THRESHOLD = 1500
AKAMAI_CHALLENGE_THRESHOLD = 5000
VALID_CONTENT_THRESHOLD = 10000

# Viewport options for randomization
VIEWPORT_SIZES = [
    (1920, 1080),  # Full HD
    (1366, 768),   # Laptop
    (1440, 900),   # MacBook
    (1536, 864),   # Windows laptop
    (1280, 720),   # HD
    (1600, 900),   # HD+
]


class CamoufoxScraper(BaseScraper):
    def __init__(self) -> None:
        pass

    @property
    def name(self) -> ScraperType:
        return ScraperType.CAMOUFOX

    async def initialize(self) -> None:
        logger.info("Camoufox Scraper initialized")

    async def cleanup(self) -> None:
        logger.info("Camoufox Scraper cleaned up")

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
        cookies: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> ScrapeResponse:
        """
        Scrape a URL with Camoufox, cycling through proxy IPs on Akamai blocks.

        Strategy:
        - Each attempt launches a new browser (= new proxy IP via -rotate)
        - Blocked IPs (~500 char response) are detected in ~3-5s and skipped immediately
        - JS challenges (~2500 chars) get up to 15s to resolve
        - Successful pages get full networkidle + human simulation treatment
        """
        start_time = time.time()
        max_ip_attempts = 10

        for attempt in range(max_ip_attempts):
            try:
                async with BROWSER_SEMAPHORE:
                    content, response_cookies, block_type = await self._scrape_with_camoufox(
                        url, selector_to_wait_for, timeout, headless,
                        proxy_url, proxy_username, proxy_password, proxy_server, cookies,
                    )

                content_length = len(content) if content else 0

                if content_length >= VALID_CONTENT_THRESHOLD:
                    execution_time = time.time() - start_time
                    logger.info(
                        f"[SUCCESS] {url} on attempt {attempt + 1}/{max_ip_attempts} "
                        f"({content_length} chars, {execution_time:.1f}s)"
                    )
                    return ScrapeResponse(
                        success=True,
                        html=content,
                        cookies=response_cookies,
                        content_length=content_length,
                        execution_time=execution_time,
                        scraper_used=self.name,
                        retries_attempted=attempt,
                    )

                # Handle different failure types
                if block_type == "ip_blocked":
                    logger.warning(
                        f"[IP BLOCKED] Attempt {attempt + 1}/{max_ip_attempts} for {url} "
                        f"({content_length} chars) — rotating IP..."
                    )
                    # No delay — just grab a new IP immediately
                    continue
                elif block_type == "challenge_failed":
                    logger.warning(
                        f"[CHALLENGE FAILED] Attempt {attempt + 1}/{max_ip_attempts} for {url} "
                        f"({content_length} chars)"
                    )
                    await asyncio.sleep(1)
                    continue
                else:
                    logger.warning(
                        f"[SHORT RESPONSE] Attempt {attempt + 1}/{max_ip_attempts} for {url} "
                        f"({content_length} chars)"
                    )
                    if content:
                        logger.warning(f"[DEBUG HTML PREVIEW] {content[:2000]}")
                    continue

            except Exception as e:
                logger.error(
                    f"[ERROR] Attempt {attempt + 1}/{max_ip_attempts} for {url}: {e}"
                )
                continue

        execution_time = time.time() - start_time
        logger.warning(f"[ALL ATTEMPTS FAILED] {url} after {max_ip_attempts} IP attempts ({execution_time:.1f}s)")
        return ScrapeResponse(
            success=False,
            error=f"All {max_ip_attempts} IP attempts failed",
            execution_time=execution_time,
            scraper_used=self.name,
            retries_attempted=max_ip_attempts,
        )

    async def _scrape_with_camoufox(
        self,
        url: str,
        selector_to_wait_for: Optional[str] = None,
        timeout: int = 30000,
        headless: bool = True,
        proxy_url: Optional[str] = None,
        proxy_username: Optional[str] = None,
        proxy_password: Optional[str] = None,
        proxy_server: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, Dict[str, str], str]:
        """
        Single scrape attempt with Camoufox. Returns (content, cookies, block_type).

        block_type values:
        - "ip_blocked": Akamai 403 block (~500 chars), IP is flagged
        - "challenge_failed": JS challenge page that didn't resolve (~2500 chars)
        - "success": Got valid content (>10k chars)
        """
        if proxy_server and proxy_username and proxy_password:
            proxy = {
                "server": proxy_server,
                "username": proxy_username,
                "password": proxy_password,
            }
            geoip = True
        else:
            proxy = None
            geoip = False

        async with AsyncCamoufox(
            headless=headless,
            proxy=proxy,
            geoip=geoip,
        ) as browser:
            page: Page = await browser.new_page()

            try:
                # Inject cookies if provided
                if cookies:
                    formatted_cookies = [
                        {'name': name, 'value': value, 'url': url}
                        for name, value in cookies.items()
                    ]
                    await page.context.add_cookies(formatted_cookies)

                # Block images, media, fonts — but NOT stylesheets
                # Akamai's sensor monitors CSS loading; blocking it is a detection signal
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in ["image", "media", "font"]
                    else route.continue_()
                )

                # Randomize viewport
                vp_w, vp_h = random.choice(VIEWPORT_SIZES)
                await page.set_viewport_size(
                    viewport_size=ViewportSize(width=vp_w, height=vp_h)
                )

                # Stealth: hide webdriver flag
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined,
                    });
                """)

                # --- PHASE 1: Fast initial load ---
                # Use domcontentloaded (not networkidle) for speed.
                # We check content immediately to detect Akamai blocks fast.
                try:
                    await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                except Exception as e:
                    logger.warning(f"Navigation failed for {url}: {e}")
                    return "", {}, "ip_blocked"

                # Brief wait for initial JavaScript execution
                await page.wait_for_timeout(2000)

                # --- PHASE 2: Quick Akamai block detection ---
                content = await page.content()
                content_length = len(content)

                if content_length < AKAMAI_BLOCK_THRESHOLD:
                    # Instant Akamai 403 "Access Denied" — ~230-507 chars
                    # This IP is flagged, no point waiting. Fail fast.
                    title = self._extract_title(content)
                    logger.warning(
                        f"[BLOCK DETECTED] {url} — {content_length} chars, "
                        f"title='{title}'"
                    )
                    return content, {}, "ip_blocked"

                # --- PHASE 3: JS challenge detection and resolution ---
                if content_length < AKAMAI_CHALLENGE_THRESHOLD:
                    # Akamai JS challenge page — ~2500 chars
                    # Contains JavaScript that needs to execute to generate _abck cookie
                    logger.info(
                        f"[CHALLENGE DETECTED] {url} ({content_length} chars) "
                        f"— waiting for Akamai JS to resolve..."
                    )
                    content = await self._handle_akamai_challenge(page, url)
                    content_length = len(content)

                    if content_length < VALID_CONTENT_THRESHOLD:
                        cookies_dict = await self._get_cookies(page)
                        return content, cookies_dict, "challenge_failed"

                # --- PHASE 4: Full page load (we got past Akamai!) ---
                # Now wait for networkidle since real content is loading
                try:
                    await page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    logger.warning(f"networkidle timeout for {url} — continuing anyway")

                # Wait for specific selector if provided
                if selector_to_wait_for:
                    try:
                        await page.wait_for_selector(selector_to_wait_for, timeout=15000)
                        logger.info(f"Found selector: {selector_to_wait_for}")
                    except Exception:
                        logger.warning(f"Selector {selector_to_wait_for} not found for {url}")

                # Simulate human behavior (only for real pages, not block pages)
                await self._simulate_human_behavior(page)

                # Get final content and cookies
                content = await page.content()
                cookies_dict = await self._get_cookies(page)
                final_url = page.url
                content_length = len(content)

                if final_url != url:
                    logger.info(f"[REDIRECT] {url} -> {final_url}")

                logger.info(
                    f"Retrieved {content_length} chars from {url}. "
                    f"Cookies: {len(cookies_dict)}"
                )

                # Log Akamai cookie state on success for analysis
                if content_length >= VALID_CONTENT_THRESHOLD:
                    has_abck = '_abck' in cookies_dict
                    has_bm_sz = 'bm_sz' in cookies_dict
                    logger.info(
                        f"[AKAMAI COOKIES] _abck={has_abck}, bm_sz={has_bm_sz}, "
                        f"total_cookies={len(cookies_dict)}"
                    )

                block_type = "success" if content_length >= VALID_CONTENT_THRESHOLD else "challenge_failed"
                return content, cookies_dict, block_type

            finally:
                if page:
                    await page.close()

    async def _handle_akamai_challenge(self, page: Page, url: str) -> str:
        """
        Handle Akamai JS challenge by waiting for the browser to execute
        the challenge script, generate the _abck cookie, and reload/redirect.

        Tries up to 5 stages with 3s waits between each.
        """
        for stage in range(5):
            await page.wait_for_timeout(3000)

            # Check if page has navigated or reloaded
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass

            content = await page.content()
            content_length = len(content)

            if content_length >= VALID_CONTENT_THRESHOLD:
                logger.info(
                    f"[CHALLENGE RESOLVED] Stage {stage + 1}/5 for {url} "
                    f"({content_length} chars)"
                )
                return content

            # Check if _abck cookie has been set (Akamai validation progressing)
            cookies = await self._get_cookies(page)
            has_abck = '_abck' in cookies
            logger.info(
                f"[CHALLENGE PENDING] Stage {stage + 1}/5 for {url} "
                f"({content_length} chars, _abck={has_abck})"
            )

        # Final attempt — try networkidle to catch late-loading content
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        return await page.content()

    async def _get_cookies(self, page: Page) -> Dict[str, str]:
        """Extract cookies from page context."""
        try:
            cookies_list = await page.context.cookies()
            return {cookie['name']: cookie['value'] for cookie in cookies_list}
        except Exception:
            return {}

    def _extract_title(self, html: str) -> str:
        """Extract <title> from HTML for debug logging."""
        try:
            match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
            return match.group(1).strip() if match else "NO_TITLE_FOUND"
        except Exception:
            return "TITLE_EXTRACTION_ERROR"

    async def _simulate_human_behavior(self, page: Page) -> None:
        """Simulate human-like mouse movements and scrolling."""
        try:
            await page.wait_for_timeout(random.randint(1000, 3000))
            await page.mouse.move(random.randint(100, 800), random.randint(100, 600))
            if random.random() < 0.7:
                await page.mouse.wheel(0, random.randint(-200, 200))
                await page.wait_for_timeout(random.randint(500, 1500))
        except Exception as e:
            logger.warning(f"Human behavior simulation failed: {e}")
