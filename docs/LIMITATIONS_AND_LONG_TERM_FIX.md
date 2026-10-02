# Limitations, and the right long-term fix

## What this approach costs

A scraping bridge is a bet that a website's markup will not change. Everything
below follows from that one bet.

**It breaks when the markup changes.** The parsers match specific selectors on
`standardebooks.org`. Nothing guarantees the site keeps publishing that shape.
**It depends on undocumented behaviour.** The `view=list`, `per-page`, `query`,
`sort` and `tags[]` parameters are what the site's own frontend happens to send.
They are not a contract, and the site can change or withdraw them without notice.
**There is no service level agreement.** Nobody has promised this endpoint will
exist tomorrow, will return the same shape, or will be maintained at all.
**It covers only part of the data.** List, detail, search, subjects and authors
are covered. Reading-level distributions, contributor biographies, publication
history, file formats and download links are not. **It is strictly read-only.**
There is no write path, by design. **It can serve slightly stale data.** The
cache is a deliberate politeness trade: a response may be up to one cache
lifetime old, by default 300 seconds. **It is throughput-limited.** One upstream
request per second by default means a caller paging through a large catalogue
waits, and a shared cache is not enough at volume because the cache is
in-process. **It carries legal and terms-of-service risk.** Reading public pages
is not the same as being authorised to republish them, and the operator of this
service, not the site, carries that risk. **There is no authenticated or
per-user data.** No accounts, no personalisation, no membership content.
**There is no accuracy guarantee.** A parser can be subtly wrong without
detecting it: a book with two contributors may lose one. **It is unsuitable for
production-scale volume.** One request per second cannot support a service with
real traffic, and pushing harder would be discourteous at best.

## What breaks first, and how you find out

The most likely failure is a **restructure of the listing page**. That is the
page every other endpoint depends on, so a change there breaks the most
functionality at once. The second most likely is the **grid view**, whose markup
differs subtly from the list view: reading-ease is printed in a different
position, and fields this project returns as absent there may not be absent in
the other direction.

The bridge is built to fail loudly rather than quietly wrong. Parsers treat every
required element as mandatory and raise a drift error naming the missing selector,
which surfaces as `UPSTREAM_CHANGED` with HTTP 502 and a log line naming the
element. A caller sees an error, not a short list. The risk that remains is a
change that keeps the selectors valid while altering their *meaning*, which no
amount of local validation can detect; only a diff against a fresh capture would,
and no such monitoring runs continuously here.

## The right long-term fix

The correct fix is not a better scraper. It is for **the data owner to offer an
official API or a data feed**. For commercial use, the right instrument is a
**partnership or a data-licensing agreement**, not a more polite crawler.

A good official API would provide: a **versioned schema**, so consumers can pin
a version and be told when a new one appears; **authentication**, so access is
metered and attributable rather than anonymous; **rate-limit headers**, so
callers can self-regulate instead of guessing; **webhooks or a change feed**, so
consumers learn about new or corrected records instead of polling; and a **service
level agreement** with stated uptime and support terms. Standard Ebooks already
publishes its source as version-controlled files, so a feed of its catalogue
would be a small increment for them and a large one for consumers.

## Why the interface is shaped to survive that swap

The scraping boundary is one package. `app/upstream` owns every URL, selector and
field mapping, and nothing above it knows what an HTML page is. Routes, the
`data`/`meta` envelope, the five error codes and the response models are
independent of where the bytes came from. Swapping in an official API means
rewriting `app/upstream` and deleting the fixtures; the routes, the schemas, the
OpenAPI document and every consumer stay as they are. That is the point of the
split, and it is why this is worth building even as an interim measure.

## Next steps in a real engagement

1. **Who to approach.** The Standard Ebooks maintainers and trustees, who already
   run a public issue tracker and discuss catalogue tooling there. Ask about the
   mailing list first; a maintainer can redirect an approach that is not theirs to
   accept.
2. **What to ask for.** A read-only catalogue endpoint, or a periodic
   machine-readable export. Lead with their interest: they do not need to build
   an API, only to publish the structured data they already keep. Offer to
   maintain any client you write against it.
3. **How to measure impact.** Time to catalogue change visible in this bridge,
   broken-parse incidents per month, and upstream requests avoided. Those are the
   numbers that justify the conversation.
4. **Until then.** Keep the politeness defaults, watch for `UPSTREAM_CHANGED` in
   the logs, re-capture fixtures whenever the site changes, and treat this service
   as what it is: a working demonstration that the underlying demand is real, not
   a foundation to build on.

Implementation-level caveats, including the cache, the circuit breaker and
per-process state, are in [LIMITATIONS.md](LIMITATIONS.md).