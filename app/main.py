from fastapi import Depends, FastAPI, HTTPException  # type: ignore[import-not-found]
from contextlib import asynccontextmanager
import logging
from app.auth import verify_api_key
from app.models import CookiesRequest, CookiesResponse, ScrapeRequest, ScrapeResponse, HealthResponse, ScraperType
from app.services.factory import ScraperFactory
from app.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting scraper service...")
    await ScraperFactory.initialize()
    yield
    # Shutdown
    logger.info("Shutting down scraper service...")
    await ScraperFactory.cleanup()


app = FastAPI(
    title="Web Scraper API",
    description="FastAPI service for web scraping with multiple bypass services",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        available_scrapers=ScraperFactory.get_available_scrapers(),
    )


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_url(request: ScrapeRequest, api_key: str = Depends(verify_api_key)):
    """Scrape a URL using specified scraper service"""
    try:
        scraper = ScraperFactory.get_scraper(request.scraper_type)

        result = await scraper.scrape(
            url=str(request.url),
            selector_to_wait_for=request.selector_to_wait_for,
            timeout=request.timeout or settings.DEFAULT_TIMEOUT,
            headless=request.headless,
            proxy_url=request.proxy_url if request.proxy_url else None,
            proxy_username=request.proxy_username if request.proxy_username else None,
            proxy_password=request.proxy_password if request.proxy_password else None,
            proxy_server=request.proxy_server if request.proxy_server else None,
            wait_until=request.wait_until,
            cookies=request.cookies,
        )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/cookies", response_model=CookiesResponse)
async def get_cookies(request: CookiesRequest, api_key: str = Depends(verify_api_key)):
    """Earn cookies in Camoufox through one proxy exit and say which exit it was."""
    try:
        scraper = ScraperFactory.get_scraper(ScraperType.CAMOUFOX)
        return await scraper.get_cookies(
            url=str(request.url),
            required_cookie=request.required_cookie,
            proxy_server=request.proxy_server or None,
            proxy_username=request.proxy_username or None,
            proxy_password=request.proxy_password or None,
            rotate_us_proxy=request.rotate_us_proxy,
            max_attempts=max(1, min(request.max_attempts, 10)),
            timeout_ms=request.timeout_ms,
        )
    except Exception as e:
        logger.error(f"/cookies failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/scrapers")
async def list_scrapers(api_key: str = Depends(verify_api_key)):
    """List available scraper services"""
    return {"available_scrapers": ScraperFactory.get_available_scrapers()}


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Web Scraper API is running"}


if __name__ == "__main__":
    import uvicorn  # type: ignore[import-not-found]

    uvicorn.run(
        "app.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=True
    )
