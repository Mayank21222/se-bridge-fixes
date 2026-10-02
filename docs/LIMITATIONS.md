# Limitations, and what a proper fix would cost

An honest list of what this bridge cannot do, why, and what fixing it properly
would involve. Nothing here is hidden behind a workaround.

## 1. The target site restricts named AI crawlers

**What happens.** `robots.txt` for Standard Ebooks disallows `/honeypot` for
everyone, and bars a named group of SEO and AI agents — including `chatgpt-user`,
`claude-user`, `claude-web`, `MistralAI-User` and `Perplexity-User` — from
`/ebooks/*/text*` and `/ebooks/*/downloads/*`. It does not bar them from the
catalogue pages this bridge reads, and no agent in the file carries a blanket
`Disallow: /`. This project sets its own honest `User-Agent`, never requests the
restricted paths, and stays inside the one-request-per-second budget. See
`docs/TARGET_SELECTION.md` and `docs/RECON.md`.

**Why it is shipped anyway.** The brief asks for a responsible reader of a site
that offers no public API, and the site's own machine-readable rules permit the
paths this project uses. This implementation is what responsible looks like in
practice: it identifies itself, rate-limits itself, caches for five minutes,
detects blocks and reports them instead of working around them, and can be
switched off with `SE_BRIDGE_BASE_URL` plus a kill switch.

**The proper fix.** Ask. Standard Ebooks publishes a contact address and runs a
feed interface for exactly this kind of client. A real deployment should either
use the membership feeds with permission, or request written approval. This
should not be shipped at scale without one or the other.

**Kill switch.** `SE_BRIDGE_BASE_URL` points the bridge at a different origin;
stopping the process stops all traffic. There is no background scheduler, so
idle means zero requests.

## 2. No total count, and out-of-range pages clamp

**What happens.** The catalogue publishes no item count, so `meta.total` is
`null` on paginated responses. Worse, `?page=9999` answers 200 with the *last*
page rather than an empty list, so a client cannot discover the end by walking
past it.

**Why.** Both are upstream behaviours; the HTML has no total to read, and the
server does the clamping.

**The proper fix.** A persisted record count, refreshed on a slow schedule, with
an out-of-range page detected by comparing the returned rows against the
requested page's first identifier. Both need state this design deliberately
does not have — an in-process cache is not a database. Alternatively, use the
membership feed, which can be enumerated.

## 3. Subject facets come from an HTML form control

**What happens.** `/v1/subjects` parses the `<select name="tags[]">` out of the
catalogue page. That is the only place the site publishes its filter values.

**Why.** There is no facets endpoint.

**The proper fix.** Same as #2: read them from the feed, or cache them on a
schedule rather than on demand.

## 4. Author pages are grid-mode and unfiltered

**What happens.** `/ebooks/{author}` ignores `view=list` and `page`, so author
listings carry no subjects, word counts or reading ease. `/v1/authors/{slug}`
returns titles and identifiers only.

**Why.** Confirmed against the live site; it is not configurable from outside.

**The proper fix.** For each author, fetch their books' detail pages and
assemble the richer view — 13 extra requests for one author here. That is
expensive enough to need caching, which means #2's answer.

## 5. The cache is in-process only

**What happens.** Restarting the service empties it. Two replicas do not share
it, so total upstream load multiplies by the replica count.

**Why.** Keeps the deployment a single process with no external dependency.

**The proper fix.** Redis, or an HTTP cache layer in front. The `UpstreamClient`
interface is already injection-friendly — cache and limiter take a clock, so a
shared backend is a contained change to one class.

## 6. The circuit breaker is per-process

**What happens.** A breaker tripped in one worker does not stop another.

**The proper fix.** Shared state, as in #5. Until then, run one worker; the
default `make run` does.

## 7. No conditional requests

**What happens.** `If-None-Match` and `If-Modified-Since` are not sent, so a
revalidation that would return 304 instead re-downloads the page.

**Why.** The site sends no `ETag` or `Last-Modified` on catalogue pages, so
there is nothing to validate against.

**The proper fix.** Not available for this target.

## 8. The error vocabulary has no internal-error member

**What happens.** The brief fixes five error codes. There is no code for "the
upstream site is unreachable" or "a bug in this service". Both surface as
`RATE_LIMITED` (429, retryable) — the only retryable code available.

**Why.** The vocabulary is fixed, and inventing a sixth code would break it.

**The proper fix.** Add `UPSTREAM_UNAVAILABLE` (503) and `INTERNAL_ERROR` (500)
to the contract. This is the one limitation that is entirely self-imposed, and
the first thing to change with permission.

## 9. `BAD_REQUEST` for a 405

**What happens.** `POST /v1/ebooks` answers 400 `BAD_REQUEST` with the message
"method not allowed on this path" rather than 405.

**Why.** Same as #8 — the five-code vocabulary has no method-not-allowed
member.

**The proper fix.** Follow #8.

## 10. Search is substring matching

**What happens.** `q=shakespeare` returns the plays *and* books that merely
mention Shakespeare in their metadata. It does not understand meaning.

**Why.** That is what the site's `query` parameter does.

**The proper fix.** A local index — but that means downloading and storing the
catalogue, which is a different product with different obligations. Not
attempted here.

## 11. Ebook identifiers are path-shaped

**What happens.** IDs are the site's own path tails, so they change if the site
changes its URL scheme. IDs are also case-sensitive on our side and must be
lowercase.

**Why.** Mirroring the site keeps the mapping obvious and keeps `meta.source_url`
reconstructible.

**The proper fix.** Assign a stable internal surrogate key and keep the path as
an alias, once there is a database to hold the mapping.

## 12. Live tests depend on a third party being up

**What happens.** `--live` fails if `standardebooks.org` is unreachable. The
offline suite does not, because it runs entirely on fixtures.

**Why.** That is the correct trade for this project.

**The proper fix.** Nothing. Recorded here so a failing live run is read as "the
site is down", not "the code is broken".

## Not attempted, on purpose

- **Downloading ebook files.** Out of scope; the API returns URLs.
- **Any authenticated endpoint.** OPDS feeds need membership credentials, and
  this project holds none.
- **Storing a catalogue copy.** Would turn a polite reader into a mirror.
- **Proxying arbitrary URLs.** The bridge has no open proxy surface.
- **Scraping `/about`.** It lists real patron names; nothing here needs it.