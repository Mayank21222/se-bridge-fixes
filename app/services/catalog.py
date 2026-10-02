"""Orchestration: turn an API request into upstream calls and a result set.

The service owns three policy decisions that the API layer should not care
about:

* which upstream URL answers a given request;
* what ``meta.total`` may honestly be (the catalogue publishes no total, so
  paginated results report ``null`` rather than a guess);
* how upstream conditions become the five allowed API error codes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from app import __version__
from app.config import Settings, get_settings
from app.errors import (
    NOT_FOUND,
    RATE_LIMITED,
    UPSTREAM_BLOCKED,
    UPSTREAM_CHANGED,
    UpstreamBlocked,
    UpstreamChanged,
    UpstreamError,
    UpstreamNotFound,
    UpstreamRateLimited,
)
from app.models import EbookDetail, EbookSummary, HealthData, Meta, SubjectFacet
from app.services import validation
from app.upstream import endpoints, parsers
from app.upstream.client import UpstreamClient, get_client

logger = logging.getLogger("app.services.catalog")


@dataclass(slots=True)
class ServiceResult:
    """A payload plus the metadata that goes into the response envelope."""

    items: object
    page: int | None
    page_size: int | None
    total: int | None
    source_url: str
    fetched_at: datetime
    cached: bool

    def to_meta(self) -> Meta:
        """Build the envelope's ``meta`` object."""
        return Meta(
            page=self.page,
            page_size=self.page_size,
            total=self.total,
            source_url=self.source_url,
            fetched_at=self.fetched_at.isoformat().replace("+00:00", "Z"),
            cached=self.cached,
        )


def error_code_for(exc: Exception) -> tuple[str, str, bool]:
    """Map an upstream condition onto ``(code, message, retryable)``.

    The vocabulary is fixed at five codes, which forces two documented
    compromises: an exhausted retry budget and a circuit-breaker trip both
    surface as ``RATE_LIMITED`` (the only retryable code in the set), and an
    unhandled internal error does too. See ``docs/TEST_RESULTS.md`` and the
    README for why.
    """
    if isinstance(exc, UpstreamNotFound):
        return NOT_FOUND, str(exc), False
    if isinstance(exc, UpstreamBlocked):
        return UPSTREAM_BLOCKED, str(exc), False
    if isinstance(exc, UpstreamChanged):
        return UPSTREAM_CHANGED, str(exc), False
    if isinstance(exc, UpstreamRateLimited):
        return RATE_LIMITED, str(exc), True
    if isinstance(exc, UpstreamError):
        return RATE_LIMITED, str(exc), True
    return RATE_LIMITED, "the request could not be completed; retry later", True


