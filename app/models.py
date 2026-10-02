"""Pydantic response models.

These are the public contract of the bridge. They are deliberately independent
of the target site's markup: if Standard Ebooks renames a CSS class or drops a
``<meta>`` tag, only :mod:`app.upstream.parsers` changes. Consumers of this API
see the same shapes before and after.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.errors import BAD_REQUEST, NOT_FOUND, RATE_LIMITED, UPSTREAM_BLOCKED, UPSTREAM_CHANGED

T = TypeVar("T")


# --------------------------------------------------------------------------
# Shared value objects
# --------------------------------------------------------------------------
class AuthorRef(BaseModel):
    """An ebook author, as named on the public catalogue page."""

    name: str = Field(description="Display name of the author.")
    slug: str = Field(description="URL-safe author slug, used as the author filter value.")
    url: str | None = Field(default=None, description="Canonical public page for this author.")
    same_as: list[str] = Field(
        default_factory=list,
        description=(
            "Authority links the catalogue publishes, e.g. Library of Congress or Wikipedia."
        ),
    )


class ContributorRef(BaseModel):
    """A secondary credit such as translator, illustrator or editor."""

    role: str = Field(description="Credit as printed, e.g. 'Translated'.")
    name: str = Field(description="Name of the contributor.")
    url: str | None = Field(default=None, description="Link the catalogue publishes for them.")


class SubjectRef(BaseModel):
    """A subject facet, used both as a filter value and as metadata."""

    name: str = Field(description="Display name of the subject, e.g. 'Science Fiction'.")
    slug: str = Field(description="URL-safe subject slug, e.g. 'science-fiction'.")


class CollectionRef(BaseModel):
    """A curated set an ebook belongs to, e.g. 'The Oresteia'."""

    name: str = Field(description="Display name of the collection.")
    slug: str = Field(description="URL-safe collection slug.")


class FormatRef(BaseModel):
    """One downloadable rendition of an ebook.

    We publish the link the catalogue lists; we never download the file.
    """

    label: str = Field(description="Label used on the page, e.g. 'Compatible epub'.")
    mime_type: str | None = Field(default=None, description="IANA media type.")
    url: str = Field(description="Absolute URL of the file.")


class SourceRef(BaseModel):
    """An upstream transcription or scan the catalogue credits."""

    label: str = Field(description="Anchor text of the credit.")
    url: str = Field(description="Absolute URL of the credited page.")


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------
class EbookSummary(BaseModel):
    """One ebook as it appears in a listing or search result."""

    id: str = Field(
        description="Stable identifier, e.g. 'edwin-a-abbott/flatland'. "
        "Pass it to GET /v1/ebooks/{ebook_id}."
    )
    title: str = Field(description="Title of the ebook.")
    authors: list[AuthorRef] = Field(description="Authors, in publication order.")
    contributors: list[ContributorRef] = Field(
        default_factory=list, description="Translators, illustrators and editors. May be empty."
    )
    subjects: list[SubjectRef] = Field(
        default_factory=list,
        description="Subject facets. Empty in grid views, where the site omits them.",
    )
    word_count: int | None = Field(default=None, description="Word count, or null if not listed.")
    reading_ease: float | None = Field(
        default=None, description="Reading-ease score, or null if not listed."
    )
    cover_url: str | None = Field(default=None, description="Cover image URL, or null.")
    source_url: str = Field(description="Public page this record was parsed from.")


class EbookDetail(EbookSummary):
    """The full record for one ebook."""

    abstract: str | None = Field(
        default=None, description="One-sentence summary, or null when the catalogue omits it."
    )
    description: str | None = Field(
        default=None, description="Long-form description, or null when the catalogue omits it."
    )
    reading_time_minutes: int | None = Field(
        default=None, description="Estimated reading time in minutes, or null."
    )
    difficulty: str | None = Field(
        default=None, description="Site's difficulty band, e.g. 'easy' or 'average difficulty'."
    )
    collections: list[CollectionRef] = Field(
        default_factory=list, description="Sets it belongs to."
    )
    language: str | None = Field(default=None, description="BCP 47 language tag, e.g. 'en-GB'.")
    license: str | None = Field(
        default=None, description="Licence URL the catalogue publishes for the file."
    )
    published_at: str | None = Field(
        default=None, description="Date this edition was first released (ISO 8601 date)."
    )
    updated_at: str | None = Field(
        default=None, description="Date this edition was last modified (ISO 8601 date)."
    )
    formats: list[FormatRef] = Field(
        default_factory=list, description="Downloadable renditions listed on the page."
    )
    read_online_url: str | None = Field(
        default=None, description="Public page that renders the whole book in the browser."
    )
    sources: list[SourceRef] = Field(
        default_factory=list, description="Transcription or scan sources credited by the site."
    )
    source_repository_url: str | None = Field(
        default=None, description="Public source repository for this edition."
    )


class SubjectFacet(BaseModel):
    """A subject the catalogue can filter on."""

    slug: str = Field(description="Value to pass as ?subject=.")
    name: str = Field(description="Display name of the subject.")


# --------------------------------------------------------------------------
# Envelope and errors
# --------------------------------------------------------------------------
class Meta(BaseModel):
    """Provenance for every response, successful or not."""

    page: int | None = Field(default=None, description="1-based page number, null if not paged.")
    page_size: int | None = Field(
        default=None, description="Page size honoured, null if not paged."
    )
    total: int | None = Field(
        default=None,
        description="Total matching records when the upstream site exposes it, otherwise null. "
        "The Standard Ebooks catalogue does not publish a total, so this is usually null.",
    )
    source_url: str | None = Field(
        default=None, description="Public upstream page the data was read from."
    )
    fetched_at: str = Field(description="When this payload was produced (ISO 8601, UTC).")
    cached: bool = Field(
        description="True when served from the local response cache without hitting the site."
    )


class Envelope(BaseModel, Generic[T]):
    """The single success shape: a payload plus its provenance."""

    data: T = Field(description="The result.")
    meta: Meta = Field(description="Provenance and pagination metadata.")


class ErrorDetail(BaseModel):
    """The ``error`` object carried by every failure."""

    code: str = Field(
        description=f"One of {BAD_REQUEST}, {NOT_FOUND}, {RATE_LIMITED}, "
        f"{UPSTREAM_BLOCKED}, {UPSTREAM_CHANGED}."
    )
    message: str = Field(description="Human-readable explanation safe to show a caller.")
    retryable: bool = Field(description="True when repeating the same request may succeed.")


class ErrorResponse(BaseModel):
    """The single failure shape."""

    error: ErrorDetail = Field(description="What went wrong.")


class HealthData(BaseModel):
    """Service health plus a live, cache-aware probe of the target site."""

    status: str = Field(description="'ok' when the site answered, 'degraded' when it did not.")
    upstream_reachable: bool = Field(description="Whether the target site answered the probe.")
    circuit_breaker: str = Field(description="'closed', 'open' or 'half_open'.")
    upstream_check_url: str = Field(description="Public URL used for the probe.")
    service_version: str = Field(description="Version of this bridge.")
