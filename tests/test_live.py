"""Live tests: these make real, rate-limited requests to the target site.

They are skipped unless ``--live`` is passed, because they are the only tests
in the project that touch the network::

    make test-live

Each test goes through :class:`~app.upstream.client.UpstreamClient`, so the
bridge's own one-request-per-second limit and 300-second cache apply. They are
few and coarse on purpose: the offline suite covers the logic, and these prove
the real site still looks the way the parsers expect.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.errors import ApiError, UpstreamNotFound
from app.services.catalog import CatalogService
from app.upstream.client import UpstreamClient

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def settings() -> Settings:
    """Live settings: the production default of one request per second."""
    return Settings(
        cache_ttl_seconds=600,
        user_agent=(
            "standard-ebooks-bridge/1.0 (reverse-engineering exercise; "
            "contact candidate@example.invalid)"
        ),
    )


@pytest.fixture(scope="module")
def client(settings: Settings) -> UpstreamClient:
    with UpstreamClient(settings) as upstream:
        yield upstream


@pytest.fixture(scope="module")
def service(client: UpstreamClient, settings: Settings) -> CatalogService:
    return CatalogService(client=client, settings=settings)


def test_live_health_reports_the_site_reachable(service: CatalogService) -> None:
    data, _ = service.health()
    assert data.upstream_reachable is True
    assert data.status == "ok"


def test_live_listing_returns_full_summaries(service: CatalogService) -> None:
    result = service.list_ebooks(page=1, page_size=12)
    assert len(result.items) == 12
    assert result.total is None, "the catalogue still publishes no total"
    first = result.items[0]
    assert first.id and first.title
    assert first.authors, "list rows must still carry an author"
    assert first.source_url.startswith("https://standardebooks.org/ebooks/")
    assert first.word_count and first.word_count > 0


def test_live_second_page_differs_from_the_first(service: CatalogService) -> None:
    first = service.list_ebooks(page=1, page_size=12)
    second = service.list_ebooks(page=2, page_size=12)
    assert {item.id for item in first.items}.isdisjoint({item.id for item in second.items})
    assert second.page == 2


def test_live_search_finds_shakespeare(service: CatalogService) -> None:
    result = service.search_ebooks(query="shakespeare", page=1, page_size=12)
    assert result.items
    assert any(item.id.startswith("william-shakespeare/") for item in result.items)


def test_live_search_without_matches_is_empty_not_an_error(service: CatalogService) -> None:
    result = service.search_ebooks(query="zzzqqqxyzzy-no-such-book", page=1, page_size=12)
    assert result.items == []


def test_live_subject_filter_returns_only_that_subject(service: CatalogService) -> None:
    result = service.list_ebooks(page=1, page_size=12, subject="science-fiction")
    assert result.items
    assert all("science-fiction" in {ref.slug for ref in item.subjects} for item in result.items)


def test_live_detail_record_is_complete(service: CatalogService) -> None:
    result = service.get_ebook("dorothy-m-richardson/oberland")
    detail = result.items
    assert detail.title == "Oberland"
    assert detail.authors and detail.authors[0].slug == "dorothy-m-richardson"
    assert detail.description and detail.abstract
    assert detail.license.startswith("https://creativecommons.org/")
    assert detail.source_repository_url
    assert {fmt.label for fmt in detail.formats} >= {"epub", "azw3", "kepub"}


def test_live_three_segment_identifier_resolves(service: CatalogService) -> None:
    detail = service.get_ebook("thomas-a-kempis/the-imitation-of-christ/william-benham").items
    assert detail.id.endswith("/william-benham")
    assert [ref.role for ref in detail.contributors] == ["Translated by"]


def test_live_unknown_ebook_is_not_found(service: CatalogService) -> None:
    with pytest.raises(UpstreamNotFound) as caught:
        service.get_ebook("nobody-here/nothing-here")
    assert caught.value.retryable is False


def test_live_subject_facets(service: CatalogService) -> None:
    facets = service.list_subjects().items
    slugs = {facet.slug for facet in facets}
    assert {"fiction", "science-fiction", "poetry"} <= slugs
    assert len(slugs) == len(facets), "slugs must be unique"


def test_live_author_page(service: CatalogService) -> None:
    result = service.list_author_ebooks("dorothy-m-richardson")
    assert result.total and result.total > 1
    assert all(item.id.startswith("dorothy-m-richardson/") for item in result.items)


def test_live_invalid_input_never_reaches_the_site(service: CatalogService) -> None:
    for bad in ("../etc/passwd", "Author/Title", "a/b/c/d"):
        with pytest.raises(ApiError) as caught:
            service.get_ebook(bad)
        assert caught.value.code == "BAD_REQUEST"


def test_live_cache_avoids_a_second_round_trip(service: CatalogService) -> None:
    """Assert the cache on a URL no earlier live test has touched."""
    unique = {"page_size": 12, "page": 7}
    first = service.list_ebooks(**unique)
    second = service.list_ebooks(**unique)
    assert second.cached is True
    assert first.fetched_at == second.fetched_at
    assert first.items and second.items
    assert [item.id for item in first.items] == [item.id for item in second.items]


def test_live_circuit_breaker_is_closed(client: UpstreamClient) -> None:
    """A polite run of real calls must never trip the breaker."""
    assert client.breaker_state == "closed"
