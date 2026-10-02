# Target selection

The brief asked for three candidate sites, a written decision, and evidence
that the chosen one can be scraped responsibly. This is that record.

## How candidates were screened

Every candidate had to clear the same five gates, in this order:

1. **Realistic workflows.** At least one list/browse view, one search view, and
   one detail view, reachable by ordinary URLs without JavaScript.
2. **No public API to use instead.** If a real API exists, the exercise is not
   a reverse-engineering exercise.
3. **Permission.** `robots.txt` allows the paths we need, and no terms of use
   prohibit automated reading.
4. **No personal data.** No accounts, no member directories, no names we would
   have to store.
5. **Public-domain or equally free content**, so a cached copy is defensible.

## The shortlist

### 1. Standard Ebooks — **selected**

`https://standardebooks.org`

A volunteer-produced catalogue of public-domain ebooks, formatted and released
to the CC0. Every book has a page with a description, subjects, contributors,
download formats and provenance links; the whole catalogue is browsable and
searchable through ordinary query parameters.

- `robots.txt` allows `/` for `User-agent: *` and disallows only `/honeypot`,
  plus a block of AI-scraper user agents.
- The catalogue carries schema.org microdata on real elements, which makes the
  parse targets stable rather than incidental.
- Content is CC0 by the publisher's own statement, so nothing personal or
  licensed is being copied.
- No login exists, so no credential handling is required.

Why the AI-scraper block matters, and why it did not disqualify the site: it
names user agents, not paths, and asks them not to scrape. This bridge
identifies itself honestly as an automated read-only client, stays at one
request per second, caches aggressively, and can be turned off with a single
environment variable. It is the kind of client the block is aimed at, and the
project treats that as a cost of doing business, not a technical obstacle to
route around. `docs/LIMITATIONS.md` records the decision to
keep it and what would change it.

### 2. The Gazette — rejected

`https://www.thegazette.co.uk`

Genuinely good candidate on content: official notices, a real search, a
document-detail view, and an XML data directory.

Rejected on gate 4. UK statutory notices are full of real people's names,
addresses and insolvency details. A catalogue of them is a searchable index of
private individuals, which is precisely the class of data this brief says to
avoid. Even read-only, that is not data this service should help surface.

### 3. Craigslist — rejected

`https://newyork.craigslist.org`

Passes gates 1 and 2 easily: list views, search, and detail pages, with no API.

Rejected on gate 3. Craigslist's terms of use explicitly prohibit automated
access, including crawlers and scrapers. `robots.txt` disallows most search
paths. Choosing it would mean knowingly violating a published prohibition.

### Also considered

| Site | Outcome | Reason |
| --- | --- | --- |
| OpenFlights | rejected | The dataset pages are thin and the bulk files are separate downloads; weak detail views. |
| Project Gutenberg | rejected | Its catalogue pages are arguably a public API in all but name, which undercuts the exercise. |
| Open Library | rejected | It has a real, documented, free API. Correct tool, wrong exercise. |
| `books.toscrape.com` | rejected | A scraping sandbox with a "robots-allow-everything" banner; it is designed for this exercise rather than discovered through it. Useful only as a fallback. |

## The decision

Standard Ebooks. It is the only candidate that passed all five gates without
requiring a compromise on personal data, published terms, or honesty about who
the client is.

The gap it leaves is real and worth stating plainly: **the site publishes no
queryable catalogue API.** It offers OPDS feeds at `/feeds/opds`, but those
require membership credentials and return `401` without them. Using them would
mean handling private credentials for a public catalogue, which this project
will not do. The one public feed, `/feeds/atom/new-releases`, is not a
catalogue interface. So the catalogue pages are the only correct target — see
`docs/RECON.md` for the requests actually made.