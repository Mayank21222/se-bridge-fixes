# Using this API with an AI agent

A short, practical guide for an agent that needs to look things up here rather
than browsing.

## The one rule

**Call this API, not the website.** It is the polite path: rate-limited,
cached, and instrumented. Going to `standardebooks.org` directly from a tool
loop is how an agent ends up hammering a volunteer project.

## Choose the endpoint

| You want | Call |
| --- | --- |
| Browse the catalogue | `GET /v1/ebooks?page=1&page_size=24` |
| Find books on a topic | `GET /v1/search?q=...` |
| Everything by one author | `GET /v1/authors/{author-slug}` |
| One book, in full | `GET /v1/ebooks/{author-slug}/{title-slug}` |
| Valid subject slugs | `GET /v1/subjects` |
| Is it up? | `GET /health` |

## The tools

Six tools, droppable into an agent as they are. Base URL
`http://127.0.0.1:8000`. Every one returns the same envelope.

### `get_health`

**Purpose.** Check the service and whether the target site is reachable. Cached
and rate-limited like everything else, so it is safe to call often.

**Parameters.** None.

**Example call.**

```bash
curl -s http://127.0.0.1:8000/health
```

**Example response.**

```json
{
  "data": {
    "status": "ok",
    "upstream_reachable": true,
    "circuit_breaker": "closed",
    "upstream_check_url": "https://standardebooks.org/ebooks?view=list&per-page=1&page=1",
    "service_version": "1.0.0"
  },
  "meta": {
    "page": null,
    "page_size": null,
    "total": null,
    "source_url": "https://standardebooks.org/ebooks?view=list&per-page=1&page=1",
    "fetched_at": "2026-10-02T05:54:37.655289Z",
    "cached": false
  }
}
```

### `list_ebooks`

**Purpose.** Page through the catalogue, newest first, optionally filtered by
subject. Use this to browse; use `search_ebooks` when you have a query.

**Parameters.**

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `page` | int | `1` | Must be ≥ 1. |
| `page_size` | int | `24` | 1–48; 12, 24 and 48 are the sizes the site itself offers. |
| `subject` | slug | — | From `list_subjects`. Rejects anything else with `BAD_REQUEST`. |
| `sort` | enum | `newest` | `newest`, `author-alpha`, `reading-ease`, `length`, `popularity`. `relevance` is rejected here. |

**Example call.**

```bash
curl -s "http://127.0.0.1:8000/v1/ebooks?page=1&page_size=2"
```

**Example response.**

```json
{
  "data": [
    {
      "id": "dorothy-m-richardson/oberland",
      "title": "Oberland",
      "authors": [{"name": "Dorothy M. Richardson", "slug": "dorothy-m-richardson", "url": "https://standardebooks.org/ebooks/dorothy-m-richardson", "same_as": []}],
      "contributors": [],
      "subjects": [{"name": "Fiction", "slug": "fiction"}],
      "word_count": 40658,
      "reading_ease": 66.57,
      "cover_url": "https://standardebooks.org/images/covers/dorothy-m-richardson_oberland/0dd9469/cover@2x.jpg",
      "source_url": "https://standardebooks.org/ebooks/dorothy-m-richardson/oberland"
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 2,
    "total": null,
    "source_url": "https://standardebooks.org/ebooks?view=list&per-page=2&page=1",
    "fetched_at": "2026-10-02T05:54:37.703301Z",
    "cached": false
  }
}
```

`meta.total` is `null`: the site publishes no count. Walk pages until one comes
back empty.

### `search_ebooks`

**Purpose.** Find books by free text across titles, author names and contributor
credits. Substring matching, not semantic ranking.

**Parameters.**

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `q` | string | — | Required. Blank or whitespace-only is `BAD_REQUEST`; max 200 characters. |
| `page` | int | `1` | Must be ≥ 1. |
| `page_size` | int | `24` | 1–48. |
| `subject` | slug | — | Narrows the search to one subject. |
| `sort` | enum | `relevance` | `relevance` or `newest`. |

**Example call.**

```bash
curl -s "http://127.0.0.1:8000/v1/search?q=shakespeare&page_size=1&sort=newest"
```

**Example response.**

```json
{
  "data": [
    {
      "id": "william-shakespeare/richard-iii",
      "title": "Richard III",
      "authors": [{"name": "William Shakespeare", "slug": "william-shakespeare", "url": null, "same_as": []}],
      "contributors": [],
      "subjects": [{"name": "Drama", "slug": "drama"}],
      "word_count": 31100,
      "reading_ease": 80.82,
      "cover_url": "https://standardebooks.org/images/covers/william-shakespeare_richard-iii/91dba07/cover@2x.jpg",
      "source_url": "https://standardebooks.org/ebooks/william-shakespeare/richard-iii"
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 1,
    "total": null,
    "source_url": "https://standardebooks.org/ebooks?view=list&per-page=1&page=1&query=shakespeare",
    "fetched_at": "2026-10-02T05:54:38.916312Z",
    "cached": false
  }
}
```

