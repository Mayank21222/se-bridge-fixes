"""The only code in this project that talks to the target site.

Responsibilities, in the order they apply to every request:

1. serve from the TTL cache when the exact URL was fetched recently;
2. refuse to call at all while the circuit breaker is open;
3. wait until at least ``1 / requests_per_second`` has passed since the last
   outbound call;
4. issue the request with a descriptive ``User-Agent`` and connect/read
   timeouts;
5. retry ``429`` and ``5xx`` with exponential backoff plus jitter, honouring
   ``Retry-After`` in both its seconds and HTTP-date forms;
6. give up on a ``403`` or a challenge page immediately - we report being
   blocked rather than trying to get around it.

Nothing here retries other ``4xx`` responses, and nothing here logs a response
body.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from app.config import Settings, get_settings
from app.errors import UpstreamBlocked, UpstreamError, UpstreamNotFound, UpstreamRateLimited

logger = logging.getLogger("app.upstream.client")

#: Bodies that mean "prove you are human". We detect them; we never solve them.
#: None of these strings occurs anywhere in the 12 recorded real pages, so
#: matching on them does not misfire on ordinary catalogue content; a marker
#: late in a document is still caught because the whole body is scanned.
_BLOCK_MARKERS = (
    "captcha",
    "are you a robot",
    "unusual traffic",
    "cf-browser-verification",
    "checking your browser",
)

_CACHE_MAX_ENTRIES = 512

#: Paths ``robots.txt`` disallows for ``User-agent: *``. Every page the bridge
#: reads contains a hidden link to ``/honeypot`` whose own text promises to ban
#: the requesting IP, so a parser bug or a careless URL build must not follow
#: it. The check lives here rather than in the URL builder: this is the last
#: point before a byte leaves the process, including a ``Location`` hop.
_DISALLOWED_PATHS = ("/honeypot",)

#: Path segments that address full text or file downloads. Named AI crawlers
#: are barred from ``/ebooks/*/text*`` and ``/ebooks/*/downloads/*``; this
#: client treats those rules as binding on itself too, and refuses the same
#: paths so a caller cannot reach them by putting ``text`` or ``downloads`` in
#: an ebook identifier.
_RESTRICTED_EBOOK_SEGMENTS = frozenset({"text", "downloads"})

_MAX_REDIRECTS = 10


class DisallowedPath(UpstreamBlocked):
    """Raised before any request when a URL is disallowed by ``robots.txt``.

    Subclasses :class:`UpstreamBlocked` so the API maps it to
    ``UPSTREAM_BLOCKED`` with ``retryable: false``, not to the retryable
    ``RATE_LIMITED`` catch-all for generic upstream errors.
    """


def _remove_dot_segments(path: str) -> str:
    """Collapse ``.`` and ``..`` the way RFC 3986 section 5.2.4 prescribes.

    This has to match what actually goes on the wire. ``httpx`` normalises dot
    segments while building the request, so ``/help/../honeypot`` leaves this
    process as ``/honeypot``. A guard that only inspected the string it was
    handed would therefore pass a URL whose *transmitted* path is the one we
    refuse, which is the exact outcome the guard exists to prevent.
    """
    out: list[str] = []
    for segment in path.split("/"):
        if segment == ".":
            continue
        if segment == "..":
            if out:
                out.pop()
            continue
        out.append(segment)
    joined = "/".join(out)
    # A leading empty segment is the root slash and must survive; trailing empty
    # segments come from repeated slashes and are dropped by the caller's rstrip.
    return joined if joined.startswith("/") else f"/{joined}"


def _normalised_path(url: str) -> str:
    """Return the request path as it will actually be transmitted.

    Percent-decoding, dot-segment removal, repeated-slash collapsing and
    case folding all happen here, so a caller cannot spell a forbidden path in a
    form the matcher fails to recognise. Decoding runs to a fixed point, because
    one round is not enough for a doubly-encoded segment.
    """
    path = urlsplit(url).path
    for _ in range(3):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    path = _remove_dot_segments(path)
    while "//" in path:
        path = path.replace("//", "/")
    return path.lower().rstrip("/") or "/"


def _is_disallowed(url: str) -> bool:
    """True when ``url`` targets a path this client is forbidden to request."""
    path = _normalised_path(url)
    if any(path == rule or path.startswith(f"{rule}/") for rule in _DISALLOWED_PATHS):
        return True
    parts = [segment for segment in path.split("/") if segment]
    if len(parts) >= 2 and parts[0] == "ebooks":
        return any(segment in _RESTRICTED_EBOOK_SEGMENTS for segment in parts[1:])
    return False


@dataclass(frozen=True, slots=True)
class FetchResult:
    """A successful upstream read, plus where and when it came from."""

    url: str
    text: str
    from_cache: bool
    fetched_at: datetime


class _RateLimiter:
    """Spaces outbound calls by at least ``min_interval`` seconds."""

    def __init__(
        self, min_interval: float, clock: Callable[[], float], sleeper: Callable[[float], None]
    ):
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.Lock()
        self._last_call: float | None = None

    def acquire(self) -> None:
        """Block until it is this caller's turn to hit the network."""
        with self._lock:
            now = self._clock()
            if self._last_call is not None:
                wait = self._min_interval - (now - self._last_call)
                if wait > 0:
                    self._sleep(wait)
            self._last_call = self._clock()


