"""Exceptions used across the bridge.

Two families live here:

``UpstreamError`` and friends
    Raised by :mod:`app.upstream` when the target site cannot give us what we
    asked for. The politeness layer raises the "we gave up" variants; the
    parsers raise ``UpstreamChanged`` when the markup no longer matches.

``ApiError``
    Raised by :mod:`app.services` for caller mistakes. Carries one of the five
    allowed error codes so that the API layer never has to invent a new one.
"""

from __future__ import annotations

from typing import Final

BAD_REQUEST: Final = "BAD_REQUEST"
NOT_FOUND: Final = "NOT_FOUND"
RATE_LIMITED: Final = "RATE_LIMITED"
UPSTREAM_BLOCKED: Final = "UPSTREAM_BLOCKED"
UPSTREAM_CHANGED: Final = "UPSTREAM_CHANGED"

ERROR_STATUS: Final[dict[str, int]] = {
    BAD_REQUEST: 400,
    NOT_FOUND: 404,
    RATE_LIMITED: 429,
    UPSTREAM_BLOCKED: 502,
    UPSTREAM_CHANGED: 502,
}


class BridgeError(Exception):
    """Base class for every error this service raises deliberately."""


# --------------------------------------------------------------------------
# Upstream conditions
# --------------------------------------------------------------------------
class UpstreamError(BridgeError):
    """The target site could not be read, for a reason the caller cannot fix."""

    #: Whether an identical, identical retry could plausibly succeed.
    retryable: bool = True


class UpstreamNotFound(UpstreamError):
    """The requested page does not exist upstream (HTTP 404)."""

    retryable = False


class UpstreamBlocked(UpstreamError):
    """The site refused automated access: HTTP 403 or an interstitial/CAPTCHA.

    We never try to work around this; the caller is told to slow down or stop.
    """

    retryable = False


class UpstreamRateLimited(UpstreamError):
    """We are throttling ourselves or the site asked us to back off."""

    retryable = True


class UpstreamChanged(UpstreamError):
    """The page structure no longer matches what the parser expects.

    ``element`` names the selector or field that could not be found, so a
    maintainer can jump straight to the parser function that owns it.
    """

    retryable = False

    def __init__(self, element: str, message: str | None = None) -> None:
        self.element = element
        super().__init__(message or f"upstream page structure changed: {element} is missing")


# --------------------------------------------------------------------------
# Caller mistakes
# --------------------------------------------------------------------------
class ApiError(BridgeError):
    """A request we can reject without touching the target site."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        if code not in ERROR_STATUS:  # pragma: no cover - guards future edits
            raise ValueError(f"{code!r} is not an allowed error code")
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)

    @property
    def status_code(self) -> int:
        """HTTP status that pairs with :attr:`code`."""
        return ERROR_STATUS[self.code]


def bad_request(message: str) -> ApiError:
    """Shorthand for a 400 with a caller-facing explanation."""
    return ApiError(BAD_REQUEST, message, retryable=False)
