# Reconnaissance

What was actually sent to the target site, what came back, and how the HTML was
mapped to records. Every claim here was checked against the live site; the
fixtures under `tests/fixtures/` are the recorded evidence.

## The target

`https://standardebooks.org`, reached over plain HTTPS with no redirect.

## Requests made

Exactly four distinct URL shapes, all GET, all on `standardebooks.org`:

| Purpose | Request | Result |
| --- | --- | --- |
| Catalogue listing | `GET /ebooks?view=list&per-page={size}&page={n}` | 200, HTML |
| Subject filter | `GET /subjects/{slug}?view=list&per-page=12` | 200, HTML |
| Free-text search | `GET /ebooks?view=list&per-page=12&query={q}&sort=relevance` | 200, HTML |
| Detail page | `GET /ebooks/{author}/{title}[/{contributor}]` | 200, HTML |
| Subject facets | the listing URL, reading its filter `<select>` | 200, HTML |
| Author listing | `GET /ebooks/{author}` | 200, HTML |

Query-parameter names, confirmed from the site's own form markup rather than
guessed: `view=list`, `per-page`, `page`, `query`, `tags[]`, `sort`.

**`per-page` is not restricted to three values.** The site's own control offers
12, 24 and 48, which is what an earlier draft of this file recorded and what the
README's assumptions table still claimed. Tested against the live site on
2026-10-02, any positive integer works: `per-page=13` renders exactly 13
`schema:Book` rows, `per-page=100` renders 100. The offered three are menu
choices, not a validated set. The bridge therefore does not allowlist them; it
caps the value at `SE_BRIDGE_MAX_PAGE_SIZE` (48) for its own reasons and passes
whatever it asks for.

**One redirect to record.** `tags[]` is what the filter form submits, but it is
not what the server answers on. `GET /ebooks?...&tags[]=philosophy` returns
**302** to `/subjects/philosophy?per-page=2&view=list`. Subject filtering is
therefore a *path* (`/subjects/{slug}`) that the form reaches through a
parameter, and the canonical links in the served HTML point at the path
directly. The bridge requests `/subjects/{slug}` directly and skips the
round trip. Both forms were fetched and compared: identical apart from a
donation aside. An earlier draft of this file described the `tags[]` URL as
returning 200 directly, which is wrong — it redirects.

## What was deliberately not requested

- **`/honeypot`** — `robots.txt` disallows it, and the link on every page says
  following it bans your IP for 24 hours. The bridge never constructs this URL,
  and `UpstreamClient` additionally refuses any URL whose path matches it before
  opening a socket. Its link text is present on *every* ordinary page, so it is
  not usable as a block signal; block detection uses HTTP 403 and challenge
  markers instead. See the note below.
- **`/feeds/opds`** — returns 401; requires membership credentials.
- **`/about`** — lists real patron names. Nothing in this API needs it.
- **Any authenticated endpoint.** No credentials exist, stored or accepted.

### A note on `/honeypot`, recorded honestly

While auditing these claims by hand, the author of this project requested
`/honeypot` once, to check what it returned. It returned 404, and the target
then stopped answering requests from this machine for the rest of the session —
connections refused on port 443 while unrelated hosts stayed reachable. Whether
that was a honeypot-triggered ban, rate limiting or an unrelated server event
was never established, because the correct response to a block is to stop, not
to keep probing.

Two things follow, and both are reflected in the code rather than only here:

1. `UpstreamClient` now refuses any URL whose path is `/honeypot` — including a
   trailing slash, a nested path or a query string — raising `DisallowedPath`
   before any socket work. Previously the project only avoided the URL by never
   constructing it, which is a single careless route away from the same outcome.
2. The live suite and the smoke test could not be re-run after this happened, so
   the transcripts in `docs/TEST_RESULTS.md` are from the earlier verified runs
   and are labelled with what they do and do not prove.

## robots.txt

Retrieved from `https://standardebooks.org/robots.txt` on 2026-10-02:

```
Sitemap: https://standardebooks.org/sitemap

# Badly-behaved bots
User-agent: *
Disallow: /honeypot

# SEO crawlers
User-agent: SemrushBot
User-agent: DotBot
User-agent: AhrefsBot
User-agent: SEOkicks
User-agent: DataForSeoBot
User-agent: proximic
User-agent: chatgpt-user
User-agent: claude-user
User-agent: claude-web
User-agent: MistralAI-User
User-agent: Perplexity-User

Disallow: /ebooks/*/downloads/*
Disallow: /ebooks/*/text*
```