class _TTLCache:
    """A tiny in-process cache keyed by the full request URL."""

    def __init__(self, ttl: float, clock: Callable[[], float]):
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, str, datetime]] = {}

    def get(self, url: str) -> FetchResult | None:
        """Return the cached body for ``url``, or ``None`` when absent or stale."""
        if self._ttl <= 0:
            return None
        with self._lock:
            entry = self._entries.get(url)
            if entry is None:
                return None
            expires_at, text, fetched_at = entry
            if expires_at <= self._clock():
                del self._entries[url]
                return None
            return FetchResult(url=url, text=text, from_cache=True, fetched_at=fetched_at)

    def set(self, url: str, text: str, fetched_at: datetime) -> None:
        """Store ``text`` for ``url`` until the TTL expires."""
        if self._ttl <= 0:
            return
        with self._lock:
            if len(self._entries) >= _CACHE_MAX_ENTRIES:
                self._entries.pop(next(iter(self._entries)))
            self._entries[url] = (self._clock() + self._ttl, text, fetched_at)

    def clear(self) -> None:
        """Drop every entry. Used by tests and by the cache probe endpoint."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class _CircuitBreaker:
    """Opens after N consecutive failures; allows one trial after a cooldown."""

    def __init__(self, threshold: int, cooldown: float, wall_clock: Callable[[], float]):
        self._threshold = threshold
        self._cooldown = cooldown
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> str:
        """``closed``, ``open`` or ``half_open``."""
        with self._lock:
            if self._consecutive_failures < self._threshold:
                return "closed"
            opened_at = self._opened_at
            if opened_at is not None and self._wall_clock() - opened_at < self._cooldown:
                return "open"
            return "half_open"

    def before_call(self) -> None:
        """Raise if we must not call upstream right now."""
        with self._lock:
            if self._consecutive_failures < self._threshold:
                return
            opened_at = self._opened_at
            if opened_at is not None and self._wall_clock() - opened_at < self._cooldown:
                raise UpstreamRateLimited(
                    f"circuit breaker open after {self._consecutive_failures} consecutive "
                    f"upstream failures; not calling the site for another "
                    f"{self._cooldown - (self._wall_clock() - opened_at):.1f}s"
                )
            if self._trial_in_flight:
                raise UpstreamRateLimited(
                    "circuit breaker is half open and a trial request is already in flight"
                )
            self._trial_in_flight = True

    def on_success(self) -> None:
        """Record a successful call and close the breaker."""
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._trial_in_flight = False

    def on_failure(self) -> None:
        """Record a failed call, opening the breaker at the threshold."""
        with self._lock:
            self._consecutive_failures += 1
            self._opened_at = self._wall_clock()
            self._trial_in_flight = False
            if self._consecutive_failures == self._threshold:
                logger.warning(
                    "circuit breaker opened after %d consecutive upstream failures",
                    self._consecutive_failures,
                )

    def on_abort(self) -> None:
        """Clear an in-flight trial without counting a success or a failure.

        Used when we refuse to continue (a disallowed redirect target) after
        the breaker has already admitted the call.
        """
        with self._lock:
            self._trial_in_flight = False


class UpstreamClient:
    """A polite, caching, self-limiting HTTP client for the target site."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._settings = settings or get_settings()
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleeper
        self._random = random_source
        self._cache = _TTLCache(self._settings.cache_ttl_seconds, clock)
        self._limiter = _RateLimiter(self._settings.min_request_interval_seconds, clock, sleeper)
        self._breaker = _CircuitBreaker(
            self._settings.circuit_failure_threshold,
            self._settings.circuit_cooldown_seconds,
            wall_clock,
        )
        self._http = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(
                self._settings.read_timeout_seconds,
                connect=self._settings.connect_timeout_seconds,
            ),
            follow_redirects=False,
            headers={
                "User-Agent": self._settings.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
            },
        )

    # -- introspection ------------------------------------------------------
    @property
    def breaker_state(self) -> str:
        """Current circuit-breaker state, for the health endpoint."""
        return self._breaker.state

    @property
    def cache_size(self) -> int:
        """Number of live cache entries."""
        return len(self._cache)

    def clear_cache(self) -> None:
        """Empty the response cache."""
        self._cache.clear()

    # -- request path -------------------------------------------------------
    def get_html(self, url: str) -> FetchResult:
        """Fetch ``url``, honouring cache, rate limit, retries and the breaker.

        Returns:
            The body plus provenance. Raises :class:`~app.errors.UpstreamNotFound`,
            :class:`~app.errors.UpstreamBlocked`, :class:`~app.errors.UpstreamRateLimited`
            or :class:`~app.errors.UpstreamError` otherwise.

        Raises:
            DisallowedPath: if the URL is forbidden by the target's
                ``robots.txt``. Raised before any socket work, so a disallowed
                path can never cost the target a request.
        """
        if _is_disallowed(url):
            raise DisallowedPath(f"{_safe_url(url)} is disallowed by the target's robots.txt")

        cached = self._cache.get(url)
        if cached is not None:
            logger.debug("cache hit %s", _safe_url(url))
            return cached

        self._breaker.before_call()
        attempts = self._settings.max_attempts
        for attempt in range(1, attempts + 1):
            try:
                response = self._request_following_redirects(url)
            except UpstreamBlocked:
                self._breaker.on_abort()
                raise
            except UpstreamError:
                # A redirect loop or a Location-less redirect aborts without
                # counting as a failure, so it must release the half-open trial
                # slot here. Skipping this leaves the breaker permanently half
                # open, and every later caller is refused with "a trial request
                # is already in flight" even though nothing is in flight.
                self._breaker.on_abort()
                raise
            except httpx.HTTPError as exc:
                self._breaker.on_failure()
                if attempt < attempts:
                    delay = self._backoff(attempt)
                    logger.warning(
                        "upstream transport error on attempt %d/%d (%s); retrying in %.1fs",
                        attempt,
                        attempts,
                        type(exc).__name__,
                        delay,
                    )
                    self._sleep(delay)
                    continue
                raise UpstreamRateLimited(
                    f"could not reach the site after {attempts} attempts: {type(exc).__name__}"
                ) from exc

            status = response.status_code
            if status == 429 or status >= 500:
                self._breaker.on_failure()
                if attempt < attempts:
                    delay = self._retry_delay(response, attempt)
                    logger.warning(
                        "upstream returned %d on attempt %d/%d; retrying in %.1fs",
                        status,
                        attempt,
                        attempts,
                        delay,
                    )
                    self._sleep(delay)
                    continue
                raise UpstreamRateLimited(
                    f"the site kept answering {status} after {attempts} attempts"
                )

            if status == 403:
                self._breaker.on_failure()
                raise UpstreamBlocked(
                    f"the site answered 403 for {_safe_url(url)}; refusing automated access"
                )

            if status == 404:
                self._breaker.on_failure()
                raise UpstreamNotFound(f"no page at {_safe_url(url)}")

            if 400 <= status < 500:
                self._breaker.on_failure()
                raise UpstreamError(
                    f"the site answered {status} for {_safe_url(url)}; not retrying a client error"
                )

            text = response.text
            lowered = text.lower()
            if any(marker in lowered for marker in _BLOCK_MARKERS):
                self._breaker.on_failure()
                raise UpstreamBlocked(
                    f"the site served a challenge page for {_safe_url(url)}; "
                    "not attempting to pass it"
                )

            self._breaker.on_success()
            fetched_at = datetime.fromtimestamp(self._wall_clock(), tz=UTC)
            self._cache.set(url, text, fetched_at)
            logger.info("upstream %d %s", status, _safe_url(url))
            return FetchResult(url=url, text=text, from_cache=False, fetched_at=fetched_at)

        raise UpstreamRateLimited(  # pragma: no cover - loop always returns or raises
            "exhausted upstream attempts"
        )

    # -- helpers ------------------------------------------------------------
    def _request_following_redirects(self, url: str) -> httpx.Response:
        """GET ``url``, following same-host redirects under the same guards.

        Each hop is rate-limited and checked against the disallowed-path
        list *before* the request is sent, so a ``Location: /honeypot``
        cannot sneak past the guard that ``httpx`` auto-follow would skip.
        """
        current = url
        for _ in range(_MAX_REDIRECTS):
            if _is_disallowed(current):
                raise DisallowedPath(
                    f"{_safe_url(current)} is disallowed by the target's robots.txt"
                )
            self._limiter.acquire()
            response = self._http.get(current)
            if response.has_redirect_location:
                current = self._redirect_target(current, response)
                continue
            return response
        raise UpstreamError(f"too many redirects for {_safe_url(url)}")

    def _redirect_target(self, current_url: str, response: httpx.Response) -> str:
        """Resolve ``Location`` and refuse off-site hops."""
        location = response.headers.get("Location")
        if not location:
            raise UpstreamError(f"redirect from {_safe_url(current_url)} had no Location")
        nxt = urljoin(str(response.url), location)
        origin = urlsplit(current_url)
        dest = urlsplit(nxt)
        if dest.netloc and dest.netloc != origin.netloc:
            raise UpstreamBlocked(
                f"refusing off-site redirect from {_safe_url(current_url)} to {dest.netloc}"
            )
        return nxt

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff for attempt ``n`` with equal jitter."""
        raw = self._settings.backoff_base_seconds * (2 ** (attempt - 1))
        capped = min(raw, self._settings.backoff_max_seconds)
        return capped / 2 + self._random() * capped / 2

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        """Back off for at least ``Retry-After`` when the site sent one.

        The site's own instruction outranks our exponential backoff, because
        retrying sooner than a rate-limited site asked is the impolite choice.
        It is deliberately *not* truncated to ``backoff_max_seconds``: that
        setting governs how fast our own backoff grows, not what the site asked
        for, and clamping to it would silently retry under a rate limit.

        A ``Retry-After`` beyond ``max_retry_after_seconds`` means "come back
        much later". Rather than pin a worker for that long, or retry early, we
        give up and tell the caller when to return.
        """
        requested = self._parse_retry_after(response.headers.get("Retry-After"))
        if requested is None:
            return self._backoff(attempt)
        if requested > self._settings.max_retry_after_seconds:
            raise UpstreamRateLimited(
                f"the site asked to wait {requested:.0f}s, longer than the "
                f"{self._settings.max_retry_after_seconds:.0f}s this client will hold a "
                "request open; retry after that"
            )
        return max(self._backoff(attempt), requested)

    def _parse_retry_after(self, value: str | None) -> float | None:
        """Read ``Retry-After`` as seconds or as an HTTP date. ``None`` if absent."""
        if not value:
            return None
        raw = value.strip()
        if raw.isdigit():
            return float(raw)
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.fromtimestamp(self._wall_clock(), tz=UTC)).total_seconds())

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._http.close()

    def __enter__(self) -> UpstreamClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _safe_url(url: str) -> str:
    """Log URLs without their query string, which can contain user input."""
    return url.split("?", 1)[0]


_client: UpstreamClient | None = None
_client_lock = threading.Lock()


def get_client() -> UpstreamClient:
    """Return the process-wide client, so cache, limiter and breaker are shared."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = UpstreamClient(get_settings())
    return _client


def reset_client() -> None:
    """Drop the process-wide client. Used by tests."""
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
        _client = None
