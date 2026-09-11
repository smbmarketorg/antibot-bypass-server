import os
from pydantic import field_validator  # type: ignore[import-not-found]
from pydantic_settings import BaseSettings  # type: ignore[import-not-found]


class Settings(BaseSettings):
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_DEBUG: bool = False

    BRIGHTDATA_CDP_ENDPOINT: str = ""

    DEFAULT_TIMEOUT: int = 30000
    MAX_RETRIES: int = 3

    # BrightData applies a per-account adaptive rate limit on browser session
    # opens ("bucket_rate_limit"). Measured 2026-09-11: a SINGLE client hit it
    # on 2 of 3 attempts, so 50 concurrent opens kept the bucket permanently
    # drained and BizBuySell discovery returned nothing for a week. Waiting
    # ~90s cleared it and the very next fetch returned a full 800KB page with
    # _track_tkn, so the ceiling is on session opens, not on our IPs.
    BRIGHTDATA_MAX_CONCURRENCY: int = int(os.getenv("BRIGHTDATA_MAX_CONCURRENCY", "5"))
    # Backoff floor specifically for rate-limit errors. The generic 2**attempt
    # ladder (1/2/4s) is far too short for a token bucket and just re-drains it.
    BRIGHTDATA_RATE_LIMIT_BACKOFF_S: float = float(
        os.getenv("BRIGHTDATA_RATE_LIMIT_BACKOFF_S", "45")
    )
    # Bodies below this are Akamai deny pages (~370-525 bytes measured), never
    # real content. Returning them as success is what made a 4-day outage look
    # healthy to the scraper.
    BRIGHTDATA_MIN_VALID_BYTES: int = int(os.getenv("BRIGHTDATA_MIN_VALID_BYTES", "1500"))

    # auth
    API_KEY: str = ""
    ENABLE_AUTH: bool = os.getenv("ENABLE_AUTH", "false").lower() == "true"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @field_validator("BRIGHTDATA_CDP_ENDPOINT")
    def validate_brightdata_cdp_endpoint(cls, v: str) -> str:
        if not v or v == "":
            raise ValueError("BRIGHTDATA_CDP_ENDPOINT is required")
        if not (v.startswith("https://") or v.startswith("wss://")):
            raise ValueError(
                "BRIGHTDATA_CDP_ENDPOINT must start with https:// or wss://"
            )
        return v


settings = Settings()
