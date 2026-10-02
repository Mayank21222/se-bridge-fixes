# Standard Ebooks Bridge

A read-only JSON API over the public [Standard Ebooks](https://standardebooks.org)
catalogue, which publishes no queryable API of its own.

- **Six endpoints** — browse, search, one record, an author's works, subject
  facets, and health.
- **One upstream request per second**, a five-minute cache, and a circuit
  breaker that opens rather than hammering a site having trouble.
- **No credentials, no personal data, no writes.**
- **133 tests** (119 offline in 0.35s, 14 live) and a 70-check smoke test.

The site is a volunteer project that blocks named AI crawlers in `robots.txt`
and ships a honeypot path that bans the requesting IP. This bridge identifies
itself, stays slow, caches hard, and reports a block instead of working around
one. See [Why this target](#why-this-target) — that decision is argued in full
in [`docs/TARGET_SELECTION.md`](docs/TARGET_SELECTION.md).

---

## Quick start

```bash
make setup     # create .venv (Python 3.11+) and install runtime + dev deps
make run       # serve on http://127.0.0.1:8000
```

In another terminal:

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
curl -s "http://127.0.0.1:8000/v1/ebooks?page_size=3" | python3 -m json.tool
```

Interactive docs are at `/docs`, the schema at `/openapi.json`.

Without `make`, or with different tools:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

No configuration is required. Every setting has a working default; copy
`.env.example` to `.env` to change any of them.

## All targets

| Command | What it does |
| --- | --- |
| `make setup` | Create the virtualenv and install dependencies |
| `make run` | Start the API on port 8000 with reload |
| `make test` | Offline suite: 119 tests, no network |
| `make test-live` | Adds the 14 tests that hit the real site |
| `make smoke` | 70 live checks against a running server |
| `make lint` | `ruff check`, `ruff format --check`, `mypy` |
| `make format` | Apply ruff's fixes and formatting |
| `make openapi` | Write `docs/openapi.json` |
| `make scan` | Fail on secrets, credentials or personal e-mail addresses |
| `make clean` | Remove caches and the virtualenv |

---

## The API

Every success returns the same envelope:

```json
{
  "data": [ ... ],
  "meta": {
    "page": 1,
    "page_size": 12,
    "total": null,
    "source_url": "https://standardebooks.org/ebooks?view=list&per-page=12&page=1",
    "fetched_at": "2026-10-02T05:27:03Z",
    "cached": false
  }
}
```

Every failure returns one of five codes, with the same shape:

```json
{"error": {"code": "BAD_REQUEST", "message": "page must be at least 1", "retryable": false}}
```

| Code | Status | Retryable | Means |
| --- | --- | --- | --- |
| `BAD_REQUEST` | 400 | no | Your parameters are wrong |
| `NOT_FOUND` | 404 | no | No such record or endpoint |
| `RATE_LIMITED` | 429 | yes | Throttled, upstream busy, or breaker open |
| `UPSTREAM_BLOCKED` | 502 | no | The site refused automated access — **stop** |
| `UPSTREAM_CHANGED` | 502 | no | The site's HTML no longer matches — **report it** |

`meta.total` is `null` for paginated listings because the site publishes no
count and a guessed total would be a lie. `/v1/subjects` and
`/v1/authors/{slug}` return everything in one response, so they report a real
total.

### `GET /health`

Always `200`, so a monitor can read the body either way.

```json
{
  "data": {
    "status": "ok",
    "upstream_reachable": true,
    "circuit_breaker": "closed",
    "upstream_check_url": "https://standardebooks.org/ebooks?view=list&per-page=1&page=1",
    "service_version": "1.0.0"
  },
  "meta": { "page": null, "page_size": null, "total": null, "...": "..." }
}
```

The probe goes through the same cache, rate limit and breaker as real traffic,
so polling it cannot overload anything.

### `GET /v1/ebooks`

| Parameter | Default | Notes |
| --- | --- | --- |
| `page` | `1` | 1-based. `0` or negative → `BAD_REQUEST` |
| `page_size` | `12` | Ceiling 48 (`SE_BRIDGE_MAX_PAGE_SIZE`) |
| `subject` | — | A slug from `/v1/subjects`. Unknown → empty page, not an error |
| `sort` | `newest` | `newest`, `author-alpha`, `reading-ease`, `length`, `popularity` |

```bash
curl -s "http://127.0.0.1:8000/v1/ebooks?subject=science-fiction&sort=reading-ease&page_size=5"
```

Returns summaries: `id`, `title`, `authors`, `contributors`, `subjects`,
`word_count`, `reading_ease`, `cover_url`, `source_url`.

### `GET /v1/search`

Same parameters, plus a required `q`, and `sort` may also be `relevance`.
`q` must be non-blank and at most 200 characters. A query matching nothing is a
`200` with an empty list.

```bash
curl -s "http://127.0.0.1:8000/v1/search?q=shakespeare&page_size=5"
```

Search is substring matching over titles, authors and contributors — not
semantic. It will return books that merely mention your term.

### `GET /v1/ebooks/{ebook_id}`

`ebook_id` mirrors the site's own path tail:

```
edwin-a-abbott/flatland
thomas-a-kempis/the-imitation-of-christ/william-benham
```

Returns the full record: everything in the summary plus `abstract`,
`description`, `reading_time_minutes`, `difficulty`, `collections`, `language`,
`license`, `published_at`, `formats[]`, `read_online_url`, `sources[]` and
`source_repository_url`.

Identifiers are validated before any request leaves: uppercase, backslashes,
empty segments, `..`, over-long values and four-segment paths are all
`BAD_REQUEST` with no upstream call.

### `GET /v1/subjects`

The 19 subject slugs the catalogue can filter on, read from its filter form.

### `GET /v1/authors/{author_slug}`

Every ebook by one author in a single response. The site's author page ignores
`page` and `view` and always renders in grid mode, so these rows carry no
subjects or word counts — an upstream limit, documented rather than hidden.

```bash
curl -s "http://127.0.0.1:8000/v1/authors/dorothy-m-richardson"
```

---

## How it works

```
caller
  │
  ▼
app/main.py              routes, response envelope, error mapping
  │
  ▼
app/services/catalog.py   which upstream URL answers this, and what meta.total may be
  │
  ▼
app/services/validation.py every caller mistake rejected here, before any request
  │
  ▼
app/upstream/client.py    cache → breaker → rate limit → request → retry
  │                        │
  ▼                        ▼
app/upstream/endpoints.py  app/upstream/parsers.py
URL construction          pure HTML → records, raising on drift
```

| Module | Responsibility |
| --- | --- |
| `app/config.py` | Validated settings; a bad `.env` fails at start-up |
| `app/errors.py` | The five codes and the exceptions behind them |
| `app/models.py` | Pydantic schemas that define the OpenAPI contract |
| `app/services/validation.py` | Page, page size, sort, slug, ID and query rules |
| `app/upstream/endpoints.py` | Every upstream URL, in one file |
| `app/upstream/parsers.py` | Pure functions: HTML in, records out |
| `app/upstream/client.py` | The only code that opens a socket |

Two boundaries carry most of the design. **Parsers are pure** — no I/O, no
settings, so they are tested directly against fixtures. **The client is the only
network code**, and it takes `transport`, `clock`, `wall_clock`, `sleeper` and
`random_source` as constructor arguments. That single seam is what lets 119
tests run offline in a third of a second, with exact timing assertions.

### Politeness

Applied in order on every request:

1. **Cache** — the exact URL, for 300 seconds. Bounded at 512 entries.
2. **Circuit breaker** — after 5 consecutive upstream failures, no requests for
   60 seconds; then one trial request decides whether to close again.
3. **Rate limit** — one second between outbound calls, process-wide.
4. **Retries** — `429` and `5xx` only, exponential backoff with equal jitter,
   honouring `Retry-After` in both seconds and HTTP-date form. Nothing else is
   retried.
5. **Blocks are reported, not handled** — `403` or a challenge page raises
   `UPSTREAM_BLOCKED` immediately. This client does not solve challenges,
   rotate addresses, or pretend to be a browser.

Requests carry an identifying `User-Agent` and never carry credentials or
cookies. Logs record paths and statuses, never response bodies or query
strings.

---

## Why this target

`Standard Ebooks` passed five gates: realistic browse/search/detail workflows,
no public API to use instead, permission in `robots.txt`, no personal data, and
public-domain content.

Rejected: **The Gazette** (statutory notices are full of real people's names and
addresses), **Craigslist** (its terms prohibit automated access), **OpenFlights**
(thin detail views), **Open Library** and **Project Gutenberg** (they have real
APIs — the wrong exercise).

The gap worth being explicit about: the site *does* publish OPDS feeds at
`/feeds/opds`, but they return `401` without membership credentials. Using them
would mean handling private credentials for a public catalogue, so this project
does not. Full reasoning in [`docs/TARGET_SELECTION.md`](docs/TARGET_SELECTION.md).

Two paths are deliberately never requested: `/honeypot`, which `robots.txt`
disallows and which bans the requesting IP, and `/about`, which lists real
patron names and is not needed for anything here.

---

## Testing

```bash
make test          # 119 offline tests, no network, 0.35s
make test-live     # adds 14 tests against the real site
make run & make smoke   # 70 live checks over HTTP
make lint          # ruff + format check + mypy
make scan          # secrets and personal-data scan
```

Everything is injectable, so the offline suite is fully deterministic:
`FakeClock` for time, `RecordingSleeper` that advances the clock as a real sleep
would, and `FakeTransport` replaying scripted responses while recording every
URL that *would* have been requested.

Full results, the required-scenario matrix, and the five defects these tests
caught are in [`docs/TEST_RESULTS.md`](docs/TEST_RESULTS.md).

---

## Configuration

All optional, all validated at start-up. See [`.env.example`](.env.example).

| Variable | Default | Effect |
| --- | --- | --- |
| `SE_BRIDGE_BASE_URL` | `https://standardebooks.org` | Upstream origin |
| `SE_BRIDGE_REQUESTS_PER_SECOND` | `1.0` | Outbound rate limit |
| `SE_BRIDGE_CACHE_TTL_SECONDS` | `300` | Cache lifetime; `0` disables |
| `SE_BRIDGE_USER_AGENT` | identifying string | Sent on every request |
| `SE_BRIDGE_MAX_ATTEMPTS` | `3` | Attempts per request, including the first |
| `SE_BRIDGE_CIRCUIT_FAILURE_THRESHOLD` | `5` | Failures before the breaker opens |
| `SE_BRIDGE_CIRCUIT_COOLDOWN_SECONDS` | `60` | How long it stays open |
| `SE_BRIDGE_MAX_PAGE_SIZE` | `48` | Page-size ceiling |
| `SE_BRIDGE_MAX_QUERY_LENGTH` | `200` | Longest accepted `q` |
| `SE_BRIDGE_LOG_LEVEL` | `INFO` | Log verbosity |

There is **no** credential setting, because there is nothing to authenticate to.

---

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/TARGET_SELECTION.md`](docs/TARGET_SELECTION.md) | The five gates, the shortlist, why each rejection |
| [`docs/RECON.md`](docs/RECON.md) | Exact requests made, endpoints tried, HTML mapping |
| [`docs/AGENT_USAGE.md`](docs/AGENT_USAGE.md) | How an agent should call this, and what not to do |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | 12 known limits and the proper fix for each |
| [`docs/TEST_RESULTS.md`](docs/TEST_RESULTS.md) | Test evidence and the required-scenario matrix |
| [`docs/openapi.json`](docs/openapi.json) | Exported OpenAPI 3.1 document |

## Licence

MIT. This service contains no copied site content — it parses and returns
metadata and public URLs at request time, and caches responses in memory only.