class CatalogService:
    """Read-only access to the Standard Ebooks catalogue."""

    def __init__(
        self, client: UpstreamClient | None = None, settings: Settings | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or get_client()

    # -- health -------------------------------------------------------------
    def health(self) -> tuple[HealthData, ServiceResult]:
        """Probe the target site through the same cache, limiter and breaker.

        Never raises: an unreachable site is a degraded service, not an error
        response, so a monitor can tell the two apart from the status code.
        """
        check_url = endpoints.catalog_url(
            self._settings, page=1, per_page=1, sort=endpoints.SORT_NEWEST
        )
        now = datetime.now(tz=UTC)
        try:
            fetched = self._client.get_html(check_url)
        except UpstreamError:
            logger.warning("health probe failed; reporting the site as unreachable")
            return (
                HealthData(
                    status="degraded",
                    upstream_reachable=False,
                    circuit_breaker=self._client.breaker_state,
                    upstream_check_url=check_url,
                    service_version=__version__,
                ),
                ServiceResult(
                    items=None,
                    page=None,
                    page_size=None,
                    total=None,
                    source_url=check_url,
                    fetched_at=now,
                    cached=False,
                ),
            )

        return (
            HealthData(
                status="ok",
                upstream_reachable=True,
                circuit_breaker=self._client.breaker_state,
                upstream_check_url=check_url,
                service_version=__version__,
            ),
            ServiceResult(
                items=None,
                page=None,
                page_size=None,
                total=None,
                source_url=check_url,
                fetched_at=fetched.fetched_at,
                cached=fetched.from_cache,
            ),
        )

    # -- listing and search -------------------------------------------------
    def list_ebooks(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
        subject: str | None = None,
        sort: str | None = None,
    ) -> ServiceResult:
        """Return one page of the catalogue, filtered by subject and sorted."""
        return self._catalog_page(
            page=page, page_size=page_size, subject=subject, sort=sort, query=None
        )

    def search_ebooks(
        self,
        *,
        query: str | None,
        page: int | None = None,
        page_size: int | None = None,
        subject: str | None = None,
        sort: str | None = None,
    ) -> ServiceResult:
        """Return one page of catalogue results for a free-text query."""
        return self._catalog_page(
            page=page, page_size=page_size, subject=subject, sort=sort, query=query
        )

    def _catalog_page(
        self,
        *,
        page: int | None,
        page_size: int | None,
        subject: str | None,
        sort: str | None,
        query: str | None,
    ) -> ServiceResult:
        """Shared path for listing and search; the catalogue page does both."""
        resolved_page = validation.validate_page(page)
        resolved_size = validation.validate_page_size(page_size, self._settings)
        resolved_query = (
            validation.validate_query(query, self._settings) if query is not None else None
        )
        resolved_sort = validation.validate_sort(sort, searching=resolved_query is not None)
        resolved_subject = validation.validate_subject(subject)

        url = endpoints.catalog_url(
            self._settings,
            page=resolved_page,
            per_page=resolved_size,
            sort=resolved_sort,
            subject=resolved_subject,
            query=resolved_query,
        )
        fetched = self._client.get_html(url)
        items: list[EbookSummary] = parsers.parse_catalog_page(fetched.text, source_url=fetched.url)
        return ServiceResult(
            items=items,
            page=resolved_page,
            page_size=resolved_size,
            # The catalogue paginates without ever publishing a total, and the
            # page-number strip is a sliding window, so a total would be a lie.
            total=None,
            source_url=fetched.url,
            fetched_at=fetched.fetched_at,
            cached=fetched.from_cache,
        )

    # -- facets -------------------------------------------------------------
    def list_subjects(self) -> ServiceResult:
        """Return the subject facets the catalogue can filter on."""
        url = endpoints.catalog_url(self._settings, page=1, per_page=1, sort=endpoints.SORT_NEWEST)
        fetched = self._client.get_html(url)
        facets: list[SubjectFacet] = parsers.parse_subject_facets(
            fetched.text, source_url=fetched.url
        )
        return ServiceResult(
            items=facets,
            page=1,
            page_size=len(facets),
            total=len(facets),
            source_url=fetched.url,
            fetched_at=fetched.fetched_at,
            cached=fetched.from_cache,
        )

    # -- single records -----------------------------------------------------
    def get_ebook(self, ebook_id: str) -> ServiceResult:
        """Return the full record for one ebook.

        An unknown identifier produces ``NOT_FOUND``; a malformed one is
        rejected by :func:`~app.services.validation.validate_ebook_id` before
        any request is made.
        """
        resolved_id = validation.validate_ebook_id(ebook_id)
        url = endpoints.ebook_url(self._settings, resolved_id)
        fetched = self._client.get_html(url)
        detail: EbookDetail = parsers.parse_ebook_page(
            fetched.text, source_url=fetched.url, base_url=fetched.url
        )
        return ServiceResult(
            items=detail,
            page=1,
            page_size=1,
            total=1,
            source_url=fetched.url,
            fetched_at=fetched.fetched_at,
            cached=fetched.from_cache,
        )

    def list_author_ebooks(self, author_slug: str) -> ServiceResult:
        """Return every ebook by one author.

        The site's author page renders its whole (short) run at once and
        ignores ``page``, so there is exactly one page here and its length is a
        real total. It also ignores ``view`` and always answers in grid mode,
        whose rows carry no subjects or word counts; that is an upstream limit,
        not a parsing gap.
        """
        slug = validation.validate_author_slug(author_slug)
        url = endpoints.author_url(self._settings, slug)
        fetched = self._client.get_html(url)
        items = parsers.parse_catalog_page(fetched.text, source_url=fetched.url)
        return ServiceResult(
            items=items,
            page=1,
            page_size=len(items),
            total=len(items),
            source_url=fetched.url,
            fetched_at=fetched.fetched_at,
            cached=fetched.from_cache,
        )


__all__ = [
    "CatalogService",
    "ServiceResult",
    "UpstreamBlocked",
    "UpstreamChanged",
    "UpstreamError",
    "error_code_for",
]