A query with no matches returns `200` with `"data": []`. That is a valid answer,
not a failure.

### `get_ebook`

**Purpose.** One book in full, including the fields the listing omits:
description, formats, licence, publication dates and provenance.

**Parameters.**

| Name | Type | Notes |
| --- | --- | --- |
| `ebook_id` | path | One to three path segments, e.g. `edwin-a-abbott/flatland`. Embedded slashes are the separator; a stray `.` or `..` is `BAD_REQUEST`. |

**Example call.**

```bash
curl -s http://127.0.0.1:8000/v1/ebooks/edwin-a-abbott/flatland
```

**Example response.**

```json
{
  "data": {
    "id": "edwin-a-abbott/flatland",
    "title": "Flatland",
    "authors": [
      {
        "name": "Edwin A. Abbott",
        "slug": "edwin-a-abbott",
        "url": "https://standardebooks.org/ebooks/edwin-a-abbott",
        "same_as": [
          "https://id.loc.gov/authorities/names/n50034802.html",
          "https://en.wikipedia.org/wiki/Edwin_A._Abbott"
        ]
      }
    ],
    "contributors": [],
    "subjects": [{"name": "Fiction", "slug": "fiction"}],
    "word_count": 33546,
    "reading_ease": 52.12,
    "cover_url": "https://standardebooks.org/images/covers/edwin-a-abbott_flatland/eb024ce/hero@2x.jpg",
    "source_url": "https://standardebooks.org/ebooks/edwin-a-abbott/flatland",
    "abstract": "A square is pulled out of his reality by a sphere, and shown the meaning of three dimensions.",
    "description": "Flatland is uniquely both a social critique and a primer on multi-dimensional geometry.",
    "reading_time_minutes": 122,
    "difficulty": "fairly difficult",
    "collections": [],
    "language": "en-GB",
    "license": "https://creativecommons.org/publicdomain/zero/1.0/",
    "published_at": "2018-01-04",
    "updated_at": "2026-08-15",
    "formats": [{"label": "epub", "mime_type": "application/epub+zip", "url": "https://standardebooks.org/ebooks/edwin-a-abbott/flatland/downloads/edwin-a-abbott_flatland.epub"}],
    "read_online_url": "https://standardebooks.org/ebooks/edwin-a-abbott/flatland/text/single-page",
    "sources": [{"label": "This book at Wikipedia", "url": "https://en.wikipedia.org/wiki/Flatland"}],
    "source_repository_url": "https://github.com/standardebooks/edwin-a-abbott_flatland"
  },
  "meta": {
    "page": null,
    "page_size": null,
    "total": null,
    "source_url": "https://standardebooks.org/ebooks/edwin-a-abbott/flatland",
    "fetched_at": "2026-10-02T05:54:39.220415Z",
    "cached": false
  }
}
```

Null means the site omits that field for this edition. It is never a guess.

### `list_subjects`

**Purpose.** The valid `subject` slugs. Call this before filtering rather than
guessing a slug.

**Parameters.** None.

**Example call.**

```bash
curl -s http://127.0.0.1:8000/v1/subjects
```

**Example response.**

```json
{
  "data": [
    {"slug": "adventure", "name": "Adventure"},
    {"slug": "autobiography", "name": "Autobiography"},
    {"slug": "drama", "name": "Drama"},
    {"slug": "science-fiction", "name": "Science Fiction"}
  ],
  "meta": {
    "page": 1,
    "page_size": 19,
    "total": 19,
    "source_url": "https://standardebooks.org/ebooks?view=list&per-page=1&page=1",
    "fetched_at": "2026-10-02T05:54:40.108224Z",
    "cached": false
  }
}
```

Trimmed to four of nineteen. This is the one endpoint where `meta.total` is
exact.

### `get_author_books`

**Purpose.** Everything in the catalogue by one author.

**Parameters.**

| Name | Type | Notes |
| --- | --- | --- |
| `author_slug` | path | Lowercase hyphens, as in the catalogue's own URLs, e.g. `edwin-a-abbott`. |

**Example call.**

```bash
curl -s http://127.0.0.1:8000/v1/authors/edwin-a-abbott
```

**Example response.**

