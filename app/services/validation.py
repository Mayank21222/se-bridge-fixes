"""Caller-facing input validation.

Everything a client can get wrong is rejected here, before a single byte
leaves the machine. That is why a ``page=0`` request makes no upstream call at
all: it never reaches the politeness layer.
"""

from __future__ import annotations

import re

from app.config import Settings
from app.errors import bad_request
from app.upstream import endpoints

#: A catalogue slug: lowercase, digits and single hyphens.
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: An ebook identifier is the catalogue's own path tail, either
#: ``author-slug/title-slug`` or ``author-slug/title-slug/contributor-slug``.
#: Anchored, so ``..``, ``%2e%2e``, uppercase and backslashes all fail.
_EBOOK_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*){1,2}$")

_MAX_EBOOK_ID_LENGTH = 200
_MAX_SLUG_LENGTH = 128


def validate_page(page: int | None) -> int:
    """Return a 1-based page number or raise ``BAD_REQUEST``."""
    if page is None:
        return 1
    if page < 1:
        raise bad_request("page must be at least 1")
    return page


def validate_page_size(page_size: int | None, settings: Settings) -> int:
    """Return a page size within the configured ceiling or raise ``BAD_REQUEST``."""
    if page_size is None:
        return settings.default_page_size
    if page_size < 1:
        raise bad_request("page_size must be at least 1")
    if page_size > settings.page_size_ceiling:
        raise bad_request(
            f"page_size must not exceed {settings.page_size_ceiling} "
            "so that no caller can ask the site for an unbounded page"
        )
    return page_size


def validate_sort(sort: str | None, *, searching: bool) -> str:
    """Return a sort key valid for this endpoint, or raise ``BAD_REQUEST``.

    The catalogue itself offers different sort menus for browsing and for
    searching - relevance only exists once a query is present - so a key that
    is meaningless here is rejected rather than silently dropped upstream.
    """
    allowed = endpoints.SORT_SEARCH_OPTIONS if searching else endpoints.SORT_LISTING_OPTIONS
    if sort is None or sort == "":
        return endpoints.SORT_NEWEST
    if sort not in allowed:
        names = ", ".join(sorted(allowed))
        where = "search" if searching else "listing"
        raise bad_request(f"sort must be one of: {names} (valid for {where})")
    return sort


def validate_subject(subject: str | None) -> str | None:
    """Return a subject slug, or ``None`` when no subject filter was asked for.

    An unknown but well-formed slug is passed through: the catalogue answers
    with an empty page, which is a valid result, not an error.
    """
    if subject is None:
        return None
    slug = subject.strip().lower()
    if slug in {"", endpoints.SUBJECT_ALL}:
        return None
    if len(slug) > _MAX_SLUG_LENGTH or not _SLUG.match(slug):
        raise bad_request("subject must be a lowercase catalogue slug such as 'science-fiction'")
    return slug


def validate_author_slug(author_slug: str) -> str:
    """Return a validated author slug or raise ``BAD_REQUEST``."""
    slug = author_slug.strip().lower()
    if not slug or len(slug) > _MAX_SLUG_LENGTH or not _SLUG.match(slug):
        raise bad_request("author must be a lowercase catalogue slug such as 'oscar-wilde'")
    return slug


def validate_ebook_id(ebook_id: str) -> str:
    """Return a validated ebook identifier or raise ``BAD_REQUEST``.

    Identifiers mirror the site's own path tails, so one or two forward
    slashes are expected. Everything else - a leading or trailing slash, a
    doubled slash, ``..``, a backslash, more than three segments, an
    over-long value - is refused here rather than being turned into a request.
    """
    raw = (ebook_id or "").strip()
    if not raw:
        raise bad_request("ebook id must not be empty")
    if len(raw) > _MAX_EBOOK_ID_LENGTH:
        raise bad_request(f"ebook id must be at most {_MAX_EBOOK_ID_LENGTH} characters")
    if raw != raw.strip("/"):
        raise bad_request("ebook id must not start or end with a slash")
    if "//" in raw or "\\" in raw:
        raise bad_request("ebook id must not contain empty or backslash-separated segments")
    if not _EBOOK_ID.match(raw):
        raise bad_request(
            "ebook id must look like 'author-slug/title-slug' or "
            "'author-slug/title-slug/contributor-slug' using lowercase slugs"
        )
    return raw


def validate_query(query: str | None, settings: Settings) -> str:
    """Return a non-empty search string or raise ``BAD_REQUEST``.

    The value is only length-checked here; percent-encoding happens in
    :mod:`app.upstream.endpoints`, so punctuation and non-ASCII are safe.
    """
    if query is None:
        raise bad_request("q is required and must not be empty or whitespace only")
    trimmed = query.strip()
    if not trimmed:
        raise bad_request("q must not be empty or whitespace only")
    if len(trimmed) > settings.max_query_length:
        raise bad_request(f"q must be at most {settings.max_query_length} characters")
    return trimmed
