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
| Catalogue listing | `GET /ebooks?view=list&per-page={12\|24\|48}&page={n}` | 200, HTML |
| Subject filter | `GET /ebooks?view=list&per-page=12&tags[]={slug}` | 200, HTML |
| Free-text search | `GET /ebooks?view=list&per-page=12&query={q}&sort=relevance` | 200, HTML |
| Detail page | `GET /ebooks/{author}/{title}[/{contributor}]` | 200, HTML |
| Subject facets | the listing URL, reading its filter `<select>` | 200, HTML |
| Author listing | `GET /ebooks/{author}` | 200, HTML |

Query-parameter names, confirmed from the site's own form markup rather than
guessed: `view=list`, `per-page`, `page`, `query`, `tags[]`, `sort`.

## What was deliberately not requested

- **`/honeypot`** — `robots.txt` disallows it, and the page punishes anyone who
  requests it. The bridge never constructs this URL. Its link text is present on
  *every* ordinary page, so it is not usable as a block signal; block detection
  uses HTTP 403 and challenge markers instead.
- **`/feeds/opds`** — returns 401; requires membership credentials.
- **`/about`** — lists real patron names. Nothing in this API needs it.
- **Any authenticated endpoint.** No credentials exist, stored or accepted.

## robots.txt

```
User-agent: *
Disallow: /honeypot

User-agent: GPTBot
Disallow: /
... (a further block of named AI crawlers, each Disallow: /)
```

Only `/honeypot` is path-restricted for everyone. The project honours both the
path rule and the spirit of the user-agent rule: one request per second, a
five-minute cache, an identifying `User-Agent`, and no attempt to disguise the
client.

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
| `title` | `str` | no | `h3 span[property="schema:name"]` | required; absence is drift |
| `authors` | `list[AuthorRef]` | no, but may be empty | `p.author a` | list view; grid view uses `property="schema:author"` |
| `contributors` | `list[ContributorRef]` | yes, usually empty | `p:not(.author) a` | role is inferred from the preceding text |
| `subjects` | `list[SubjectRef]` | yes, usually empty | `li.property > span[property="schema:keywords"] a` | absent in grid mode |
| `word_count` | `int \| null` | yes | `div.details` text | parsed from prose; absent in grid mode |
| `reading_ease` | `float \| null` | yes | `div.details` text | score before the word count in list view, after in grid view |
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
| `SubjectRef.name` / `.slug` | `str` | no | `href` is `/ebooks?tags[]={slug}` |

### Detail page — `<article>`

Carries every listing field above plus these. All are nullable, because a
minimal edition may legitimately omit any of them.

| Field | Type | Can be missing | Where it comes from |
| --- | --- | --- | --- |
| `abstract` | `str \| null` | yes | paragraph marked `property="schema:abstract"` |
| `description` | `str \| null` | yes | paragraph marked `property="schema:description"` |
| `reading_time_minutes` | `int \| null` | yes | prose in the details block, digit- and unit-matched |
| `difficulty` | `str \| null` | yes | prose in the details block, e.g. "Easy" |
| `collections` | `list[CollectionRef]` | yes | series links outside the keywords property; `CollectionRef` is `name`, `slug` |
| `language` | `str \| null` | yes | details prose |
| `license` | `str \| null` | yes | the copyright statement on the page |
| `published_at` | `str \| null` | yes | details prose, normalised to ISO 8601 date |
| `updated_at` | `str \| null` | yes | details prose, normalised to ISO 8601 date |
| `formats` | `list[FormatRef]` | yes | download table rows; `FormatRef` is `label`, `mime_type` (nullable), `url` |
| `read_online_url` | `str \| null` | yes | the "Read online" link; absent when the site offers none |
| `sources` | `list[SourceRef]` | yes | provenance links in the footer section; `SourceRef` is `label`, `url` |
| `source_repository_url` | `str \| null` | yes | the GitHub repository link for the transcription |

Author `same_as` links come from the authority footnotes (Library of Congress,
Wikipedia). Prose fields are read from the two paragraphs the site marks
`property="schema:description"` and `property="schema:abstract"`, whitespace
normalised in every case.

## Fixtures

Twelve pages were recorded and trimmed to `tests/fixtures/`, each trimmed down
to the smallest subtree that still parses identically — verified by parsing
both the original and the trimmed file and asserting the results match
byte-for-byte after model dumping. `tests/fixtures/README.md` lists each
fixture, its source URL and its size.

A test asserts that none of the twelve real pages contains any block marker, so
challenge detection cannot misfire on ordinary catalogue content.