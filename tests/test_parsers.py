"""Parser tests, run entirely against the recorded fixtures.

Every assertion here is about the *shape* of the markup we depend on, so a
failure means either the site changed or our selectors did.
"""

from __future__ import annotations

import pytest
from selectolax.parser import HTMLParser

from app.errors import UpstreamChanged
from app.upstream import parsers
from tests.conftest import fixture_html

PAGE_1_URL = "https://standardebooks.org/ebooks?view=list&per-page=12&page=1"
OBERLAND_URL = "https://standardebooks.org/ebooks/dorothy-m-richardson/oberland"
IMITATION_URL = (
    "https://standardebooks.org/ebooks/thomas-a-kempis/the-imitation-of-christ/william-benham"
)


# --------------------------------------------------------------------- listing
def test_listing_page_yields_twelve_summaries() -> None:
    items = parsers.parse_catalog_page(fixture_html("catalog_page_1"), source_url=PAGE_1_URL)
    assert len(items) == 12


def test_listing_rows_carry_id_title_author_and_source_url() -> None:
    items = parsers.parse_catalog_page(fixture_html("catalog_page_1"), source_url=PAGE_1_URL)
    first = items[0]
    assert first.id == "dorothy-m-richardson/oberland"
    assert first.title == "Oberland"
    assert [author.slug for author in first.authors] == ["dorothy-m-richardson"]
    assert first.source_url == OBERLAND_URL


def test_listing_resolves_relative_cover_urls_against_the_request() -> None:
    items = parsers.parse_catalog_page(fixture_html("catalog_page_1"), source_url=PAGE_1_URL)
    for item in items:
        assert item.cover_url is None or item.cover_url.startswith("https://")


def test_listing_reads_subjects_word_counts_and_reading_ease() -> None:
    items = parsers.parse_catalog_page(fixture_html("catalog_page_1"), source_url=PAGE_1_URL)
    first = items[0]
    assert [(ref.name, ref.slug) for ref in first.subjects] == [("Fiction", "fiction")]
    assert first.word_count == 40658
    assert first.reading_ease == pytest.approx(66.57)


def test_listing_rows_expose_contributors_when_present() -> None:
    items = parsers.parse_catalog_page(fixture_html("catalog_page_12"), source_url=PAGE_1_URL)
    contributors = [ref for item in items for ref in item.contributors]
    assert contributors, "expected at least one listing row with a contributor"
    assert any(
        ref.role.lower().startswith(("translat", "edited", "illustr")) for ref in contributors
    )


def test_pages_differ_so_pagination_is_real() -> None:
    page_1 = parsers.parse_catalog_page(fixture_html("catalog_page_1"), source_url=PAGE_1_URL)
    page_2 = parsers.parse_catalog_page(fixture_html("catalog_page_2"), source_url=PAGE_1_URL)
    assert {item.id for item in page_1}.isdisjoint({item.id for item in page_2})


def test_subject_filter_page_is_parsed_like_any_listing() -> None:
    items = parsers.parse_catalog_page(
        fixture_html("catalog_subject_drama"),
        source_url="https://standardebooks.org/ebooks?view=list&per-page=12&tags%5B%5D=drama",
    )
    assert items
    assert any("drama" in {ref.slug for ref in item.subjects} for item in items)


def test_search_results_are_parsed() -> None:
    items = parsers.parse_catalog_page(
        fixture_html("catalog_search_shakespeare"),
        source_url="https://standardebooks.org/ebooks?view=list&per-page=12&query=shakespeare",
    )
    assert len(items) == 12
    # The catalogue also matches on titles and contributor credits, so results
    # are not limited to books by the author being searched for.
    assert any(item.id.startswith("william-shakespeare/") for item in items)
    assert any("shakespeare" in item.id or "shakespeare" in item.title.lower() for item in items)


def test_no_results_message_parses_to_an_empty_list() -> None:
    items = parsers.parse_catalog_page(
        fixture_html("catalog_search_empty"),
        source_url="https://standardebooks.org/ebooks?view=list&per-page=12&query=zzzqqqxyzzy",
    )
    assert items == []


def test_out_of_range_page_clamps_to_the_last_page() -> None:
    """A page number past the end is clamped upstream, not treated as empty.

    This is a real quirk of the target: ``?page=9999`` answers with the final
    page (2 rows here) instead of 404 or an empty list, so a caller cannot use
    "past the end" to probe the catalogue depth. Recorded in RECON.md.
    """
    html = fixture_html("catalog_page_out_of_range")
    tree = HTMLParser(html)
    nav = tree.css_first("nav.pagination")
    assert nav is not None, "an out-of-range page still renders the pagination strip"
    assert nav.css_first('a[aria-current="page"]') is not None

    items = parsers.parse_catalog_page(
        html, source_url="https://standardebooks.org/ebooks?view=list&per-page=12&page=9999"
    )
    assert len(items) == 2
    assert items[-1].id == "agatha-christie/the-mysterious-affair-at-styles"


# ---------------------------------------------------------------------- detail
def test_detail_reads_identity_description_and_licence() -> None:
    detail = parsers.parse_ebook_page(
        fixture_html("ebook_oberland"), source_url=OBERLAND_URL, base_url=OBERLAND_URL
    )
    assert detail.id == "dorothy-m-richardson/oberland"
    assert detail.title == "Oberland"
    assert detail.language == "en-GB"
    assert detail.license == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert detail.description
    assert detail.abstract