```json
{
  "data": [
    {
      "id": "edwin-a-abbott/flatland",
      "title": "Flatland",
      "authors": [{"name": "Edwin A. Abbott", "slug": "edwin-a-abbott", "url": null, "same_as": []}],
      "contributors": [],
      "subjects": [],
      "word_count": null,
      "reading_ease": null,
      "cover_url": "https://standardebooks.org/images/covers/edwin-a-abbott_flatland/eb024ce/cover@2x.jpg",
      "source_url": "https://standardebooks.org/ebooks/edwin-a-abbott/flatland"
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 1,
    "total": 1,
    "source_url": "https://standardebooks.org/ebooks/edwin-a-abbott",
    "fetched_at": "2026-10-02T05:54:40.915025Z",
    "cached": false
  }
}
```

`subjects`, `word_count` and `reading_ease` are `null` here and the array is
always complete: the site renders author pages in grid mode, which omits those
fields. Use `get_ebook` for one book if you need them.

## Read the envelope

Every success has the same two keys:

```json
{
  "data": [ ... ],
  "meta": {
    "page": 1,
    "page_size": 24,
    "total": null,
    "source_url": "https://standardebooks.org/ebooks?view=list&per-page=24&page=1",
    "fetched_at": "2026-10-02T05:27:03Z",
    "cached": false
  }
}
```

- **`meta.total` is `null` for listings.** The site does not publish a count.
  Do not use its absence as a signal that you have reached the end — walk pages
  until one comes back empty.
- **`meta.cached` tells you the cost was zero.** If it is `true`, the answer
  came from this service's cache. Repeating a cached query is free; repeating
  an uncached one costs the upstream site a request.
- **`meta.source_url` is the exact upstream page.** Quote it in an answer when
  a user wants to check your work. Never fetch it yourself.

Every failure has one shape and one of five codes:

```json
{"error": {"code": "BAD_REQUEST", "message": "page must be at least 1", "retryable": false}}
```

| Code | Status | Meaning | What to do |
| --- | --- | --- | --- |
| `BAD_REQUEST` | 400 | Your parameters are wrong. | Fix them. Retrying unchanged is pointless. |
| `NOT_FOUND` | 404 | No such record or endpoint. | Check the identifier; the site uses lowercase slugs. |
| `RATE_LIMITED` | 429 | Throttled locally, upstream is busy, or the circuit is open. | Back off and retry. This one is retryable. |
| `UPSTREAM_BLOCKED` | 502 | The site refused automated access. | **Stop.** Do not retry, and do not try to work around it. |
| `UPSTREAM_CHANGED` | 502 | The site's HTML no longer matches the parsers. | **Stop and report.** The service needs a maintainer, not a retry. |

`UPSTREAM_BLOCKED` and `UPSTREAM_CHANGED` are not obstacles to route around.
Treat both as "tell the user the bridge is broken", then stop calling.

## Being a good caller

- **Ask for what you need.** `page_size=12` is plenty for most questions; the
  ceiling is 48.
- **Do not loop pages.** The catalogue holds ~1,500 books. Two or three pages
  will answer almost any question; fetching all 128 to count them will not.
- **Reuse a slug you already have.** The catalogue's own URLs use lowercase
  hyphens: `edwin-a-abbott/flatland`. `GET /v1/subjects` gives you valid
  subject slugs.
- **Search is a substring match, not a semantic one.** It matches titles,
  author names and contributor credits. `shakespeare` returns plays plus
  unrelated books that merely mention him.
- **Back off on 429** — at least a second, ideally exponential. A burst of
  retries is what opens the circuit breaker.

## Recipes

**One question, one book**

```bash
curl -s "http://127.0.0.1:8000/v1/ebooks/edwin-a-abbott/flatland" \
  | jq '{title: .data.title, author: .data.authors[0].name, subjects: [.data.subjects[].slug], read: .data.read_online_url}'
```

**Find something to read on a subject**

```bash
curl -s "http://127.0.0.1:8000/v1/ebooks?subject=science-fiction&sort=reading-ease&page_size=5" \
  | jq '.data[] | {id, title, authors: [.authors[].name]}'
```

**Check whether a bridge call worked before giving up**

```bash
curl -s http://127.0.0.1:8000/health | jq '{upstream: .data.upstream_reachable, breaker: .data.circuit_breaker}'
```

If `upstream` is `false` or the breaker is not `closed`, the upstream site is
having trouble. Wait rather than retrying; `/health` is rate-limited and cached
like everything else.

## For agents that generate code

The OpenAPI document is the contract:

- served live at `/openapi.json`,
- committed at `docs/openapi.json`.

Point a client generator at either. Do not hand-write request code from these
examples; the schema is the source of truth.

## What this service will not do

- It does not download ebook files. It returns URLs; fetching them is your
  call, and the site permits bulk download separately for that purpose.
- It does not write, edit or delete anything. Every endpoint is a read.
- It does not hold credentials, so it cannot reach the membership-gated feeds.
- It does not hide a failure behind an empty result. If the upstream call
  failed, you get an error, not a short list.