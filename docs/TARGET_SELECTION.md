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

- `robots.txt` disallows only `/honeypot` for `User-agent: *`. A named block of
  SEO and AI-crawler agents is restricted from full text and file downloads;
  the catalogue pages this bridge reads are not restricted for any agent.
- The catalogue carries schema.org microdata on real elements, which makes the
  parse targets stable rather than incidental.

**Use case.** An AI agent could call these endpoints to discover which
public-domain books a given subject or author has in the catalogue and read their
metadata, without scraping HTML or needing credentials.
- Content is CC0 by the publisher's own statement, so nothing personal or
  licensed is being copied.
- No login exists, so no credential handling is required.

### Terms of service and the permission basis

**The site publishes no separate terms-of-use document.** There is no `/terms`,
`/tos` or legal page, and a search of the site and the web for one turns up
nothing. That absence is itself the finding, and it means the usual gate — "find
the terms, read them, confirm they permit automated access" — cannot be satisfied
in the normal way. Rather than treat a missing document as silent permission,
here is the basis actually relied on, with the evidence:

**1. The content licence the publisher states for the work itself.** Standard
Ebooks' own statement, on its colophon and copyright pages and in its GitHub
organisation, is that its ebooks are released to the public domain under CC0,
and that its code and metadata are MIT-licensed. The relevant clause for this
project is therefore permissive rather than prohibitive: the site does not
assert rights over the catalogue metadata this bridge returns, which is why the
selected target passed gate 5 without a compromise.

**2. The `robots.txt` directives governing the paths used**, quoted in full in
[`docs/RECON.md`](RECON.md):

```
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

For `User-agent: *`, every path this bridge requests — `/ebooks`, `/ebooks/{id}`,
`/ebooks?view=list`, `/ebooks/{author}` — is allowed. `/honeypot` is disallowed
and is never requested.

The named block is narrower than it first appears, and the narrowing is in this
project's favour. Those eleven agents are barred from full text and from file
downloads, not from the catalogue. This bridge requests neither, so it complies
with the named-agent rules whichever agent it identifies as. No agent in the file
carries a bare `Disallow: /`, and `GPTBot` is not mentioned.

An earlier draft of this document claimed those agents were each disallowed from
the whole site with `Disallow: /`. That was not true of the live file, and the
error ran in the direction of inventing a prohibition that made the project's
ethical position look stricter than it is. It is corrected here because the
permission basis is the part of this submission most worth being able to trust.

The stricter reading that survives the correction: even where a path rule permits
this traffic, the site operator plainly prefers that bulk text and binaries not be
harvested by automated agents. The bridge takes that as binding on intent — hence
it never touches those paths, identifies itself honestly, holds one request per
second, caches for five minutes, and can be switched off with one environment
variable.

**3. What is not claimed.** No document on the site authorises automated access in
the way an API's terms of service would. The honest statement is that this bridge
operates in a space the site has left undefined, under a licence that grants the
rights it needs, while honouring every machine-readable instruction the site
publishes and accepting that the operator may block it at any time. That residual
uncertainty is a real limitation of the target choice, and it is recorded as such
in [`docs/LIMITATIONS_AND_LONG_TERM_FIX.md`](LIMITATIONS_AND_LONG_TERM_FIX.md)
rather than smoothed over.

### Why the AI-crawler rules did not disqualify the site

The named block covers agents of this kind — `chatgpt-user`, `claude-user`,
`claude-web`, `MistralAI-User` — but restricts them to catalogue pages rather
than excluding them. The exercise is explicitly to read a site that offers no API,
and the site's own machine-readable rules permit exactly the paths this bridge
uses. The project still identifies itself honestly as an automated read-only
client, stays at one request per second, caches aggressively, and can be turned
off with a single environment variable.
[`docs/LIMITATIONS.md`](LIMITATIONS.md) records what would change that decision.

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