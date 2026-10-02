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