Reading this carefully, because the shape matters:

- **For `User-agent: *`, only `/honeypot` is disallowed.** Every path this
  bridge requests — `/ebooks`, `/ebooks/{author}`, `/ebooks/{ebook_id}` — is
  allowed. There is no blanket crawl ban.
- **The named block is a content restriction, not a blanket ban.** Those eleven
  agents, which include `chatgpt-user`, `claude-user`, `claude-web`,
  `MistralAI-User` and `Perplexity-User`, are barred from `/ebooks/*/downloads/*`
  and `/ebooks/*/text*` — the full text and the file downloads. They are **not**
  barred from the catalogue pages, which is precisely what this bridge reads.
- **No agent is listed with a bare `Disallow: /`.** `GPTBot` does not appear in
  the file at all. An earlier draft of this document claimed a block of named AI
  crawlers each carrying `Disallow: /`; that was wrong, and it overstated the
  restriction. It has been corrected against the live file rather than left as a
  convenient belief.
- **The bridge stays inside the permission on its own terms.** It never
  requests `downloads/` or `text` paths, so it complies with the named-agent
  rules whichever agent it identifies as. It also honours the parts that are not
  mandatory: one request per second, a five-minute cache, an identifying
  `User-Agent` with a contact, and no attempt to disguise the client.

## Endpoint findings

### No queryable API

- `/feeds/opds` and `/feeds/opds/all` → **401 Unauthorized**. Membership-gated.
- `/feeds/atom/new-releases` → 200, but a feed of recent releases, not a
  catalogue interface.
- No developer documentation page exists.

### The catalogue page does everything

One page renders listing, subject filter, search, sort and pagination. That is
why the API needs only one upstream listing call shape.

### Sorting is context-dependent

The sort menu changes when a free-text query is present:

- Without a query: `default`, `author-alpha`, `reading-ease`, `length`,
  `popularity`.
- With a query: `relevance` and `newest` replace `default`.

`relevance` does not exist without a query. The API exposes one vocabulary and
maps it per context (`app/upstream/endpoints.py:upstream_sort`), and rejects a
sort key that is meaningless for the endpoint with `BAD_REQUEST` rather than
silently dropping it.

### No total is published

The catalogue paginates but never says how many items exist, and the page-number
strip is a sliding window that does not reach the end. So `meta.total` is
`null` for paginated responses. Inventing one would be a lie. Two endpoints
*can* report an exact total — `/v1/subjects` and `/v1/authors/{slug}` — because
they return everything in one response.

### Out-of-range pages clamp instead of emptying

`?page=9999` answers 200 with the **last** page (2 rows), not 404 and not an
empty list. A caller cannot use a past-the-end page to probe catalogue depth.
`test_out_of_range_page_clamps_to_the_last_page` pins this behaviour, and the
comment there explains why it matters.

### Author pages ignore `view` and `page`

`/ebooks/{author}?view=list&per-page=48` still renders
`<ol class="ebooks-list grid">` with no pagination. Grid rows carry no subjects
and no word counts. This is an upstream limit, not a parsing gap, and the API
documents it rather than papering over it.

### Two shapes for "nothing here"

A page with an empty `<ol class="ebooks-list">` and a page with no list at all,
just `<p class="no-results">`, are both valid empty results. The parser accepts
both and treats anything else as drift.

## HTML mapping

### Listing rows — `<li typeof="schema:Book" about="/ebooks/...">`

Types are the ones the API actually returns. "Can be missing" means the site
legitimately omits it, in which case the field is `null` and never a guess.

