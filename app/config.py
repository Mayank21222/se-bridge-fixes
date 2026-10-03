"""Environment-driven configuration.

Every knob the bridge uses is read from an environment variable named
``SE_BRIDGE_*``. Values are validated once, at import time of
:func:`get_settings`, so a typo in ``.env`` fails loudly on start-up instead of
producing a confusing failure on the first request.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="SE_BRIDGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Upstream target ---------------------------------------------------
    base_url: str = "https://standardebooks.org"

    # --- Politeness --------------------------------------------------------
    requests_per_second: float = Field(default=1.0, gt=0)
    cache_ttl_seconds: int = Field(default=300, ge=0)
    user_agent: str = "standard-ebooks-bridge/1.0 (+https://example.invalid/standard-ebooks-bridge)"

    # --- Timeouts and retries ----------------------------------------------
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    read_timeout_seconds: float = Field(default=15.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_base_seconds: float = Field(default=1.0, ge=0)
    backoff_max_seconds: float = Field(default=30.0, ge=0)
    max_retry_after_seconds: float = Field(
        default=300.0,
        gt=0,
        description=(
            "Longest Retry-After this client will sit out. Beyond it the request "
            "fails with RATE_LIMITED rather than sleeping or retrying early."
        ),
    )

    # --- Circuit breaker ---------------------------------------------------
    circuit_failure_threshold: int = Field(default=5, ge=1)
    circuit_cooldown_seconds: float = Field(default=60.0, gt=0)

    # --- API limits --------------------------------------------------------
    max_page_size: int = Field(default=48, ge=1)
    default_page_size: int = Field(default=12, ge=1)
    max_query_length: int = Field(default=200, ge=1)

    # --- Observability -----------------------------------------------------
    log_level: str = "INFO"

    @field_validator("base_url")
    @classmethod
    def _must_be_http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("SE_BRIDGE_BASE_URL must be an absolute http(s) URL")
        return value.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError(f"SE_BRIDGE_LOG_LEVEL must be a standard level, got {value!r}")
        return level

    @model_validator(mode="after")
    def _default_page_size_must_be_requestable(self) -> Settings:
        """Reject a default page size the API would then reject as too large.

        Without this, ``SE_BRIDGE_DEFAULT_PAGE_SIZE=100`` starts cleanly and then
        answers every unparameterised request with ``400``, because the ceiling
        is applied twice: once by the query-parameter bound and once by
        :meth:`page_size_ceiling`.
        """
        if self.default_page_size > self.max_page_size:
            raise ValueError(
                f"SE_BRIDGE_DEFAULT_PAGE_SIZE ({self.default_page_size}) cannot exceed "
                f"SE_BRIDGE_MAX_PAGE_SIZE ({self.max_page_size})"
            )
        return self

    @property
    def min_request_interval_seconds(self) -> float:
        """Minimum wall-clock gap between two outbound upstream requests."""
        return 1.0 / self.requests_per_second

    @property
    def page_size_ceiling(self) -> int:
        """Largest page size this API will ask the upstream site for."""
        return self.max_page_size


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, building them on first use."""
    return Settings()


def configure_logging(level: str | None = None) -> None:
    """Install a concise log format. Logs paths and statuses, never payloads."""
    logging.basicConfig(
        level=level or get_settings().log_level,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


def reset_settings() -> None:
    """Clear cached settings (useful for tests)."""
    get_settings.cache_clear()
