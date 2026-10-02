"""Turn Standard Ebooks HTML into typed records.

Every function here is pure: HTML in, :mod:`app.models` records out. There is
no network access, no clock and no global state, which is what lets
``tests/test_parsers.py`` run offline against fixtures in ``tests/fixtures``.

Two failure modes are distinguished on purpose:

* an **optional** field that the catalogue omitted becomes ``None`` - we never
  invent text and we never fail the record;
* a **required** element that has disappeared raises
  :class:`~app.errors.UpstreamChanged` naming that element, which the API
  layer turns into ``UPSTREAM_CHANGED`` so a maintainer knows exactly which
  selector to fix.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from app.errors import UpstreamChanged
from app.models import (
    AuthorRef,
    CollectionRef,
    ContributorRef,
    EbookDetail,
    EbookSummary,
    FormatRef,
    SourceRef,
    SubjectFacet,
    SubjectRef,
)

# Selectors for required structure. Named so error messages can quote them.
SEL_CATALOG_LIST = "ol.ebooks-list"
SEL_CATALOG_EMPTY = "p.no-results"
SEL_SUBJECT_SELECT = 'form[action="/ebooks"] select[name="tags[]"]'
SEL_CATALOG_ITEM = "ol.ebooks-list > li[about]"
SEL_ITEM_TITLE = 'span[property="schema:name"]'
SEL_DETAIL_ARTICLE = "article.ebook"
SEL_DETAIL_TITLE = 'article.ebook h1[property="schema:name"]'
SEL_DETAIL_AUTHOR = 'article.ebook a[property="schema:author"]'

_GITHUB_HOST = "github.com"
_SITE_HOST = "standardebooks.org"

_WHITESPACE = re.compile(r"\s+")
_WORDS = re.compile(r"([\d,]+)\s+words\b")
# The catalogue prints the score after the words on a detail page and before
# them in the list view ("52.12 reading ease"), so both orders are matched.
_READING_EASE_TRAILING = re.compile(r"reading ease(?: of)?\s+([\d]+(?:\.[\d]+)?)")
_READING_EASE_LEADING = re.compile(r"([\d]+(?:\.[\d]+)?)\s+reading ease\b")
_DIFFICULTY = re.compile(r"reading ease of\s+[\d.]+\s*\(([^)]+)\)")
_HOURS_MINUTES = re.compile(r"\((\d+)\s*hours?(?:\s*(\d+)\s*minutes?)?\)")
_MINUTES = re.compile(r"\((\d+)\s*minutes?\)")


# --------------------------------------------------------------------------
# Small text helpers
# --------------------------------------------------------------------------
def normalise_whitespace(value: str | None) -> str | None:
    """Collapse runs of whitespace and trim; ``None`` and blanks become ``None``."""
    if value is None:
        return None
    collapsed = _WHITESPACE.sub(" ", value).strip()
    return collapsed or None


def node_text(node: Node | None, *, deep: bool = True, separator: str = " ") -> str | None:
    """Return whitespace-normalised text for a node, or ``None``."""
    if node is None:
        return None
    return normalise_whitespace(node.text(deep=deep, separator=separator, strip=True))


def _int(raw: str | None) -> int | None:
    """Parse ``"40,658"`` into ``40658``."""
    if raw is None:
        return None
    cleaned = raw.replace(",", "").strip()
    return int(cleaned) if cleaned.isdigit() else None


def _float(raw: str | None) -> float | None:
    """Parse ``"66.57"`` into ``66.57``."""
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _attr(node: Node | None, name: str) -> str | None:
    """Read an attribute, returning ``None`` for a missing node or attribute."""
    if node is None:
        return None
    return normalise_whitespace(node.attributes.get(name))


def _absolute(base: str, href: str | None) -> str | None:
    """Resolve a possibly-relative href against the page it came from."""
    if not href:
        return None
    return urljoin(base, href)


def _is_external(href: str | None) -> bool:
    """True for absolute off-site links (used to find transcriptions and scans)."""
    if not href or not href.startswith("http"):
        return False
    return _SITE_HOST not in href and _GITHUB_HOST not in href


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------
# Note on the catalogue's honeypot: every page contains a hidden link at
# /honeypot that promises to ban the client IP for 24 hours. This project never
# requests that path: UpstreamClient refuses it (and the /text and /downloads
# trees) before opening a socket. It is not a usable block signal because the
# link text is present on every ordinary page too. Anti-bot *responses*
# (HTTP 403 and challenge interstitials) are detected in app.upstream.client.


def _require(node: Node | None, selector: str, *, context: str) -> Node:
    """Return ``node`` or raise :class:`UpstreamChanged` naming ``selector``."""
    if node is None:
        raise UpstreamChanged(selector, f"{selector} not found while parsing {context}")
    return node


# --------------------------------------------------------------------------
# Field-level parsing
# --------------------------------------------------------------------------
def _parse_reading_stats(
    text: str | None,
) -> tuple[int | None, float | None, str | None, int | None]:
    """Extract ``(word_count, reading_ease, difficulty, minutes)`` from prose.

    The catalogue prints these in two different sentences depending on the
    view, e.g. ``"40,658 words (2 hours 28 minutes) with a reading ease of
    66.57 (average difficulty)"`` and ``"33,546 words • 52.12 reading ease"``.
    """
    if not text:
        return None, None, None, None
    words = _WORDS.search(text)
    ease = _READING_EASE_TRAILING.search(text) or _READING_EASE_LEADING.search(text)
    difficulty = _DIFFICULTY.search(text)

    minutes: int | None = None
    hours_match = _HOURS_MINUTES.search(text)
    if hours_match:
        hours = int(hours_match.group(1))
        mins = int(hours_match.group(2) or 0)
        minutes = hours * 60 + mins
    else:
        minutes_match = _MINUTES.search(text)
        if minutes_match:
            minutes = int(minutes_match.group(1))

    return (
        _int(words.group(1)) if words else None,
        _float(ease.group(1)) if ease else None,
        normalise_whitespace(difficulty.group(1)) if difficulty else None,
        minutes,
    )


def _parse_authors(item: Node, base_url: str, *, detailed: bool) -> list[AuthorRef]:
    """Read the author credits of a listing row or a detail page.

    Grid rows mark the author link with ``property="schema:author"``; list rows
    drop the microdata and rely on ``p.author a`` instead. Both are read, with
    the microdata form taking precedence.
    """
    authors: list[AuthorRef] = []
    anchors = item.css('a[property="schema:author"]') or item.css("p.author a")
    for anchor in anchors:
        name = node_text(anchor.css_first(SEL_ITEM_TITLE)) or node_text(anchor)
        if not name:
            continue
        href = _attr(anchor, "href") or ""
        slug = href.rstrip("/").rsplit("/", 1)[-1] if href else ""
        same_as: list[str] = []
        if detailed:
            same_as = [
                value
                for value in (
                    _attr(meta, "content") for meta in anchor.css('meta[property="schema:sameAs"]')
                )
                if value
            ]
        authors.append(
            AuthorRef(
                name=name,
                slug=slug,
                url=_absolute(base_url, href) if href else None,
                same_as=same_as,
            )
        )
    return authors


def _parse_contributors(scope: Node) -> list[ContributorRef]:
    """Read ``<p>Translated by <a …></p>``-style credits inside ``scope``.

    Only paragraphs whose single link is off-site are treated as credits, so
    the "№ 3 in the X set" and "Part of the Y set" lines are not misread.
    """
    contributors: list[ContributorRef] = []
    for paragraph in scope.css("p"):
        link = paragraph.css_first("a")
        if link is None:
            continue
        href = _attr(link, "href") or ""
        if not href.startswith("http"):
            continue
        name = node_text(link)
        if not name:
            continue
        full = node_text(paragraph, separator=" ") or ""
        role = normalise_whitespace(full.replace(name, "")) or ""
        role = role.removesuffix(" by").strip().rstrip(".").strip()
        contributors.append(
            ContributorRef(role=role or "Contributor", name=name, url=_absolute("", href))
        )
    return contributors


def _parse_subjects(scope: Node) -> list[SubjectRef]:
    """Read ``/subjects/<slug>`` links as subject facets."""
    subjects: list[SubjectRef] = []
    for anchor in scope.css('a[href^="/subjects/"]'):
        name = node_text(anchor)
        slug = (_attr(anchor, "href") or "").rstrip("/").rsplit("/", 1)[-1]
        if name and slug:
            subjects.append(SubjectRef(name=name, slug=slug))
    return subjects


def _parse_collections(scope: Node) -> list[CollectionRef]:
    """Read ``/collections/<slug>`` links as curated sets."""
    collections: list[CollectionRef] = []
    for anchor in scope.css('a[href^="/collections/"]'):
        name = node_text(anchor)
        slug = (_attr(anchor, "href") or "").rstrip("/").rsplit("/", 1)[-1]
        if name and slug:
            collections.append(CollectionRef(name=name, slug=slug))
    return collections


def _id_from_about(about: str | None) -> str:
    """Turn ``/ebooks/a/b/c`` into the API identifier ``a/b/c``."""
    raw = (about or "").strip().strip("/")
    for prefix in ("ebooks/",):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    return raw


def _cover_url(item: Node, base_url: str) -> str | None:
    """Read the cover image of a listing row."""
    image = item.css_first('img[property="schema:image"]') or item.css_first("img")
    return _absolute(base_url, _attr(image, "src"))


# --------------------------------------------------------------------------
# Public parsers
# --------------------------------------------------------------------------
def _summary_from_item(item: Node, base_url: str, source_url: str) -> EbookSummary:
    """Parse one ``<li>`` of a catalogue listing.

    Grid rows omit word count, reading ease, subjects and contributors, so those
    fields are simply ``None`` for them - that is a real shape difference on the
    site, not a parse failure.
    """
    about = _attr(item, "about")
    ebook_id = _id_from_about(about)
    _require(item.css_first(SEL_ITEM_TITLE), SEL_ITEM_TITLE, context=f"listing item {ebook_id!r}")

    detail_area = item.css_first("div.details")
    stats_source = node_text(detail_area, separator=" ") if detail_area is not None else None
    if stats_source is None:
        stats_source = node_text(item, separator=" ") or None
    word_count, reading_ease, _difficulty, _minutes = _parse_reading_stats(stats_source)

    return EbookSummary(
        id=ebook_id,
        title=node_text(item.css_first(SEL_ITEM_TITLE)) or "",
        authors=_parse_authors(item, base_url, detailed=False),
        contributors=_parse_contributors(detail_area) if detail_area is not None else [],
        subjects=_parse_subjects(detail_area) if detail_area is not None else [],
        word_count=word_count,
        reading_ease=reading_ease,
        cover_url=_cover_url(item, base_url),
        source_url=_absolute(base_url, about) or source_url,
    )


def iter_catalog_items(html: str, *, source_url: str) -> Iterator[EbookSummary]:
    """Yield every ebook row on a catalogue listing page.

    The catalogue has two shapes for "nothing here": a listing element with no
    rows (an out-of-range page number), and a ``p.no-results`` message with no
    listing element at all (a query or filter matching nothing). Both are
    valid empty results, not errors.
    """
    tree = HTMLParser(html)
    listing = tree.css_first(SEL_CATALOG_LIST)
    if listing is None:
        _require(
            tree.css_first(SEL_CATALOG_EMPTY),
            f"{SEL_CATALOG_LIST} or {SEL_CATALOG_EMPTY}",
            context=source_url,
        )
        return
    for item in listing.css("li[about]"):
        yield _summary_from_item(item, source_url, source_url)


def parse_catalog_page(html: str, *, source_url: str) -> list[EbookSummary]:
    """Parse a whole catalogue listing page into ebook summaries."""
    return list(iter_catalog_items(html, source_url=source_url))


def parse_subject_facets(html: str, *, source_url: str) -> list[SubjectFacet]:
    """Read the subject filter options out of the catalogue's search form.

    The site has no page that lists facets on its own, so we read them from the
    one control that defines them.
    """
    tree = HTMLParser(html)
    select = _require(tree.css_first(SEL_SUBJECT_SELECT), SEL_SUBJECT_SELECT, context=source_url)
    facets: list[SubjectFacet] = []
    for option in select.css("option"):
        slug = _attr(option, "value")
        name = node_text(option)
        if slug and name and slug != "all":
            facets.append(SubjectFacet(slug=slug, name=name))
    return facets


def parse_ebook_page(html: str, *, source_url: str, base_url: str) -> EbookDetail:
    """Parse one ebook's public page into a full record.

    ``base_url`` is the page's own public URL; it is used to resolve relative
    download links and to stamp ``source_url`` onto the record.
    """
    tree = HTMLParser(html)
    article = _require(tree.css_first(SEL_DETAIL_ARTICLE), SEL_DETAIL_ARTICLE, context=source_url)
    title_node = _require(article.css_first(SEL_DETAIL_TITLE), SEL_DETAIL_TITLE, context=source_url)

    ebook_id = _id_from_about(_attr(article, "about"))
    authors = _parse_authors(article, base_url, detailed=True)
    _require(article.css_first(SEL_DETAIL_AUTHOR), SEL_DETAIL_AUTHOR, context=source_url)

    aside = article.css_first("aside#reading-ease")
    summary = node_text(aside, separator=" ") if aside is not None else None
    word_count, reading_ease, difficulty, minutes = _parse_reading_stats(summary)
    word_meta = article.css_first('meta[property="schema:wordCount"]')
    if word_count is None:
        word_count = _int(_attr(word_meta, "content"))

    description_node = article.css_first('div[property="schema:description"]')
    formats: list[FormatRef] = []
    for item in article.css('li[property="schema:encoding"]'):
        link = item.css_first('a[property="schema:contentUrl"]')
        url = _absolute(base_url, _attr(link, "href"))
        if not url:
            continue
        label = node_text(item.css_first('span[property="schema:description"]'))
        if label is None:
            label = _attr(item.css_first('meta[property="schema:description"]'), "content")
        if label is None:
            label = node_text(link)
        formats.append(
            FormatRef(
                label=normalise_whitespace(label) or "download",
                mime_type=_attr(
                    item.css_first('meta[property="schema:encodingFormat"]'), "content"
                ),
                url=url,
            )
        )

    read_online_url: str | None = None
    for anchor in article.css("a"):
        href = _attr(anchor, "href") or ""
        if href.rstrip("/").endswith("/text/single-page"):
            read_online_url = _absolute(base_url, href)
            break

    seen_sources: set[str] = set()
    sources: list[SourceRef] = []
    for anchor in article.css("a"):
        href = _attr(anchor, "href") or ""
        if not _is_external(href) or href in seen_sources:
            continue
        seen_sources.add(href)
        sources.append(SourceRef(label=node_text(anchor) or href, url=href))

    repository_slug = ebook_id.replace("/", "_")
    repository_url = f"https://github.com/standardebooks/{repository_slug}"
    anchor_hrefs = {_attr(a, "href") for a in article.css("a")}

    return EbookDetail(
        id=ebook_id,
        title=node_text(title_node) or "",
        authors=authors,
        contributors=_parse_contributors(aside) if aside is not None else [],
        subjects=_parse_subjects(aside) if aside is not None else [],
        word_count=word_count,
        reading_ease=reading_ease,
        cover_url=_cover_url(article, base_url),
        source_url=base_url,
        abstract=_attr(article.css_first('meta[property="schema:abstract"]'), "content"),
        description=node_text(description_node),
        reading_time_minutes=minutes,
        difficulty=difficulty,
        collections=_parse_collections(aside) if aside is not None else [],
        language=_attr(article.css_first('meta[property="schema:inLanguage"]'), "content"),
        license=_attr(article.css_first('meta[property="schema:license"]'), "content"),
        published_at=_attr(article.css_first('meta[property="schema:datePublished"]'), "content"),
        updated_at=_attr(article.css_first('meta[property="schema:dateModified"]'), "content"),
        formats=formats,
        read_online_url=read_online_url,
        sources=sources,
        source_repository_url=repository_url if repository_url in anchor_hrefs else None,
    )