def test_detail_reads_authors_and_their_external_identifiers() -> None:
    detail = parsers.parse_ebook_page(
        fixture_html("ebook_oberland"), source_url=OBERLAND_URL, base_url=OBERLAND_URL
    )
    author = detail.authors[0]
    assert author.name == "Dorothy M. Richardson"
    assert author.slug == "dorothy-m-richardson"
    assert any("wikipedia.org" in link for link in author.same_as)


def test_detail_reads_a_three_segment_identifier() -> None:
    detail = parsers.parse_ebook_page(
        fixture_html("ebook_imitation_of_christ"),
        source_url=IMITATION_URL,
        base_url=IMITATION_URL,
    )
    assert detail.id == "thomas-a-kempis/the-imitation-of-christ/william-benham"


def test_detail_reads_contributors_with_roles() -> None:
    detail = parsers.parse_ebook_page(
        fixture_html("ebook_imitation_of_christ"),
        source_url=IMITATION_URL,
        base_url=IMITATION_URL,
    )
    assert [(ref.role, ref.name) for ref in detail.contributors] == [
        ("Translated by", "William Benham")
    ]


def test_detail_reads_download_formats_with_absolute_urls() -> None:
    detail = parsers.parse_ebook_page(
        fixture_html("ebook_flatland"), source_url="", base_url="https://standardebooks.org"
    )
    labels = {fmt.label for fmt in detail.formats}
    assert {"epub", "azw3", "kepub"} <= labels
    for fmt in detail.formats:
        assert fmt.url.startswith("https://")


def test_detail_computes_reading_time_and_difficulty() -> None:
    detail = parsers.parse_ebook_page(
        fixture_html("ebook_oberland"), source_url=OBERLAND_URL, base_url=OBERLAND_URL
    )
    assert detail.reading_time_minutes == 148
    assert detail.difficulty == "average difficulty"
    assert detail.reading_ease == pytest.approx(66.57)


def test_detail_exposes_provenance_links() -> None:
    detail = parsers.parse_ebook_page(
        fixture_html("ebook_oberland"), source_url=OBERLAND_URL, base_url=OBERLAND_URL
    )
    assert detail.source_repository_url == (
        "https://github.com/standardebooks/dorothy-m-richardson_oberland"
    )
    assert any("gutenberg.org" in source.url for source in detail.sources)


# ---------------------------------------------------------------- author pages
def test_author_page_lists_every_ebook() -> None:
    items = parsers.parse_catalog_page(
        fixture_html("author_dorothy_m_richardson"),
        source_url="https://standardebooks.org/ebooks/dorothy-m-richardson",
    )
    assert len(items) == 13
    assert all(item.id.startswith("dorothy-m-richardson/") for item in items)


def test_author_page_rows_are_grid_mode_and_so_carry_no_stats() -> None:
    html = fixture_html("author_dorothy_m_richardson")
    tree = HTMLParser(html)
    assert tree.css_first("ol.ebooks-list.grid") is not None
    items = parsers.parse_catalog_page(
        html, source_url="https://standardebooks.org/ebooks/dorothy-m-richardson"
    )
    assert all(item.word_count is None and not item.subjects for item in items)


# --------------------------------------------------------------------- facets
def test_subject_facets_are_read_from_the_filter_form() -> None:
    facets = parsers.parse_subject_facets(fixture_html("catalog_page_1"), source_url=PAGE_1_URL)
    slugs = [facet.slug for facet in facets]
    assert slugs[:3] == ["adventure", "autobiography", "biography"]
    assert "science-fiction" in slugs
    assert "all" not in slugs, "the 'All' option is not a real facet"
    for facet in facets:
        assert facet.name and facet.slug == facet.slug.lower()


def test_subject_names_keep_their_printable_punctuation() -> None:
    facets = parsers.parse_subject_facets(fixture_html("catalog_page_1"), source_url=PAGE_1_URL)
    names = {facet.slug: facet.name for facet in facets}
    assert names["childrens"] == "Children\u2019s"
    assert names["science-fiction"] == "Science Fiction"


# ----------------------------------------------------------------- drift guard
def test_unrelated_html_is_reported_as_upstream_changed() -> None:
    with pytest.raises(UpstreamChanged):
        parsers.parse_catalog_page("<html><body>nope</body></html>", source_url="x")


def test_missing_detail_section_is_reported_as_upstream_changed() -> None:
    with pytest.raises(UpstreamChanged):
        parsers.parse_ebook_page(
            "<html><body><p>hello</p></body></html>",
            source_url="https://standardebooks.org/ebooks/a/b",
            base_url="https://standardebooks.org",
        )


def test_missing_subject_form_is_reported_as_upstream_changed() -> None:
    with pytest.raises(UpstreamChanged):
        parsers.parse_subject_facets("<html><body>no form</body></html>", source_url="x")


def test_drift_error_names_the_missing_selector() -> None:
    with pytest.raises(UpstreamChanged) as caught:
        parsers.parse_catalog_page("<html><body>nope</body></html>", source_url="x")
    assert "ebooks-list" in caught.value.element
