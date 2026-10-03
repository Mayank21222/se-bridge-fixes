"""FastAPI application: routes, response models and exception handlers.

Two rules shape this module:

* every success returns the same ``{data, meta}`` envelope;
* every failure returns the same ``{"error": {...}}`` body, with one of five
  codes, and never a stack trace or an internal detail.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import configure_logging, get_settings
from app.errors import ERROR_STATUS, ApiError, UpstreamChanged, UpstreamError
from app.models import (
    EbookDetail,
    EbookSummary,
    Envelope,
    ErrorDetail,
    ErrorResponse,
    SubjectFacet,
)
from app.services.catalog import CatalogService, ServiceResult, error_code_for
from app.upstream.client import UpstreamClient, get_client

logger = logging.getLogger("app.main")

DESCRIPTION = """
A read-only JSON bridge over the public [Standard Ebooks](https://standardebooks.org)
catalogue, which publishes no API. Responses always use the same envelope:

```json
{"data": ..., "meta": {"page": 1, "page_size": 12, "total": null,
                       "source_url": "https://standardebooks.org/ebooks?...",
                       "fetched_at": "2026-01-01T00:00:00Z", "cached": false}}
```

Failures always use `{"error": {"code": ..., "message": ..., "retryable": ...}}`
with one of `BAD_REQUEST` (400), `NOT_FOUND` (404), `RATE_LIMITED` (429),
`UPSTREAM_BLOCKED` (502) and `UPSTREAM_CHANGED` (502).
"""

TAGS = [
    {"name": "service", "description": "Liveness of this bridge and of the target site."},
    {"name": "catalog", "description": "Browse the public ebook catalogue."},
    {"name": "records", "description": "Fetch a single record by identifier."},
    {"name": "search", "description": "Full-text search over the catalogue."},
    {"name": "facets", "description": "Filter values published by the catalogue."},
]


def _service(client: Annotated[UpstreamClient, Depends(get_client)]) -> CatalogService:
    """Build a service bound to the shared upstream client."""
    return CatalogService(client=client)


def envelope(result: ServiceResult, data: Any) -> JSONResponse:
    """Render a successful response in the project's single success shape."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=Envelope(data=data, meta=result.to_meta()).model_dump(mode="json"),
    )


def error_response(code: str, message: str, retryable: bool) -> JSONResponse:
    """Render a failure in the project's single failure shape."""
    return JSONResponse(
        status_code=ERROR_STATUS[code],
        content=ErrorResponse(
            error=ErrorDetail(code=code, message=message, retryable=retryable)
        ).model_dump(mode="json"),
    )


