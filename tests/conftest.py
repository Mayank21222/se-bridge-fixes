"""Shared fixtures and offline HTTP doubles.

Nothing in the default suite touches the network. Every test that needs
upstream behaviour injects either the recorded HTML fixtures or a
:class:`FakeTransport` driven by a queue of scripted responses, and injects a
fake clock so cache TTLs, retry backoff and rate spacing are exercised without
real waiting.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.main import app
from app.upstream import client as client_module

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add ``--live`` so live tests are opt-in and never run by accident."""
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="also run tests that make real requests to the target site",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every ``live`` test unless ``--live`` was passed."""
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live because it calls the target site")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def fixture_html(name: str) -> str:
    """Return the recorded HTML for a fixture, given its name without extension."""
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


@dataclass
class FakeClock:
    """Monotonic seconds plus wall-clock seconds, both advanced by hand."""

    monotonic_now: float = 1_000.0
    wall_now: float = 1_767_225_600.0  # 2026-01-01T00:00:00Z

    def monotonic(self) -> float:
        return self.monotonic_now

    def wall_clock(self) -> float:
        return self.wall_now

    def advance(self, seconds: float) -> None:
        self.monotonic_now += seconds
        self.wall_now += seconds


@dataclass
class RecordingSleeper:
    """Captures every sleep and advances the fake clock, as a real one would.

    Advancing matters: the rate limiter measures elapsed time from the same
    monotonic clock, so without it every retry would also queue up a rate-limit
    wait and the assertions below could not tell the two apart.
    """

    calls: list[float] = field(default_factory=list)
    clock: FakeClock | None = None

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self.clock is not None:
            self.clock.advance(seconds)


@dataclass
class ScriptedResponse:
    """One canned HTTP response, or an exception to raise instead."""

    status_code: int = 200
    html: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    raises: BaseException | None = None

    def build(self, request: httpx.Request) -> httpx.Response:
        if self.raises is not None:
            raise self.raises
        return httpx.Response(
            self.status_code,
            headers=self.headers,
            text=self.html,
            request=request,
        )


@dataclass
class FakeTransport:
    """An ``httpx`` transport that replays a queue of scripted responses.

    The final entry repeats once the queue is exhausted to its last element, so
    a test that only cares about the first few responses need not spell out
    every step. A completely empty queue is a test bug and fails loudly.
    """

    queue: list[ScriptedResponse] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)
    arrivals: list[float] = field(default_factory=list)
    clock: FakeClock | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.clock is not None:
            self.arrivals.append(self.clock.monotonic())
        if not self.queue:
            raise AssertionError(f"unexpected request to {request.url}")
        step = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        return step.build(request)

    @property
    def gaps(self) -> list[float]:
        """Seconds between consecutive arrivals, as the rate limiter saw them."""
        return [
            later - earlier
            for earlier, later in zip(self.arrivals, self.arrivals[1:], strict=False)
        ]

    @property
    def urls(self) -> list[str]:
        return [str(request.url) for request in self.requests]

    def count(self, fragment: str) -> int:
        return sum(1 for url in self.urls if fragment in url)


def script(
    status_code: int = 200,
    html: str = "",
    headers: dict[str, str] | None = None,
    raises: BaseException | None = None,
) -> ScriptedResponse:
    """Build one scripted response."""
    return ScriptedResponse(
        status_code=status_code, html=html, headers=headers or {}, raises=raises
    )


@pytest.fixture
def settings() -> Settings:
    """Settings with test-friendly limits and no contact details to leak."""
    return Settings(
        user_agent="se-bridge-tests/0.1 (offline test suite)",
        requests_per_second=1000.0,
        cache_ttl_seconds=300,
        max_attempts=3,
        backoff_base_seconds=1.0,
        read_timeout_seconds=5.0,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sleeper(clock: FakeClock) -> RecordingSleeper:
    return RecordingSleeper(clock=clock)


@pytest.fixture
def transport(clock: FakeClock) -> FakeTransport:
    return FakeTransport(clock=clock)


@pytest.fixture(autouse=True)
def _reset_process_client() -> Iterable[None]:
    """Keep the process-wide client from leaking between tests."""
    client_module.reset_client()
    yield
    client_module.reset_client()


def _inject(
    transport: FakeTransport, clock: FakeClock, sleeper: RecordingSleeper
) -> dict[str, Any]:
    transport.clock = clock
    return {
        "transport": transport,
        "clock": clock.monotonic,
        "wall_clock": clock.wall_clock,
        "sleeper": sleeper,
        "random_source": lambda: 0.5,
    }


@pytest.fixture
def make_client(
    settings: Settings,
    transport: FakeTransport,
    clock: FakeClock,
    sleeper: RecordingSleeper,
) -> Callable[..., Any]:
    """Build an ``UpstreamClient`` wired to the doubles above."""
    from app.upstream.client import UpstreamClient

    def factory(
        queued: Sequence[ScriptedResponse] = (),
        *,
        client_settings: Settings | None = None,
        **overrides: Any,
    ) -> UpstreamClient:
        transport.queue = list(queued)
        options = _inject(transport, clock, sleeper)
        options.update(overrides)
        return UpstreamClient(client_settings or settings, **options)

    return factory


@pytest.fixture
def make_service(
    settings: Settings,
    make_client: Callable[..., Any],
) -> Callable[..., Any]:
    """Build a ``CatalogService`` whose client is wired to the doubles above."""
    from app.services.catalog import CatalogService

    def factory(
        queued: Sequence[ScriptedResponse] = (),
        *,
        service_settings: Settings | None = None,
        **overrides: Any,
    ) -> Any:
        client_settings = service_settings or settings
        client = make_client(queued, client_settings=client_settings, **overrides)
        return CatalogService(client=client, settings=client_settings)

    return factory


@pytest.fixture
def make_api(
    settings: Settings,
    make_client: Callable[..., Any],
) -> Iterable[Callable[..., Any]]:
    """Build a ``TestClient`` whose service reads the doubles above.

    The app resolves its client through ``get_client``, so overriding that one
    dependency is all it takes to make the whole HTTP surface offline. The
    override is removed again after each test.
    """
    from fastapi.testclient import TestClient

    def factory(
        queued: Sequence[ScriptedResponse] = (),
        *,
        service_settings: Settings | None = None,
        **overrides: Any,
    ) -> TestClient:
        client = make_client(queued, client_settings=service_settings or settings, **overrides)
        app.dependency_overrides[client_module.get_client] = lambda: client
        return TestClient(app, raise_server_exceptions=False)

    yield factory
    app.dependency_overrides.clear()
