"""HTTP-surface tests: the envelope, the error vocabulary and validation.

These run against the real routing and exception handlers, with the upstream
client replaced by a scripted transport, so a request either never leaves the
process or returns exactly what the double was told to return.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import pytest

from app.config import Settings
from app.errors import ERROR_STATUS
from app.upstream import endpoints
from tests.conftest import fixture_html, script

AnyFactory = Callable[..., Any]

PAGE_1_URL = "https://standardebooks.org/ebooks?view=list&per-page=12&page=1"
OBERLAND = fixture_html("ebook_oberland")
LISTING = fixture_html("catalog_page_1")
PAGE_2 = fixture_html("catalog_page_2")
EMPTY = fixture_html("catalog_search_empty")
DETAIL = fixture_html("ebook_oberland")


# ------------------------------------------------------------------ root/docs
def test_root_points_at_the_docs(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        body = client.get("/").json()
    assert body["health"] == "/health"
    assert body["openapi"] == "/openapi.json"
    assert body["docs"] == "/docs"


def test_openapi_document_is_served_and_covers_every_route(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/health",
        "/v1/ebooks",
        "/v1/search",
        "/v1/ebooks/{ebook_id}",
        "/v1/subjects",
        "/v1/authors/{author_slug}",
    }


# ----------------------------------------------------------------- the envelope
def test_success_uses_the_single_envelope(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert isinstance(body["data"], list)
    assert set(body["meta"]) == {
        "page",
        "page_size",
        "total",
        "source_url",
        "fetched_at",
        "cached",
    }


def test_meta_reports_page_size_and_an_honest_null_total(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        meta = client.get("/v1/ebooks?page=2&page_size=24").json()["meta"]
    assert meta["page"] == 2
    assert meta["page_size"] == 24
    assert meta["total"] is None, "the catalogue publishes no total, so we must not invent one"
    assert meta["source_url"].startswith("https://standardebooks.org/ebooks?")
    assert meta["fetched_at"].endswith("Z")
    assert meta["cached"] is False


def test_cached_flag_flips_on_a_repeat_request(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        first = client.get("/v1/ebooks").json()["meta"]
        second = client.get("/v1/ebooks").json()["meta"]
    assert (first["cached"], second["cached"]) == (False, True)
    assert first["fetched_at"] == second["fetched_at"]


def test_failure_uses_the_single_error_envelope(make_api: AnyFactory) -> None:
    with make_api([script(404)]) as client:
        response = client.get("/v1/ebooks/edwin-a-abbott/flatland")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "retryable"}
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["retryable"] is False


def test_error_responses_never_leak_internals(make_api: AnyFactory) -> None:
    with make_api([script(500)]) as client:
        response = client.get("/v1/ebooks")
    text = response.text.lower()
    assert "traceback" not in text
    assert "app.upstream" not in text
    assert 'file "' not in text


# ------------------------------------------------------------------- listing
def test_listing_returns_summaries(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        items = client.get("/v1/ebooks").json()["data"]
    assert len(items) == 12
    assert items[0]["id"] == "dorothy-m-richardson/oberland"
    assert (
        items[0]["source_url"] == "https://standardebooks.org/ebooks/dorothy-m-richardson/oberland"
    )


def test_listing_defaults_to_twelve_per_page(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, LISTING)]) as client:
        client.get("/v1/ebooks")
    assert "per-page=12" in transport.urls[0]


def test_page_two_asks_upstream_for_page_two(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, PAGE_2)]) as client:
        items = client.get("/v1/ebooks?page=2").json()["data"]
    assert "page=2" in transport.urls[0]
    assert items[0]["id"] == "theodore-roosevelt/a-book-lovers-holidays-in-the-open"


def test_subject_filter_selects_the_subject_path(make_api: AnyFactory, transport: Any) -> None:
    """A subject filter asks for /subjects/{slug}, not /ebooks?tags[]=.

    The site's own filter form submits ``tags[]``, but the server answers that
    with a 302 to the subject path, so requesting the path directly is both
    canonical and one round trip cheaper.
    """
    with make_api([script(200, LISTING)]) as client:
        client.get("/v1/ebooks?subject=science-fiction")
    assert transport.urls[0].startswith("https://standardebooks.org/subjects/science-fiction?")


def test_a_traversing_subject_slug_is_rejected_before_any_request(
    make_api: AnyFactory, transport: Any
) -> None:
    """A slug that tries to climb out of /subjects/ never becomes a request.

    Two layers refuse it: the slug validator, and path-segment escaping in the
    URL builder. The validator is what a caller actually meets, and it must
    reject rather than quietly fetching something unexpected.
    """
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks?subject=../../honeypot")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    assert transport.requests == [], "an invalid slug must never reach upstream"


def test_subject_url_builder_escapes_a_segment_defensively(settings: Settings) -> None:
    """Belt and braces: even bypassing the validator, a slug stays one segment.

    The claim is about structure, not characters. After escaping, the slug is a
    single path segment whose name happens to contain dots, so it cannot climb
    out of /subjects/ however the server decodes it.
    """
    built = endpoints.catalog_url(settings, page=1, per_page=12, subject="../../honeypot")
    parsed = urlsplit(built)
    assert parsed.scheme == "https"
    assert parsed.netloc == "standardebooks.org"
    segments = [s for s in parsed.path.split("/") if s]
    assert segments[:1] == ["subjects"], parsed.path
    assert len(segments) == 2, f"slug must be one segment, got {parsed.path!r}"


def test_empty_result_is_a_200_with_no_rows(make_api: AnyFactory) -> None:
    with make_api([script(200, EMPTY)]) as client:
        response = client.get("/v1/ebooks?subject=not-a-real-subject")
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["meta"]["total"] == 0


# -------------------------------------------------------------------- search
def test_search_requires_a_query(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/search")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    assert transport.requests == [], "an invalid request must never reach upstream"


def test_search_passes_the_query_through(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, fixture_html("catalog_search_shakespeare"))]) as client:
        items = client.get("/v1/search?q=shakespeare").json()["data"]
    assert "query=shakespeare" in transport.urls[0]
    assert len(items) == 12


def test_blank_search_is_rejected(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/search?q=%20%20")
    assert response.status_code == 400
    assert transport.requests == []


def test_search_with_no_matches_is_an_empty_200(make_api: AnyFactory) -> None:
    with make_api([script(200, EMPTY)]) as client:
        response = client.get("/v1/search?q=zzzqqqxyzzy")
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["meta"]["total"] == 0


def test_special_characters_in_a_query_are_encoded_not_injected(
    make_api: AnyFactory, transport: Any
) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/search", params={"q": "a&b=c d/e?f#g+ü"})
    assert response.status_code == 200
    url = transport.urls[0]
    assert "&b=c" not in url, "the query must not break out of its parameter"
    assert " " not in url, "spaces must be percent-encoded"


def test_search_with_special_characters_and_very_long_query_is_handled_safely(
    make_api: AnyFactory, transport: Any
) -> None:
    very_long_query = "title & author = 'test' / \"quote\" ? # fragment " + "a" * 140
    assert len(very_long_query) <= 200
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/search", params={"q": very_long_query})
    assert response.status_code == 200
    assert len(transport.requests) == 1
    url = transport.urls[0]
    assert "&author=" not in url
    assert "#" not in url.split("?")[1]


def test_over_long_query_is_rejected(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/search", params={"q": "x" * 201})
    assert response.status_code == 400
    assert "200" in response.json()["error"]["message"]
    assert transport.requests == []


def test_non_ascii_query_is_accepted(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/search", params={"q": "müller ünicode"})
    assert response.status_code == 200
    assert "%C3%BC" in transport.urls[0]


# --------------------------------------------------------------- single record
def test_detail_returns_the_full_record(make_api: AnyFactory) -> None:
    with make_api([script(200, DETAIL)]) as client:
        body = client.get("/v1/ebooks/dorothy-m-richardson/oberland").json()
    record = body["data"]
    assert record["title"] == "Oberland"
    assert record["language"] == "en-GB"
    assert record["formats"]
    assert body["meta"]["total"] == 1
    assert record["source_url"].endswith("/ebooks/dorothy-m-richardson/oberland")


def test_detail_accepts_a_three_segment_id(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, fixture_html("ebook_imitation_of_christ"))]) as client:
        response = client.get("/v1/ebooks/thomas-a-kempis/the-imitation-of-christ/william-benham")
    assert response.status_code == 200
    assert transport.urls[0].endswith(
        "/ebooks/thomas-a-kempis/the-imitation-of-christ/william-benham"
    )


def test_unknown_ebook_is_not_found(make_api: AnyFactory) -> None:
    with make_api([script(404)]) as client:
        response = client.get("/v1/ebooks/nobody/nothing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "ebook_id",
    [
        "a",
        "author/",
        "/author/title",
        "author//title",
        "author/title/extra/segments",
        "..%2f..%2fetc%2fpasswd",
        "Author/Title",
        "author\\title",
        "edwin-a-abbott/flatland/text",
        "edwin-a-abbott/flatland/downloads",
    ],
)
def test_malformed_ids_are_rejected_without_calling_upstream(
    make_api: AnyFactory, transport: Any, ebook_id: str
) -> None:
    with make_api([script(200, DETAIL)]) as client:
        response = client.get(f"/v1/ebooks/{ebook_id}")
    assert response.status_code == 400, f"{ebook_id!r} should not be accepted"
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    assert transport.requests == []


@pytest.mark.parametrize("ebook_id", ["author/../../etc/passwd", "author/title/../../.."])
def test_traversal_attempts_never_reach_upstream(
    make_api: AnyFactory, transport: Any, ebook_id: str
) -> None:
    """An HTTP client resolves ``..`` before the request leaves it.

    So these arrive as a path that matches no route at all - a 404 rather than
    the 400 we would give the same text if it reached us. Either way the
    important property holds: nothing is forwarded to the target site.
    """
    with make_api([script(200, DETAIL)]) as client:
        response = client.get(f"/v1/ebooks/{ebook_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert transport.requests == []


def test_over_long_id_is_rejected(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, DETAIL)]) as client:
        response = client.get(f"/v1/ebooks/{'a-' * 150}/{'b-' * 150}")
    assert response.status_code == 400
    assert transport.requests == []


# --------------------------------------------------------------------- facets
def test_subjects_come_from_the_filter_form(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        body = client.get("/v1/subjects").json()
    slugs = [facet["slug"] for facet in body["data"]]
    assert "science-fiction" in slugs
    assert body["meta"]["total"] == len(slugs)


def test_author_page_lists_every_work(make_api: AnyFactory) -> None:
    with make_api([script(200, fixture_html("author_dorothy_m_richardson"))]) as client:
        body = client.get("/v1/authors/dorothy-m-richardson").json()
    assert len(body["data"]) == 13
    assert body["meta"]["total"] == 13
    assert body["meta"]["page"] == 1


def test_bad_author_slug_is_rejected(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/authors/Not%20A%20Slug")
    assert response.status_code == 400
    assert transport.requests == []


# ----------------------------------------------------------------- validation
@pytest.mark.parametrize("page", ["0", "-1", "abc"])
def test_bad_page_is_rejected(make_api: AnyFactory, transport: Any, page: str) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks", params={"page": page})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    assert transport.requests == []


@pytest.mark.parametrize("page_size", ["0", "-5"])
def test_non_positive_page_size_is_rejected(
    make_api: AnyFactory, transport: Any, page_size: str
) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks", params={"page_size": page_size})
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "page_size must be at least 1"
    assert transport.requests == []


@pytest.mark.parametrize("page_size", ["49", "1000"])
def test_page_size_above_the_ceiling_is_rejected(
    make_api: AnyFactory, transport: Any, page_size: str
) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks", params={"page_size": page_size})
    assert response.status_code == 400
    assert "48" in response.json()["error"]["message"]
    assert transport.requests == []


def test_page_size_at_the_ceiling_is_allowed(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks", params={"page_size": 48})
    assert response.status_code == 200


def test_unknown_sort_is_rejected(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks", params={"sort": "cheapest"})
    assert response.status_code == 400
    assert transport.requests == []


def test_relevance_sort_is_rejected_when_browsing(make_api: AnyFactory) -> None:
    """Relevance only exists once a query is present, so browsing rejects it."""
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks", params={"sort": "relevance"})
    assert response.status_code == 400
    assert "relevance" not in response.json()["error"]["message"]


def test_relevance_sort_is_accepted_when_searching(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, fixture_html("catalog_search_relevance"))]) as client:
        response = client.get("/v1/search", params={"q": "shakespeare", "sort": "relevance"})
    assert response.status_code == 200
    assert "sort=relevance" in transport.urls[0]


def test_newest_sort_is_omitted_upstream_for_a_browsing_request(
    make_api: AnyFactory, transport: Any
) -> None:
    with make_api([script(200, LISTING)]) as client:
        client.get("/v1/ebooks", params={"sort": "newest"})
    assert "sort=" not in transport.urls[0], "newest is the catalogue's own default"


def test_malformed_subject_is_rejected(make_api: AnyFactory, transport: Any) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks", params={"subject": "Science Fiction!"})
    assert response.status_code == 400
    assert transport.requests == []


# --------------------------------------------------------------------- health
def test_health_is_ok_when_the_site_answers(make_api: AnyFactory) -> None:
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["upstream_reachable"] is True
    assert data["service_version"]


def test_health_stays_200_and_reports_degraded_when_the_site_is_down(
    make_api: AnyFactory,
) -> None:
    with make_api([script(500)]) as client:
        response = client.get("/health")
    assert response.status_code == 200, "a monitor needs a 200 to read the body"
    data = response.json()["data"]
    assert data["status"] == "degraded"
    assert data["upstream_reachable"] is False


def test_health_survives_a_caller_error_too(make_api: AnyFactory) -> None:
    with make_api([script(500)]) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["meta"]["cached"] is False


# ------------------------------------------------------------- error mapping
@pytest.mark.parametrize(
    ("queued", "status", "code"),
    [
        ([script(404)], 404, "NOT_FOUND"),
        ([script(403)], 502, "UPSTREAM_BLOCKED"),
        ([script(429)], 429, "RATE_LIMITED"),
        ([script(500)], 429, "RATE_LIMITED"),
        ([script(200, "<html>Are you a robot?</html>")], 502, "UPSTREAM_BLOCKED"),
        ([script(200, "<html><body>nothing we recognise</body></html>")], 502, "UPSTREAM_CHANGED"),
    ],
)
def test_upstream_conditions_map_onto_the_fixed_vocabulary(
    make_api: AnyFactory, queued: list[Any], status: int, code: str
) -> None:
    with make_api(queued) as client:
        response = client.get("/v1/ebooks")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_mutated_fixture_returns_upstream_changed_and_logs_the_element(
    make_api: AnyFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """A real page minus one required element: 502, and the log names it.

    Uses a mutated fixture rather than invented markup, and asserts the log
    line names the missing element so a maintainer can find the one parser
    function responsible.
    """
    mutated = fixture_html("catalog_page_1").replace('class="ebooks-list list"', 'class="renamed"')
    with caplog.at_level("ERROR", logger="app.main"), make_api([script(200, mutated)]) as client:
        response = client.get("/v1/ebooks")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_CHANGED"
    assert "ebooks-list" in response.json()["error"]["message"]
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "ebooks-list" in logged, f"the log did not name the missing element: {logged!r}"


def test_absent_optional_field_is_returned_as_null(make_api: AnyFactory) -> None:
    """An edition with no contributors and no series still comes back whole."""
    with make_api([script(200, fixture_html("ebook_flatland"))]) as client:
        response = client.get("/v1/ebooks/edwin-a-abbott/flatland")
    assert response.status_code == 200
    record = response.json()["data"]
    assert record["contributors"] == []
    assert record["collections"] == []
    assert record["title"] == "Flatland"
    assert record["word_count"] == 33546
    assert record["source_url"].endswith("/ebooks/edwin-a-abbott/flatland")


def test_open_breaker_reports_rate_limited(make_api: AnyFactory) -> None:
    from app.config import Settings

    strict = Settings(requests_per_second=1000.0, max_attempts=1, circuit_failure_threshold=1)
    with make_api([script(500), script(500)], service_settings=strict) as client:
        first = client.get("/v1/ebooks?page=1")
        second = client.get("/v1/ebooks?page=2")
    assert first.status_code == 429
    assert second.status_code == 429
    assert "circuit breaker open" in second.json()["error"]["message"]


def test_unexpected_internal_error_is_contained(make_api: AnyFactory, monkeypatch: Any) -> None:
    from app.services import catalog as catalog_module

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a bug in the service layer")

    monkeypatch.setattr(catalog_module.CatalogService, "list_ebooks", explode)
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/ebooks")
    assert response.status_code == 429
    assert response.json()["error"]["retryable"] is True
    assert "a bug in the service layer" not in response.text


def test_every_error_code_maps_to_the_documented_status() -> None:
    assert ERROR_STATUS == {
        "BAD_REQUEST": 400,
        "NOT_FOUND": 404,
        "RATE_LIMITED": 429,
        "UPSTREAM_BLOCKED": 502,
        "UPSTREAM_CHANGED": 502,
    }


# --------------------------------------------------------------------- 404s
def test_unknown_route_uses_the_error_envelope(make_api: AnyFactory) -> None:
    """Framework-level 404s look the same as everything else this API returns."""
    with make_api([script(200, LISTING)]) as client:
        response = client.get("/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_uses_the_error_envelope(make_api: AnyFactory) -> None:
    """The vocabulary has no 405 member, so this degrades to BAD_REQUEST/400."""
    with make_api([script(200, LISTING)]) as client:
        response = client.post("/v1/ebooks")
    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "BAD_REQUEST"
    assert body["message"] == "method not allowed on this path"


# ----------------------------------------------------------- redirects guard
def test_redirect_to_disallowed_path_returns_upstream_blocked(make_api: AnyFactory) -> None:
    """A redirect hop to /honeypot is refused before socket work and returns 502."""
    with make_api([script(302, headers={"Location": "/honeypot"})]) as client:
        response = client.get("/v1/ebooks")
    assert response.status_code == 502
    body = response.json()["error"]
    assert body["code"] == "UPSTREAM_BLOCKED"
    assert body["retryable"] is False
    assert "disallowed" in body["message"]


def test_redirect_off_site_returns_upstream_blocked(make_api: AnyFactory) -> None:
    """An off-site redirect is refused and mapped to UPSTREAM_BLOCKED."""
    with make_api(
        [script(302, headers={"Location": "https://malicious.example.com/phishing"})]
    ) as client:
        response = client.get("/v1/ebooks")
    assert response.status_code == 502
    body = response.json()["error"]
    assert body["code"] == "UPSTREAM_BLOCKED"
    assert body["retryable"] is False
    assert "refusing off-site redirect" in body["message"]
