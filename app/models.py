from typing import Dict, List, Literal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, HttpUrl  # type: ignore[import-not-found]

from app.constants.app_data import AppData


class ScraperType(str, Enum):
    BRIGHTDATA_CDP = "brightdata_cdp"
    CAMOUFOX = "camoufox"


class ScrapeRequest(BaseModel):
    url: HttpUrl
    scraper_type: ScraperType = ScraperType.BRIGHTDATA_CDP
    selector_to_wait_for: Optional[str] = None
    timeout: Optional[int] = None
    headless: bool = True
    headers: Optional[Dict[str, str]] = None
    cookies: Optional[Dict[str, str]] = None
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    proxy_server: Optional[str] = None
    wait_until: Literal["domcontentloaded", "load", "networkidle", "commit"] = "networkidle"


class ScrapeResponse(BaseModel):
    success: bool
    html: Optional[str] = None
    error: Optional[str] = None
    content_length: Optional[int] = None
    execution_time: float
    scraper_used: ScraperType
    retries_attempted: int
    cookies: Optional[Dict[str, str]] = None  


class CookiesRequest(BaseModel):
    """Earn a site's anti-bot cookies in a real browser through a proxy exit.

    The response names the exit that earned them, so the caller can send its
    own requests through the SAME exit. Akamai ties cookies to the visitor, and
    on api.bizbuysell.com a cookie set is good for one protected API call.
    """
    url: HttpUrl
    # Cookie that must be present for the attempt to count (e.g. "_track_tkn").
    required_cookie: Optional[str] = None
    proxy_server: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    # Pick a random US exit (-us-N) per attempt. False = use proxy_username as-is.
    rotate_us_proxy: bool = True
    max_attempts: int = 4
    # Per attempt: page load plus the wait for required_cookie.
    timeout_ms: int = 45000


class CookiesResponse(BaseModel):
    success: bool
    cookies: Optional[Dict[str, str]] = None
    # The proxy username (exit) the cookies were earned through.
    proxy_username: Optional[str] = None
    user_agent: Optional[str] = None
    attempts: int = 0
    execution_time: float = 0.0
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str = AppData.app_version
    available_scrapers: List[str] = [ScraperType.BRIGHTDATA_CDP, ScraperType.CAMOUFOX]
