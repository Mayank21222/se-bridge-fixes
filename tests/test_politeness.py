"""Politeness and resilience tests for the upstream client.

All timing is virtual: the tests inject a fake monotonic clock, a fake wall
clock and a recording sleeper, so cache expiry, retry backoff and rate spacing
are asserted exactly and instantly.
"""

from __future__ import annotations

import email.utils
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.errors import (
    UpstreamBlocked,
    UpstreamError,
    UpstreamNotFound,
    UpstreamRateLimited,
)
from app.upstream.client import DisallowedPath, UpstreamClient
from tests.conftest import (
    FIXTURES,
    FakeClock,
    FakeTransport,
    RecordingSleeper,
    fixture_html,
    script,
)

URL = "https://standardebooks.org/ebooks?view=list&per-page=12&page=1"
BODY = fixture_html("catalog_page_1")

AnyFactory = Callable[..., Any]


# ------------------------------------------------------------------ the cache
def test_second_identical_request_is_served_from_cache(
    make_client: AnyFactory, transport: FakeTransport, clock: FakeClock
) -> None:
    client = make_client([script(200, BODY)])
    first = client.get_html(URL)
    second = client.get_html(URL)
    assert first.from_cache is False
    assert second.from_cache is True
    assert len(transport.requests) == 1, "the second call must not touch the network"


def test_cache_entry_expires_after_the_ttl(
    make_client: AnyFactory, transport: FakeTransport, clock: FakeClock
) -> None:
    client = make_client([script(200, BODY)])
    client.get_html(URL)
    clock.advance(299)
    assert client.get_html(URL).from_cache is True
    assert len(transport.requests) == 1

    clock.advance(2)  # now 301s old, past the 300s TTL
    assert client.get_html(URL).from_cache is False
    assert len(transport.requests) == 2