| Field | Type | Can be missing | Selector | Notes |
| --- | --- | --- | --- | --- |
| `id` | `str` | no | `about` attribute | path tail after `/ebooks`, one to three segments |
| `title` | `str` | no | `span[property="schema:name"]` | required; absence is drift |
| `authors` | `list[AuthorRef]` | no, but may be empty | `p.author a` | list view; grid view uses `property="schema:author"` |
| — | — | — | — | No element carries `property="schema:keywords"`. An earlier draft of this table listed a `li.property > span[property="schema:keywords"] a` selector for subjects; no such markup exists on any recorded page, and the parser reads `/subjects/` links directly |
| `contributors` | `list[ContributorRef]` | yes, usually empty | `p:not(.author) a` | role is inferred from the preceding text |
| `subjects` | `list[SubjectRef]` | yes, usually empty | `a[href^="/subjects/"]` | absent in grid mode |
| `word_count` | `int \| null` | yes | `div.details p` text in rows; `article p` prose on detail pages | parsed from prose; absent in grid mode |
| `reading_ease` | `float \| null` | yes | same prose as `word_count` | row text is `N words • S reading ease`; detail text is `N words (D duration) with a reading ease of S (label)` |
| `cover_url` | `str \| null` | yes | `img[property="schema:image"]`, `src` | resolved absolute |
| `source_url` | `str` | no | `about` attribute | resolved absolute; always present so any record is traceable |

Nested reference objects, each carrying its own `source_url` where the site
publishes one:

| Field | Type | Can be missing | Notes |
| --- | --- | --- | --- |
| `AuthorRef.name` | `str` | no | text of the anchor |
| `AuthorRef.slug` | `str` | no | anchor `href` tail |
| `AuthorRef.url` | `str \| null` | yes | null in listing rows, absolute URL on detail pages |
| `AuthorRef.same_as` | `list[str]` | yes, usually empty | authority footnotes, detail pages only |
| `ContributorRef.name` | `str` | no | text of the anchor |
| `ContributorRef.role` | `str` | yes | inferred from the text before the anchor |
| `ContributorRef.url` | `str \| null` | yes | null in listing rows |
| `SubjectRef.name` / `.slug` | `str` | no | `href` is `/subjects/{slug}` |

### Detail page — `<article>`

Carries every listing field above plus these. All are nullable, because a
minimal edition may legitimately omit any of them.

| Field | Type | Can be missing | Where it comes from |
| --- | --- | --- | --- |
| `abstract` | `str \| null` | yes | `meta[property="schema:abstract"]` content, not a paragraph |
| `description` | `str \| null` | yes | `div[property="schema:description"]` text, not a paragraph |
| `reading_time_minutes` | `int \| null` | yes | the duration inside the reading-ease prose, e.g. `(2 hours 2 minutes)`; absent in grid rows |
| `difficulty` | `str \| null` | yes | the parenthetical label in the prose, e.g. "(fairly difficult)"; grid rows carry no label at all |
| `collections` | `list[CollectionRef]` | yes | series links, absent from most editions; `CollectionRef` is `name`, `slug` |
| `language` | `str \| null` | yes | `meta[property="schema:inLanguage"]` content attribute |
| `license` | `str \| null` | yes | `meta[property="schema:license"]` content — the CC0 deed URL, e.g. `https://creativecommons.org/publicdomain/zero/1.0/` |
| `published_at` | `str \| null` | yes | `meta[property="schema:datePublished"]` content, normalised to an ISO 8601 date |
| `updated_at` | `str \| null` | yes | `meta[property="schema:dateModified"]` content, normalised to an ISO 8601 date |
| `formats` | `list[FormatRef]` | yes | `div.downloads-container li[typeof="schema:MediaObject"]`; `FormatRef` is `label` (anchor text), `mime_type` from `meta[property="schema:encodingFormat"]` content, `url` from `a[property="schema:contentUrl"]` |
| `read_online_url` | `str \| null` | yes | the anchor at `href="#read-online"`; absent when the site offers none |
| `sources` | `list[SourceRef]` | yes | provenance links in the footer section; `SourceRef` is `label`, `url` |
| `source_repository_url` | `str \| null` | yes | the GitHub repository link for the transcription |

Author `same_as` values come from `meta[property="schema:sameAs"]` content
attributes nested inside each author anchor, one per authority record (Library
of Congress, Wikipedia, and so on). The prose fields are not both paragraphs:
`description` is the text of `div[property="schema:description"]`, while
`abstract` is the `content` attribute of a `meta` tag. Whitespace is normalised
in every case.

## Fixtures

Twelve pages were recorded and trimmed to `tests/fixtures/`, each trimmed down
to the smallest subtree that still parses identically — verified by parsing
both the original and the trimmed file and asserting the results match
byte-for-byte after model dumping. `tests/fixtures/README.md` lists each
fixture, its source URL and its size.

A test asserts that none of the twelve real pages contains any block marker, so
challenge detection cannot misfire on ordinary catalogue content.