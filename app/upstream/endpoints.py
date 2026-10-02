"""Every URL, path and query-parameter name this bridge uses.

If Standard Ebooks moves a page or renames a query parameter, this file is the
only one that changes. Nothing else in the project imports a literal URL.
"""

from __future__ import annotations

from urllib.parse import urlencode

from app.config import Settings

# --- Paths -----------------------------------------------------------------
CATALOG_PATH = "/ebooks"
AUTHOR_PATH = "/ebooks/{author_slug}"
EBOOK_PATH = "/ebooks/{ebook_id}"
SUBJECT_PATH = "/subjects/{subject_slug}"

# --- Query parameter names -------------------------------------------------
PARAM_PAGE = "page"
PARAM_PER_PAGE = "per-page"
PARAM_QUERY = "query"
PARAM_TAGS = "tags[]"
PARAM_SORT = "sort"
PARAM_VIEW = "view"

#: Ask the catalogue for the verbose row layout, which carries word count,
#: reading ease, subjects and contributors.
VIEW_LIST = "list"

#: The value the catalogue's filter form uses for "no subject filter".
SUBJECT_ALL = "all"

# The catalogue changes its sort menu depending on whether a query is present:
# with a free-text query it offers "Relevance" and "Newest", without one it
# offers "S.E. release date (new -> old)". We expose one vocabulary and map it
# onto whichever menu is live, so callers never have to remember the quirk.
SORT_NEWEST = "newest"
SORT_RELEVANCE = "relevance"
SORT_AUTHOR_ALPHA = "author-alpha"
SORT_READING_EASE = "reading-ease"
SORT_LENGTH = "length"
SORT_POPULARITY = "popularity"

#: Upstream sort keys, keyed by our public key, for listing and for search.
_UPSTREAM_SORT_LISTING = {
    SORT_NEWEST: "default",
    SORT_AUTHOR_ALPHA: SORT_AUTHOR_ALPHA,
    SORT_READING_EASE: SORT_READING_EASE,
    SORT_LENGTH: SORT_LENGTH,
    SORT_POPULARITY: SORT_POPULARITY,
}
_UPSTREAM_SORT_SEARCH = {
    SORT_NEWEST: SORT_NEWEST,
    SORT_RELEVANCE: SORT_RELEVANCE,
    SORT_AUTHOR_ALPHA: SORT_AUTHOR_ALPHA,
    SORT_READING_EASE: SORT_READING_EASE,
    SORT_LENGTH: SORT_LENGTH,
    SORT_POPULARITY: SORT_POPULARITY,
}

SORT_LISTING_OPTIONS: dict[str, str] = {
    SORT_NEWEST: "Release date (newest first)",
    SORT_AUTHOR_ALPHA: "Author name (A-Z)",
    SORT_READING_EASE: "Reading ease (easy to hard)",
    SORT_LENGTH: "Length (short to long)",
    SORT_POPULARITY: "Popularity (most to least)",
}
SORT_SEARCH_OPTIONS: dict[str, str] = {
    SORT_RELEVANCE: "Relevance to the query",
    SORT_NEWEST: "Release date (newest first)",
    SORT_AUTHOR_ALPHA: "Author name (A-Z)",
    SORT_READING_EASE: "Reading ease (easy to hard)",
    SORT_LENGTH: "Length (short to long)",
    SORT_POPULARITY: "Popularity (most to least)",
}


def upstream_sort(sort: str, *, searching: bool) -> str:
    """Translate a public sort key into the key the catalogue expects."""
    table = _UPSTREAM_SORT_SEARCH if searching else _UPSTREAM_SORT_LISTING
    return table.get(sort, table[SORT_NEWEST])


def base_url(settings: Settings) -> str:
    """Configured origin of the target site, without a trailing slash."""
    return settings.base_url


def catalog_url(
    settings: Settings,
    *,
    page: int,
    per_page: int,
    sort: str | None = None,
    subject: str | None = None,
    query: str | None = None,
) -> str:
    """Absolute URL of a catalogue listing page.

    ``subject`` maps onto the catalogue's ``tags[]`` filter and ``query`` onto
    its free-text box; both are optional and combine freely upstream.
    """
    params: list[tuple[str, str]] = [
        (PARAM_VIEW, VIEW_LIST),
        (PARAM_PER_PAGE, str(per_page)),
        (PARAM_PAGE, str(page)),
    ]
    if sort and sort != SORT_NEWEST:
        params.append((PARAM_SORT, upstream_sort(sort, searching=bool(query))))
    if subject and subject != SUBJECT_ALL:
        params.append((PARAM_TAGS, subject))
    if query:
        params.append((PARAM_QUERY, query))
    return f"{base_url(settings)}{CATALOG_PATH}?{urlencode(params)}"


def author_url(settings: Settings, author_slug: str) -> str:
    """Absolute URL of the "all ebooks by this author" page.

    That page renders every entry at once and ignores both ``page`` and
    ``view``: verified against the live site, which still answers in grid mode
    with ``?view=list&per-page=48``. Callers therefore get one complete result
    set, and grid rows carry no subjects or word counts.
    """
    return f"{base_url(settings)}{AUTHOR_PATH.format(author_slug=author_slug)}"


def ebook_url(settings: Settings, ebook_id: str) -> str:
    """Absolute URL of one ebook's public page.

    ``ebook_id`` is the catalogue's own path tail, e.g.
    ``thomas-a-kempis/the-imitation-of-christ/william-benham``.
    """
    return f"{base_url(settings)}{EBOOK_PATH.format(ebook_id=ebook_id)}"


def subject_url(settings: Settings, subject_slug: str) -> str:
    """Absolute URL of one subject's landing page."""
    return f"{base_url(settings)}{SUBJECT_PATH.format(subject_slug=subject_slug)}"