def test_different_urls_do_not_share_a_cache_entry(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    client = make_client([script(200, BODY)])
    client.get_html(URL)
    client.get_html(f"{URL}&page=2")
    assert len(transport.requests) == 2


def test_a_zero_ttl_disables_caching(make_client: AnyFactory, settings: Settings) -> None:
    client = make_client(
        [script(200, BODY)], client_settings=settings.model_copy(update={"cache_ttl_seconds": 0})
    )
    assert client.get_html(URL).from_cache is False
    assert client.get_html(URL).from_cache is False


def test_cache_can_be_cleared(make_client: AnyFactory, transport: FakeTransport) -> None:
    client = make_client([script(200, BODY)])
    client.get_html(URL)
    assert client.cache_size == 1
    client.clear_cache()
    assert client.cache_size == 0
    client.get_html(URL)
    assert len(transport.requests) == 2


def test_cache_is_bounded_so_it_cannot_grow_without_limit(
    make_client: AnyFactory, settings: Settings
) -> None:
    client = make_client([script(200, BODY)])
    for page in range(1, 600):
        client.get_html(f"{URL}&page={page}")
    assert client.cache_size <= 512


def test_cached_response_keeps_its_original_timestamp(
    make_client: AnyFactory, clock: FakeClock
) -> None:
    client = make_client([script(200, BODY)])
    first = client.get_html(URL)
    clock.advance(10)
    second = client.get_html(URL)
    assert second.fetched_at == first.fetched_at


# --------------------------------------------------------------- rate limiting
def test_calls_are_spaced_by_at_least_the_minimum_interval(
    settings: Settings,
    transport: FakeTransport,
    clock: FakeClock,
    sleeper: RecordingSleeper,
) -> None:
    slow = settings.model_copy(update={"requests_per_second": 1.0})
    client = UpstreamClient(
        slow,
        transport=transport,
        clock=clock.monotonic,
        wall_clock=clock.wall_clock,
        sleeper=sleeper,
    )
    transport.queue = [script(200, BODY)]
    for page in (1, 2, 3):
        client.get_html(f"{URL}&page={page}")

    # The first call never waits; each later one waits exactly one interval.
    assert transport.gaps == [1.0, 1.0]
    assert sleeper.calls == [1.0, 1.0]


def test_no_wait_when_enough_time_has_already_passed(
    settings: Settings,
    transport: FakeTransport,
    clock: FakeClock,
    sleeper: RecordingSleeper,
) -> None:
    slow = settings.model_copy(update={"requests_per_second": 1.0})
    client = UpstreamClient(
        slow,
        transport=transport,
        clock=clock.monotonic,
        wall_clock=clock.wall_clock,
        sleeper=sleeper,
    )
    transport.queue = [script(200, BODY)]
    client.get_html(f"{URL}&page=1")
    clock.advance(5)
    client.get_html(f"{URL}&page=2")
    assert sleeper.calls == [], "five seconds idle is enough, so no waiting"
    assert transport.gaps == [5.0]


# --------------------------------------------------------------------- retries
def test_transient_5xx_is_retried_and_then_succeeds(
    make_client: AnyFactory, transport: FakeTransport, sleeper: RecordingSleeper
) -> None:
    client = make_client([script(503), script(502), script(200, BODY)])
    result = client.get_html(URL)
    assert result.from_cache is False
    assert len(transport.requests) == 3
    # Equal jitter with random()=0.5 halves to 75% of the nominal delay:
    # 1.0 and 2.0 seconds nominal become 0.75 and 1.5.
    assert sleeper.calls == [0.75, 1.5]


def test_persistent_5xx_gives_up_and_reports_rate_limited(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    client = make_client([script(500)])
    with pytest.raises(UpstreamRateLimited) as caught:
        client.get_html(URL)
    assert "500" in str(caught.value)
    assert len(transport.requests) == 3, "must stop at max_attempts"


def test_429_is_retried(make_client: AnyFactory, transport: FakeTransport) -> None:
    client = make_client([script(429), script(200, BODY)])
    assert client.get_html(URL).text == BODY
    assert len(transport.requests) == 2


def test_retry_after_seconds_is_honoured(
    make_client: AnyFactory, sleeper: RecordingSleeper
) -> None:
    client = make_client([script(429, headers={"Retry-After": "7"}), script(200, BODY)])
    client.get_html(URL)
    assert sleeper.calls == [7.0], "must wait at least the requested 7 seconds"


def test_retry_after_http_date_is_honoured(
    make_client: AnyFactory, clock: FakeClock, sleeper: RecordingSleeper
) -> None:
    when = email.utils.formatdate(clock.wall_now + 12, usegmt=True)
    client = make_client([script(429, headers={"Retry-After": when}), script(200, BODY)])
    client.get_html(URL)
    assert sleeper.calls == [12.0]


def test_retry_after_in_the_past_does_not_produce_a_negative_wait(
    make_client: AnyFactory, clock: FakeClock, sleeper: RecordingSleeper
) -> None:
    when = email.utils.formatdate(clock.wall_now - 60, usegmt=True)
    client = make_client([script(429, headers={"Retry-After": when}), script(200, BODY)])
    client.get_html(URL)
    assert sleeper.calls == [0.75], "falls back to plain backoff, and never waits negative"


def test_backoff_is_capped(make_client: AnyFactory, sleeper: RecordingSleeper) -> None:
    client = make_client(
        [script(500)], client_settings=Settings(max_attempts=5, backoff_max_seconds=3.0)
    )
    with pytest.raises(UpstreamRateLimited):
        client.get_html(URL)
    assert max(sleeper.calls) <= 3.0


def test_timeout_is_retried_then_reported(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    client = make_client([script(raises=httpx.ReadTimeout("timed out")), script(200, BODY)])
    assert client.get_html(URL).text == BODY
    assert len(transport.requests) == 2


def test_exhausted_timeouts_report_rate_limited(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    client = make_client([script(raises=httpx.ConnectError("refused"))])
    with pytest.raises(UpstreamRateLimited) as caught:
        client.get_html(URL)
    assert "ConnectError" in str(caught.value)


def test_a_single_attempt_setting_disables_retries(transport: FakeTransport) -> None:
    client = UpstreamClient(
        Settings(max_attempts=1),
        transport=transport,
        sleeper=lambda _s: None,
    )
    transport.queue = [script(503), script(200, BODY)]
    with pytest.raises(UpstreamRateLimited):
        client.get_html(URL)
    assert len(transport.requests) == 1


# ------------------------------------------------------------ robots.txt guard
def test_a_robots_disallowed_path_is_never_requested(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    """/honeypot promises to ban the requesting IP, so no request may be made.

    This guard exists because the target links to that path from every single
    page the bridge parses. Relying on the URL builders never producing it would
    be one careless route away from banning the client outright.
    """
    client = make_client([script(200, BODY)])
    with pytest.raises(DisallowedPath):
        client.get_html("https://standardebooks.org/honeypot")
    assert transport.requests == [], "a disallowed path must cost the target nothing"


def test_the_disallowed_guard_covers_trailing_slash_and_nesting(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    """The guard matches the path, not one literal string, so aliases are caught."""
    client = make_client([script(200, BODY)])
    for suffix in ("/honeypot/", "/honeypot/extra", "/honeypot?x=1"):
        with pytest.raises(DisallowedPath):
            client.get_html(f"https://standardebooks.org{suffix}")
    assert transport.requests == []


def test_a_permitted_path_is_not_mistaken_for_a_disallowed_one(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    """Prefix lookalikes of /honeypot, and ordinary catalogue paths, still go out."""
    client = make_client([script(200, BODY)])
    client.get_html("https://standardebooks.org/honeypots")
    client.get_html("https://standardebooks.org/ebooks?view=list")
    assert len(transport.requests) == 2


def test_disallowed_guard_is_case_insensitive_and_handles_percent_encoding(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    """Case variations and percent-encoding cannot bypass the disallowed guard."""
    client = make_client([script(200, BODY)])
    for path in (
        "https://standardebooks.org/Honeypot",
        "https://standardebooks.org/HONEYPOT/",
        "https://standardebooks.org/%68oneypot",
        "https://standardebooks.org/ebooks/author/title/TEXT",
        "https://standardebooks.org/ebooks/author/title/DOWNLOADS/file.epub",
    ):
        with pytest.raises(DisallowedPath):
            client.get_html(path)
    assert transport.requests == []


def test_full_text_and_download_paths_are_never_requested(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    """Named crawlers are barred from these trees; this client is too."""
    client = make_client([script(200, BODY)])
    for suffix in (
        "/ebooks/edwin-a-abbott/flatland/text",
        "/ebooks/edwin-a-abbott/flatland/text/single-page",
        "/ebooks/edwin-a-abbott/flatland/downloads",
        "/ebooks/edwin-a-abbott/flatland/downloads/edwin-a-abbott_flatland.epub",
        "/ebooks/dorothy-m-richardson/downloads",
    ):
        with pytest.raises(DisallowedPath):
            client.get_html(f"https://standardebooks.org{suffix}")
    assert transport.requests == []


def test_a_redirect_to_a_disallowed_path_is_not_followed(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    """httpx auto-follow would skip the guard; hops are therefore inspected."""
    client = make_client(
        [
            script(302, headers={"Location": "/honeypot"}),
            script(200, BODY),
        ]
    )
    with pytest.raises(DisallowedPath):
        client.get_html(URL)
    assert [str(request.url.path) for request in transport.requests] == ["/ebooks"], (
        "the honeypot hop must never be requested"
    )


def test_same_host_redirects_are_followed_and_rate_limited(
    settings: Settings,
    transport: FakeTransport,
    clock: FakeClock,
    sleeper: RecordingSleeper,
) -> None:
    """A 302 is another outbound call, so it waits its turn like any other."""
    slow = settings.model_copy(update={"requests_per_second": 1.0})
    client = UpstreamClient(
        slow,
        transport=transport,
        clock=clock.monotonic,
        wall_clock=clock.wall_clock,
        sleeper=sleeper,
    )
    transport.queue = [
        script(302, headers={"Location": "/ebooks?view=list&page=2"}),
        script(200, BODY),
    ]
    result = client.get_html("https://standardebooks.org/ebooks?view=list")
    assert result.text == BODY
    assert len(transport.requests) == 2
    assert sleeper.calls == [1.0]


def test_disallowed_path_is_upstream_blocked_not_rate_limited() -> None:
    """A robots.txt refusal must not look retryable to an API caller."""
    from app.services.catalog import error_code_for

    code, _message, retryable = error_code_for(
        DisallowedPath("https://standardebooks.org/honeypot is disallowed")
    )
    assert code == "UPSTREAM_BLOCKED"
    assert retryable is False


# ----------------------------------------------------------------- not retried
def test_403_is_not_retried(make_client: AnyFactory, transport: FakeTransport) -> None:
    client = make_client([script(403)])
    with pytest.raises(UpstreamBlocked):
        client.get_html(URL)
    assert len(transport.requests) == 1, "a refusal must not be hammered"


def test_challenge_page_is_detected_and_not_worked_around(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    client = make_client(
        [script(200, "<html><body>Are you a robot? Checking your browser...</body></html>")]
    )
    with pytest.raises(UpstreamBlocked) as caught:
        client.get_html(URL)
    assert "challenge" in str(caught.value)
    assert len(transport.requests) == 1


def test_a_marker_anywhere_in_the_body_is_detected(make_client: AnyFactory) -> None:
    """The whole body is scanned, not just its head, so late markers count."""
    body = BODY + "\n<p>Are you a robot?</p>"
    client = make_client([script(200, body)])
    with pytest.raises(UpstreamBlocked):
        client.get_html(URL)


def test_captcha_page_is_detected(make_client: AnyFactory) -> None:
    client = make_client([script(200, "<html>Enter the captcha to continue</html>")])
    with pytest.raises(UpstreamBlocked):
        client.get_html(URL)


def test_404_is_not_retried_and_is_not_retryable(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    client = make_client([script(404)])
    with pytest.raises(UpstreamNotFound) as caught:
        client.get_html(URL)
    assert caught.value.retryable is False
    assert len(transport.requests) == 1


def test_other_4xx_is_reported_without_retrying(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    client = make_client([script(400)])
    with pytest.raises(UpstreamError):
        client.get_html(URL)
    assert len(transport.requests) == 1


def test_real_pages_contain_no_block_marker_so_detection_cannot_misfire() -> None:
    """None of the 12 recorded pages trips the detector (see test_parsers)."""
    from app.upstream.client import _BLOCK_MARKERS

    for path in sorted(FIXTURES.glob("*.html")):
        lowered = path.read_text(encoding="utf-8").lower()
        for marker in _BLOCK_MARKERS:
            assert marker not in lowered, f"{path.name} contains block marker {marker!r}"


# -------------------------------------------------------------- the breaker
def test_breaker_opens_after_the_threshold_and_blocks_further_calls(
    make_client: AnyFactory, transport: FakeTransport
) -> None:
    client = make_client(
        [script(500)], client_settings=Settings(max_attempts=1, circuit_failure_threshold=3)
    )
    for _ in range(3):
        with pytest.raises(UpstreamRateLimited):
            client.get_html(f"{URL}&page=1")
    calls_before = len(transport.requests)

    with pytest.raises(UpstreamRateLimited) as caught:
        client.get_html(f"{URL}&page=1")
    assert "circuit breaker open" in str(caught.value)
    assert len(transport.requests) == calls_before, "no call leaves while open"


def test_breaker_closes_again_after_a_success(make_client: AnyFactory) -> None:
    client = make_client(
        [script(500), script(200, BODY)],
        client_settings=Settings(max_attempts=1, circuit_failure_threshold=2),
    )
    with pytest.raises(UpstreamRateLimited):
        client.get_html(f"{URL}&page=1")
    assert client.breaker_state == "closed", "one failure is below the threshold of two"
    assert client.get_html(f"{URL}&page=2").text == BODY
    assert client.breaker_state == "closed"


def test_breaker_opens_on_the_threshold_failure(make_client: AnyFactory) -> None:
    client = make_client(
        [script(500), script(200, BODY)],
        client_settings=Settings(max_attempts=1, circuit_failure_threshold=1),
    )
    with pytest.raises(UpstreamRateLimited):
        client.get_html(f"{URL}&page=1")
    assert client.breaker_state == "open"


def test_breaker_allows_one_trial_after_the_cooldown(
    make_client: AnyFactory, clock: FakeClock
) -> None:
    client = make_client(
        [script(500), script(200, BODY)],
        client_settings=Settings(
            max_attempts=1, circuit_failure_threshold=1, circuit_cooldown_seconds=60.0
        ),
    )
    with pytest.raises(UpstreamRateLimited):
        client.get_html(f"{URL}&page=1")
    assert client.breaker_state == "open"

    clock.advance(61)
    assert client.breaker_state == "half_open"
    assert client.get_html(f"{URL}&page=2").text == BODY
    assert client.breaker_state == "closed"


def test_successful_calls_reset_the_failure_count(make_client: AnyFactory) -> None:
    """A success clears the run of failures, so the breaker needs two fresh ones.

    Failures one and two are separated by a success; without the reset the
    breaker would already be open by page 3 and page 3 would never be reached.
    """
    client = make_client(
        [script(500), script(200, BODY), script(500), script(500)],
        client_settings=Settings(max_attempts=1, circuit_failure_threshold=2),
    )
    with pytest.raises(UpstreamRateLimited):
        client.get_html(f"{URL}&page=1")
    assert client.breaker_state == "closed"

    assert client.get_html(f"{URL}&page=2").text == BODY

    with pytest.raises(UpstreamRateLimited):
        client.get_html(f"{URL}&page=3")
    assert client.breaker_state == "closed", "the page 1 failure was forgotten"

    with pytest.raises(UpstreamRateLimited):
        client.get_html(f"{URL}&page=4")
    assert client.breaker_state == "open"