def create_app() -> FastAPI:
    """Build the ASGI application with all handlers registered."""
    configure_logging()
    application = FastAPI(
        title="Standard Ebooks Bridge",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        responses={
            400: {"model": ErrorResponse, "description": "Invalid or missing parameters"},
            404: {"model": ErrorResponse, "description": "No such record"},
            429: {"model": ErrorResponse, "description": "Throttled locally or by the site"},
            502: {"model": ErrorResponse, "description": "Upstream blocked or changed"},
        },
    )
    _orig_openapi = application.openapi

    def _openapi_override() -> dict:
        schema = _orig_openapi()
        for methods in schema.get("paths", {}).values():
            for spec in methods.values():
                if isinstance(spec, dict):
                    spec.setdefault("responses", {}).pop("422", None)
        return schema

    object.__setattr__(application, "openapi", _openapi_override)

    # ---------------------------------------------------------------- errors
    @application.exception_handler(ApiError)
    def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.retryable)

    @application.exception_handler(UpstreamError)
    def _handle_upstream_error(request: Request, exc: UpstreamError) -> JSONResponse:
        code, message, retryable = error_code_for(exc)
        if isinstance(exc, UpstreamChanged):
            # Name the missing element in the log, not just the code: this is
            # the one error a maintainer acts on, and the selector is what
            # points at the single parser function to fix.
            logger.error(
                "upstream structure changed on %s %s: %s is missing",
                request.method,
                request.url.path,
                exc.element,
            )
        else:
            logger.warning("%s %s -> %s: %s", request.method, request.url.path, code, message)
        return error_response(code, message, retryable)

    @application.exception_handler(StarletteHTTPException)
    def _handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Framework-level 404s (an unknown route, or a path that no route
        # matches) must look exactly like every other failure this API returns.
        if exc.status_code == 404:
            return error_response("NOT_FOUND", "no such endpoint or record", retryable=False)
        if exc.status_code == 405:
            return error_response("BAD_REQUEST", "method not allowed on this path", retryable=False)
        return error_response(
            "RATE_LIMITED", f"the request could not be completed (HTTP {exc.status_code})", True
        )

    @application.exception_handler(RequestValidationError)
    def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else None
        field = ".".join(str(part) for part in first["loc"]) if first else "request"
        message = f"{field}: {first.get('msg', 'invalid value')}" if first else "invalid request"
        return error_response("BAD_REQUEST", message, retryable=False)

    @application.exception_handler(Exception)
    def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The fixed five-code vocabulary has no "internal error" member, so an
        # unhandled failure is reported as the one retryable code we have.
        # The traceback goes to the log, never to the caller.
        logger.error("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return error_response(
            "RATE_LIMITED",
            "the request could not be completed; retry later",
            retryable=True,
        )

    # ---------------------------------------------------------------- routes
    @application.get("/health", tags=["service"], summary="Service and upstream health")
    def health(service: Annotated[CatalogService, Depends(_service)]) -> JSONResponse:
        """Report whether this service is up and whether the site answered.

        Always answers 200. A site that cannot be reached sets
        `data.upstream_reachable` to false and `data.status` to `degraded`.
        The probe goes through the same cache, rate limit and circuit breaker
        as any other call, so polling this endpoint cannot overload anything.
        """
        data, result = service.health()
        return envelope(result, data)

    @application.get(
        "/v1/ebooks",
        tags=["catalog"],
        summary="List catalogue entries",
        response_model=Envelope[list[EbookSummary]],
    )
    def list_ebooks(
        service: Annotated[CatalogService, Depends(_service)],
        page: Annotated[int, Query(description="1-based page number. Must be 1 or greater.")] = 1,
        page_size: Annotated[
            int,
            Query(
                description=(
                    "Items per page, at least 1. The ceiling is SE_BRIDGE_MAX_PAGE_SIZE "
                    "(48 by default); anything larger is rejected with BAD_REQUEST."
                )
            ),
        ] = get_settings().default_page_size,
        subject: Annotated[
            str | None,
            Query(
                description=(
                    "Subject slug, e.g. 'science-fiction'. "
                    "An unknown but well-formed slug returns an empty page."
                )
            ),
        ] = None,
        sort: Annotated[
            str | None,
            Query(
                description=(
                    "One of: newest (default), author-alpha, reading-ease, length, popularity. "
                    "'relevance' is search-only; see /v1/search."
                )
            ),
        ] = None,
    ) -> JSONResponse:
        """Return one page of the public catalogue, newest first by default."""
        result = service.list_ebooks(page=page, page_size=page_size, subject=subject, sort=sort)
        return envelope(result, result.items)

    @application.get(
        "/v1/search",
        tags=["search"],
        summary="Search the catalogue",
        response_model=Envelope[list[EbookSummary]],
    )
    def search_ebooks(
        service: Annotated[CatalogService, Depends(_service)],
        q: Annotated[str, Query(description="Free-text query. Must not be blank.")],
        page: Annotated[int, Query(description="1-based page number. Must be 1 or greater.")] = 1,
        page_size: Annotated[
            int,
            Query(ge=1, description="Items per page."),
        ] = get_settings().default_page_size,
        subject: Annotated[str | None, Query(description="Subject slug filter.")] = None,
        sort: Annotated[
            str | None,
            Query(
                description=(
                    "One of: relevance, newest, author-alpha, reading-ease, length, popularity."
                )
            ),
        ] = None,
    ) -> JSONResponse:
        """Return catalogue entries matching `q`.

        A query that matches nothing is a 200 with an empty `data` list, not an
        error.
        """
        result = service.search_ebooks(
            query=q, page=page, page_size=page_size, subject=subject, sort=sort
        )
        return envelope(result, result.items)

    @application.get(
        "/v1/ebooks/{ebook_id:path}",
        tags=["records"],
        summary="Fetch one ebook",
        response_model=Envelope[EbookDetail],
    )
    def get_ebook(
        service: Annotated[CatalogService, Depends(_service)],
        ebook_id: str,
    ) -> JSONResponse:
        """Return the full record for one ebook.

        The identifier mirrors the site's own path, e.g.
        `edwin-a-abbott/flatland` or
        `thomas-a-kempis/the-imitation-of-christ/william-benham`.
        """
        result = service.get_ebook(ebook_id)
        return envelope(result, result.items)

    @application.get(
        "/v1/subjects",
        tags=["facets"],
        summary="List subject facets",
        response_model=Envelope[list[SubjectFacet]],
    )
    def list_subjects(
        service: Annotated[CatalogService, Depends(_service)],
    ) -> JSONResponse:
        """Return every subject slug accepted by the `subject` filter."""
        result = service.list_subjects()
        return envelope(result, result.items)

    @application.get(
        "/v1/authors/{author_slug}",
        tags=["records"],
        summary="List every ebook by one author",
        response_model=Envelope[list[EbookSummary]],
    )
    def list_author_ebooks(
        service: Annotated[CatalogService, Depends(_service)],
        author_slug: str,
    ) -> JSONResponse:
        """Return all catalogue entries for one author.

        The site's author page is a single unpaginated page, so this response
        is always page 1 with a real `meta.total`.
        """
        result = service.list_author_ebooks(author_slug)
        return envelope(result, result.items)

    return application


app = create_app()


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    """Point a browser that lands on `/` at the interactive docs."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "service": "standard-ebooks-bridge",
            "version": __version__,
            "docs": "/docs",
            "openapi": "/openapi.json",
            "health": "/health",
        },
    )


def main() -> None:  # pragma: no cover - entry point only
    """Run the app with uvicorn: ``python -m app.main``."""
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":  # pragma: no cover
    main()
