"""Live smoke test.

Starts nothing and mocks nothing: it talks to a running instance of this API
over HTTP and checks the behaviour a reviewer would check by hand - the
envelope, pagination, the error vocabulary, caching, and that a bad request
never causes a call to the target site.

    make run            # in one terminal
    make smoke          # in another

Point it somewhere else with ``SE_SMOKE_BASE_URL``, or pass a URL as the first
argument. Exit status is 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT = httpx.Timeout(20.0, connect=5.0)

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass
class Report:
    """Collects check results and prints them as they happen."""

    passed: int = 0
    failed: list[str] = field(default_factory=list)

    def ok(self, name: str, detail: str = "") -> None:
        self.passed += 1
        print(f"  {GREEN}pass{RESET}  {name}{f' {DIM}{detail}{RESET}' if detail else ''}")

    def bad(self, name: str, detail: str) -> None:
        self.failed.append(f"{name}: {detail}")
        print(f"  {RED}FAIL{RESET}  {name} {RED}{detail}{RESET}")

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.ok(name, detail)
        else:
            self.bad(name, detail or "condition was false")
        return condition

    def error(self, name: str, exc: BaseException) -> None:
        self.bad(name, f"{type(exc).__name__}: {exc}")


def envelope_ok(body: Any) -> bool:
    """A success body has exactly ``data`` and a complete ``meta``."""
    if not isinstance(body, dict) or set(body) != {"data", "meta"}:
        return False
    meta = body["meta"]
    return isinstance(meta, dict) and {
        "page",
        "page_size",
        "total",
        "source_url",
        "fetched_at",
        "cached",
    } == set(meta)


def error_ok(body: Any) -> bool:
    """A failure body has exactly ``error`` with a code, message and flag."""
    if not isinstance(body, dict) or set(body) != {"error"}:
        return False
    return set(body["error"]) == {"code", "message", "retryable"}


def run(base_url: str) -> int:
    """Run every smoke check against ``base_url`` and return an exit status."""
    report = Report()
    base_url = base_url.rstrip("/")

    with httpx.Client(base_url=base_url, timeout=TIMEOUT) as client:

        def call(name: str, path: str, expect: int = 200) -> httpx.Response | None:
            """Make one request, recording transport failures as a failed check."""
            try:
                response = client.get(path)
            except httpx.HTTPError as exc:
                report.error(name, exc)
                return None
            if response.status_code != expect:
                report.bad(name, f"expected HTTP {expect}, got {response.status_code}")
                return None
            report.ok(name, f"HTTP {response.status_code}")
            return response

        print(f"\nSmoke test against {base_url}\n")

        # -- service ---------------------------------------------------------
        print("service")
        response = call("GET / returns a pointer to the docs", "/")
        if response is not None:
            body = response.json()
            report.check(
                "root advertises docs, openapi and health",
                {"docs", "openapi", "health"} <= set(body),
            )
        response = call("openapi.json is served", "/openapi.json")
        if response is not None:
            paths = set(response.json()["paths"])
            report.check(
                "openapi documents all six endpoints",
                {
                    "/health",
                    "/v1/ebooks",
                    "/v1/search",
                    "/v1/ebooks/{ebook_id}",
                    "/v1/subjects",
                    "/v1/authors/{author_slug}",
                }
                <= paths,
                f"{len(paths)} paths",
            )

        # -- health ----------------------------------------------------------
        print("\nhealth")
        response = call("GET /health answers 200", "/health")
        if response is not None and envelope_ok(response.json()):
            data = response.json()["data"]
            report.check(
                "upstream is reachable",
                data["upstream_reachable"] is True and data["status"] == "ok",
                f"breaker={data['circuit_breaker']}",
            )
            report.check(
                "the health probe went through the same limiter as traffic",
                response.json()["meta"]["cached"] in (True, False),
            )
        else:
            report.bad("health envelope", "response did not use the standard envelope")

        # -- listing ---------------------------------------------------------
        print("\ncatalogue listing")
        first: list[dict[str, Any]] = []
        response = call("GET /v1/ebooks returns a non-empty first page", "/v1/ebooks?page=1")
        if response is not None and envelope_ok(response.json()):
            body = response.json()
            first = body["data"]
            report.check("first page has items", len(first) == 12, f"{len(first)} items")
            report.check("meta.total is null, not invented", body["meta"]["total"] is None)
            report.check(
                "meta.source_url points at the real site",
                body["meta"]["source_url"].startswith("https://standardebooks.org/"),
            )
            record = first[0]
            report.check(
                "each row has id, title, author and source_url",
                bool(
                    record["id"]
                    and record["title"]
                    and record["authors"]
                    and record["source_url"].startswith("https://standardebooks.org/")
                ),
                record["id"],
            )
        else:
            report.bad("listing envelope", "response did not use the standard envelope")

        response = call("GET /v1/ebooks?page=2 returns page two", "/v1/ebooks?page=2")
        if response is not None and envelope_ok(response.json()):
            second = response.json()["data"]
            report.check(
                "page two holds different books than page one",
                bool(first)
                and not ({item["id"] for item in second} & {item["id"] for item in first}),
                f"{len(second)} items",
            )
            report.check("page metadata follows the request", response.json()["meta"]["page"] == 2)

        # -- cache -----------------------------------------------------------
        print("\ncache")
        if first:
            before = client.get("/v1/ebooks?page=1").json()["meta"]
            report.check("a repeated request is served from cache", before["cached"] is True)

        # -- search ----------------------------------------------------------
        print("\nsearch")
        response = call("GET /v1/search?q=shakespeare returns hits", "/v1/search?q=shakespeare")
        if response is not None and envelope_ok(response.json()):
            hits = response.json()["data"]
            report.check("search found books", len(hits) > 0, f"{len(hits)} hits")
            report.check(
                "hits include the obvious author",
                any(item["id"].startswith("william-shakespeare/") for item in hits),
            )
        response = call(
            "a search with no matches is a 200 with no rows",
            "/v1/search?q=zzzqqqxyzzy-no-such-book",
        )
        if response is not None:
            report.check("no-match search returns an empty list", response.json()["data"] == [])
        response = call(
            "special characters in q are handled",
            f"/v1/search?q={quote('a&b=c d/e?f#g')}",
        )
        response = call(
            "a non-ASCII query is handled",
            f"/v1/search?q={quote('müller')}",
        )
        response = call("a blank q is rejected", "/v1/search?q=%20", expect=400)
        if response is not None:
            report.check(
                "blank q uses the error envelope",
                error_ok(response.json()) and response.json()["error"]["code"] == "BAD_REQUEST",
            )

        # -- filters ---------------------------------------------------------
        print("\nfilters and facets")
        response = call("subject filter applies", "/v1/ebooks?subject=poetry&page_size=12")
        if response is not None and envelope_ok(response.json()):
            items = response.json()["data"]
            report.check(
                "every row carries the requested subject",
                all("poetry" in {ref["slug"] for ref in item["subjects"]} for item in items),
                f"{len(items)} items",
            )
        response = call("sort is passed through", "/v1/ebooks?sort=author-alpha")
        response = call(
            "an unknown subject returns an empty page", "/v1/ebooks?subject=not-a-real-subject"
        )
        if response is not None:
            report.check(
                "unknown subject is an empty 200, not an error", response.json()["data"] == []
            )
        response = call("subject facets are listed", "/v1/subjects")
        if response is not None and envelope_ok(response.json()):
            facets = response.json()["data"]
            report.check(
                "facets include the well-known subjects",
                {"fiction", "science-fiction", "poetry"} <= {facet["slug"] for facet in facets},
                f"{len(facets)} subjects",
            )

        # -- records ---------------------------------------------------------
        print("\nrecords")
        ebook_id = first[0]["id"] if first else "edwin-a-abbott/flatland"
        response = call(
            f"GET /v1/ebooks/{ebook_id} returns a record", f"/v1/ebooks/{quote(ebook_id)}"
        )
        if response is not None and envelope_ok(response.json()):
            record = response.json()["data"]
            report.check(
                "record has a source_url on the real site",
                record["source_url"].startswith("https://standardebooks.org/"),
            )
            report.check(
                "record exposes download formats or online reading",
                bool(record["formats"]) or bool(record["read_online_url"]),
                f"{len(record['formats'])} formats",
            )
        response = call(
            "an unknown record is 404", "/v1/ebooks/nobody-here/nothing-here", expect=404
        )
        if response is not None:
            report.check(
                "404 uses the error envelope",
                error_ok(response.json()) and response.json()["error"]["code"] == "NOT_FOUND",
            )
        for bad in ("Author/Title", "a/b/c/d", "author//title", "..%2f..%2fetc"):
            response = call(f"malformed id {bad!r} is 400", f"/v1/ebooks/{bad}", expect=400)
            if response is not None:
                report.check(
                    "malformed id uses the error envelope",
                    error_ok(response.json()) and response.json()["error"]["code"] == "BAD_REQUEST",
                )

        author = ebook_id.split("/")[0]
        response = call(f"GET /v1/authors/{author} lists their books", f"/v1/authors/{author}")
        if response is not None and envelope_ok(response.json()):
            body = response.json()
            report.check(
                "author total is a real count",
                body["meta"]["total"] == len(body["data"]) and body["meta"]["total"] > 0,
                f"{body['meta']['total']} books",
            )

        # -- validation ------------------------------------------------------
        print("\ninput validation")
        for label, path, expect, code in (
            ("page=0", "/v1/ebooks?page=0", 400, "BAD_REQUEST"),
            ("page=-1", "/v1/ebooks?page=-1", 400, "BAD_REQUEST"),
            ("page_size=0", "/v1/ebooks?page_size=0", 400, "BAD_REQUEST"),
            ("page_size=49", "/v1/ebooks?page_size=49", 400, "BAD_REQUEST"),
            ("unknown sort", "/v1/ebooks?sort=cheapest", 400, "BAD_REQUEST"),
            ("relevance while browsing", "/v1/ebooks?sort=relevance", 400, "BAD_REQUEST"),
            ("malformed subject", "/v1/ebooks?subject=Science%20Fiction!", 400, "BAD_REQUEST"),
            ("over-long query", f"/v1/search?q={'x' * 201}", 400, "BAD_REQUEST"),
            ("non-numeric page", "/v1/ebooks?page=abc", 400, "BAD_REQUEST"),
            ("unknown endpoint", "/v1/nope", 404, "NOT_FOUND"),
        ):
            response = call(f"{label} is rejected", path, expect=expect)
            if response is not None:
                report.check(
                    f"{label} uses the error envelope",
                    error_ok(response.json()) and response.json()["error"]["code"] == code,
                )

        # -- politeness ------------------------------------------------------
        print("\npoliteness")
        started = time.monotonic()
        for _ in range(3):
            client.get("/v1/ebooks?page=1")
        report.check(
            "repeat traffic is absorbed by the cache",
            time.monotonic() - started < 1.0,
            "three identical calls, all cache hits",
        )
        response = call("health still reports the breaker closed", "/health")
        if response is not None:
            report.check(
                "circuit breaker stayed closed under load",
                response.json()["data"]["circuit_breaker"] == "closed",
            )

    # -- summary -----------------------------------------------------------
    total = report.passed + len(report.failed)
    print(f"\n{'-' * 60}")
    if report.failed:
        print(f"{RED}{len(report.failed)} of {total} checks failed:{RESET}")
        for failure in report.failed:
            print(f"  - {failure}")
        return 1
    print(f"{GREEN}all {total} checks passed{RESET}")
    return 0


def main() -> int:
    """Parse arguments and run the smoke test."""
    parser = argparse.ArgumentParser(description="Smoke-test a running instance of this API.")
    parser.add_argument(
        "base_url",
        nargs="?",
        default=None,
        help=f"base URL to test (default: $SE_SMOKE_BASE_URL, else {DEFAULT_BASE_URL})",
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON too")
    args = parser.parse_args()

    base_url = args.base_url or os.environ.get("SE_SMOKE_BASE_URL") or DEFAULT_BASE_URL
    status = run(base_url)
    if args.json:
        print(json.dumps({"base_url": base_url, "ok": status == 0}))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
