# Test results

Every transcript below was produced on this machine by the command shown above
it, and is reproduced unedited. The only change is that ANSI colour escapes have
been stripped from the smoke test so the file reads as plain text; the words,
numbers and timings are as printed.

```
Python 3.12.14 · pytest 8.4.2 · platform darwin · macOS
```

## Offline suite — `make test`

Complete output:

```
$ .venv/bin/pytest
.................................................................sssssss [ 52%]
sssssss...........................................................       [100%]
=============================== warnings summary ===============================
tests/test_api.py::test_root_points_at_the_docs
  /Users/mayankkashyap/Desktop/FDE_Razorpay/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
124 passed, 14 skipped, 1 warning in 0.41s
```

The 14 skips are the live tests, which are opt-in. **No network access at all.**

| File | Tests | Covers |
| --- | --- | --- |
| `tests/test_parsers.py` | 28 | Every parser against the 12 recorded fixtures |
| `tests/test_politeness.py` | 31 | Cache, rate limit, retries, breaker, block detection |
| `tests/test_api.py` | 65 | Envelope, error vocabulary, validation, routing |
| `tests/test_live.py` | 14 | Real site, skipped without `--live` |

## Live suite — `make test-live`

Complete output:

```
$ .venv/bin/pytest --live
........................................................................ [ 52%]
..................................................................       [100%]
=============================== warnings summary ===============================
tests/test_api.py::test_root_points_at_the_docs
  /Users/mayankkashyap/Desktop/FDE_Razorpay/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
138 passed, 1 warning in 10.71s
```

All 14 live tests passed against `standardebooks.org`. At one request per second,
10.71 seconds is the rate limiter working, not slowness.

## Smoke test — `make smoke`

Against a real `uvicorn` on `http://127.0.0.1:8000`. Complete output:

```
$ .venv/bin/python scripts/smoke_test.py

Smoke test against http://127.0.0.1:8000

service
  PASS  GET / returns a pointer to the docs (27ms) HTTP 200
  PASS  root advertises docs, openapi and health (0ms)
  PASS  openapi.json is served (16ms) HTTP 200
  PASS  openapi documents all six endpoints (0ms) 6 paths

health
  PASS  GET /health answers 200 (1025ms) HTTP 200
  PASS  upstream is reachable (0ms) breaker=closed
  PASS  the health probe went through the same limiter as traffic (0ms)

catalogue listing
  PASS  GET /v1/ebooks returns a non-empty first page (259ms) HTTP 200
  PASS  first page has items (0ms) 12 items
  PASS  meta.total is null, not invented (0ms)
  PASS  meta.source_url points at the real site (0ms)
  PASS  each row has id, title, author and source_url (0ms) dorothy-m-richardson/oberland
  PASS  GET /v1/ebooks?page=2 returns page two (1024ms) HTTP 200
  PASS  page two holds different books than page one (0ms) 12 items
  PASS  page metadata follows the request (0ms)

cache
  PASS  a repeated request is served from cache (5ms)

search
  PASS  GET /v1/search?q=shakespeare returns hits (971ms) HTTP 200
  PASS  search found books (0ms) 12 hits
  PASS  hits include the obvious author (0ms)
  PASS  a search with no matches is a 200 with no rows (985ms) HTTP 200
  PASS  no-match search returns an empty list (0ms)
  PASS  special characters in q are handled (1005ms) HTTP 200
  PASS  a non-ASCII query is handled (1026ms) HTTP 200
  PASS  a blank q is rejected (2ms) HTTP 400
  PASS  blank q uses the error envelope (0ms)

filters and facets
  PASS  subject filter applies (1329ms) HTTP 200
  PASS  every row carries the requested subject (0ms) 12 items
  PASS  sort is passed through (748ms) HTTP 200
  PASS  an unknown subject returns an empty page (1194ms) HTTP 200
  PASS  unknown subject is an empty 200, not an error (0ms)
  PASS  subject facets are listed (8ms) HTTP 200
  PASS  facets include the well-known subjects (0ms) 19 subjects

records
  PASS  GET /v1/ebooks/dorothy-m-richardson/oberland returns a record (726ms) HTTP 200
  PASS  record has a source_url on the real site (0ms)
  PASS  record exposes download formats or online reading (0ms) 5 formats
  PASS  an unknown record is 404 (989ms) HTTP 404
  PASS  404 uses the error envelope (0ms)
  PASS  malformed id 'Author/Title' is 400 (2ms) HTTP 400
  PASS  malformed id uses the error envelope (0ms)
  PASS  malformed id 'a/b/c/d' is 400 (1ms) HTTP 400
  PASS  malformed id uses the error envelope (0ms)
  PASS  malformed id 'author//title' is 400 (1ms) HTTP 400
  PASS  malformed id uses the error envelope (0ms)
  PASS  malformed id '..%2f..%2fetc' is 400 (1ms) HTTP 400
  PASS  malformed id uses the error envelope (0ms)
  PASS  GET /v1/authors/dorothy-m-richardson lists their books (1038ms) HTTP 200
  PASS  author total is a real count (0ms) 13 books

input validation
  PASS  page=0 is rejected (2ms) HTTP 400
  PASS  page=0 uses the error envelope (0ms)
  PASS  page=-1 is rejected (2ms) HTTP 400
  PASS  page=-1 uses the error envelope (0ms)
  PASS  page_size=0 is rejected (2ms) HTTP 400
  PASS  page_size=0 uses the error envelope (0ms)
  PASS  page_size=49 is rejected (1ms) HTTP 400
  PASS  page_size=49 uses the error envelope (0ms)
  PASS  unknown sort is rejected (1ms) HTTP 400
  PASS  unknown sort uses the error envelope (0ms)
  PASS  relevance while browsing is rejected (1ms) HTTP 400
  PASS  relevance while browsing uses the error envelope (0ms)
  PASS  malformed subject is rejected (1ms) HTTP 400
  PASS  malformed subject uses the error envelope (0ms)
  PASS  over-long query is rejected (1ms) HTTP 400
  PASS  over-long query uses the error envelope (0ms)
  PASS  non-numeric page is rejected (1ms) HTTP 400
  PASS  non-numeric page uses the error envelope (0ms)
  PASS  unknown endpoint is rejected (1ms) HTTP 404
  PASS  unknown endpoint uses the error envelope (0ms)

politeness
  PASS  repeat traffic is absorbed by the cache (9ms) three identical calls, all cache hits
  PASS  health still reports the breaker closed (1ms) HTTP 200
  PASS  circuit breaker stayed closed under load (0ms)

------------------------------------------------------------
70 checks run, 70 passed, 0 failed
exit=0
```

70 live checks over real HTTP: the envelope, both pages differing, cache hits,
search hits and misses, filters, facets, detail records, every error code, and the
politeness layer holding under repeated traffic. The script exits zero only when
every check passes; this run exited 0.

## Lint, format and types — `make lint`

```
All checks passed!
29 files already formatted
Success: no issues found in 12 source files
```

## Secret scan — `make scan`

```
scanned 31 of 33 tracked files against 9 rules
no secrets, credentials or personal e-mail addresses found
rules checked: private key, AWS access key id, GitHub token, Slack token,
PyPI token, generic secret assignment, credential in a URL, opds membership
credential, personal e-mail address
```

Nine rules: private keys, AWS keys, GitHub/Slack/PyPI tokens, generic secret
assignments, credentials in URLs, OPDS membership credentials, and personal
e-mail addresses. Placeholders on `.invalid` and `example.com` are allowed
through; everything else fails the build. The scanner was verified against
deliberately injected violations and caught all of them, including one inside a
URL. It also caught a false positive of its own — the site's `cover@2x.jpg`
image filenames matched the e-mail rule inside three example URLs in
`docs/AGENT_USAGE.md` — fixed in `e134bb4` with a lookbehind that skips matches
sitting in a URL path, while still catching a real address such as
`real.person@acmecorp.co.uk`.

## Brief's required scenarios, mapped to evidence

| Required | Where it is proved | Result |
| --- | --- | --- |
| Health reachable true | `test_health_is_ok_when_the_site_answers`, `test_live_health_reports_the_site_reachable` | pass |
| Health reachable false, no crash | `test_health_stays_200_and_reports_degraded_when_the_site_is_down` | pass |
| Non-empty listing | `test_listing_returns_summaries`, smoke, `test_live_listing_returns_full_summaries` | pass |
| Page 2 differs | `test_pages_differ_so_pagination_is_real`, `test_page_two_asks_upstream_for_page_two` | pass |
| Pagination metadata consistent | `test_meta_reports_page_size_and_an_honest_null_total`, smoke | pass |
| Invalid page / page_size | `test_bad_page_is_rejected`, `test_page_size_above_the_ceiling_is_rejected` | pass |
| No-match filter → 200 empty | `test_empty_result_is_a_200_with_no_rows`, `test_live_subject_filter_returns_only_that_subject` | pass |
| Detail has `source_url` | `test_detail_returns_the_full_record`, smoke | pass |
| Unknown id → 404 | `test_unknown_ebook_is_not_found`, `test_live_unknown_ebook_is_not_found` | pass |
| Malformed id → 400 | `test_malformed_ids_are_rejected_without_calling_upstream` (9 cases) | pass |
| Path traversal rejected | `test_traversal_attempts_never_reach_upstream` (2 cases) | pass |
| Search hit | `test_search_passes_the_query_through`, `test_live_search_finds_shakespeare` | pass |
| Search miss | `test_search_with_no_matches_is_an_empty_200`, `test_live_search_without_matches_is_empty_not_an_error` | pass |
| Blank query | `test_blank_search_is_rejected`, smoke | pass |
| Special characters | `test_special_characters_in_a_query_are_encoded_not_injected`, smoke | pass |
| Non-ASCII query | `test_non_ascii_query_is_accepted`, smoke | pass |
| Over-long query | `test_over_long_query_is_rejected` | pass |
| Cache hit avoids upstream | `test_second_identical_request_is_served_from_cache`, `test_live_cache_avoids_a_second_round_trip` | pass |
| Cache expiry refetches | `test_cache_entry_expires_after_the_ttl` | pass |
| Cache bounded | `test_cache_is_bounded_so_it_cannot_grow_without_limit` | pass |
| Rate-limit spacing | `test_calls_are_spaced_by_at_least_the_minimum_interval` | pass |
| 429 honours `Retry-After` | `test_retry_after_seconds_is_honoured`, `test_retry_after_http_date_is_honoured`, `test_retry_after_in_the_past_does_not_produce_a_negative_wait` | pass |
| Persistent 429 → `RATE_LIMITED` | `test_upstream_conditions_map_onto_the_fixed_vocabulary`, `test_persistent_5xx_gives_up_and_reports_rate_limited` | pass |
| 5xx recovery | `test_transient_5xx_is_retried_and_then_succeeds` | pass |
| Retryable timeout | `test_timeout_is_retried_then_reported`, `test_exhausted_timeouts_report_rate_limited` | pass |
| Circuit opens | `test_breaker_opens_after_the_threshold_and_blocks_further_calls`, `test_breaker_opens_on_the_threshold_failure` | pass |
| Circuit open → `RATE_LIMITED` | `test_open_breaker_reports_rate_limited` | pass |
| Circuit half-open recovery | `test_breaker_allows_one_trial_after_the_cooldown`, `test_breaker_closes_again_after_a_success` | pass |
| 403 / challenge → `UPSTREAM_BLOCKED` | `test_403_is_not_retried`, `test_challenge_page_is_detected_and_not_worked_around`, `test_a_marker_anywhere_in_the_body_is_detected` | pass |
| Parser drift → `UPSTREAM_CHANGED` | `test_unrelated_html_is_reported_as_upstream_changed`, `test_drift_error_names_the_missing_selector`, `test_a_real_fixture_with_its_listing_removed_is_drift` | pass |
| Drift names the missing element in the log | `test_mutated_fixture_returns_upstream_changed_and_logs_the_element` | pass |
| Absent optional field → null | `test_optional_fields_the_site_omits_become_null`, `test_absent_optional_field_is_returned_as_null` | pass |
| Internal error contained | `test_unexpected_internal_error_is_contained`, `test_error_responses_never_leak_internals` | pass |
| Framework 404/405 enveloped | `test_unknown_route_uses_the_error_envelope`, `test_wrong_method_uses_the_error_envelope` | pass |
| Sort context rules | `test_relevance_sort_is_rejected_when_browsing`, `test_relevance_sort_is_accepted_when_searching`, `test_newest_sort_is_omitted_upstream_for_a_browsing_request` | pass |
| Honeypot never requested | No code path builds the URL; `docs/RECON.md` records it | pass |
| Credentials never sent | `test_requests_identify_themselves_and_never_carry_credentials`, `make scan` | pass |

## How the offline suite avoids the network

`tests/conftest.py` provides three doubles, and nothing else in the offline suite
touches a socket:

- **`FakeTransport`** — an `httpx` transport replaying a queue of scripted
  responses, recording every request URL so tests can assert exactly what would
  have gone upstream. It fails loudly on an unexpected request.
- **`FakeClock`** — monotonic and wall-clock seconds, advanced by hand.
- **`RecordingSleeper`** — captures every sleep *and* advances the clock, as a
  real sleep would. This is what lets one test distinguish a retry backoff from
  a rate-limit wait.

`UpstreamClient` accepts all five of `transport`, `clock`, `wall_clock`,
`sleeper` and `random_source` as constructor arguments. That is the seam the
whole offline suite runs through.

## How determinism was achieved

Timing assertions are exact, not approximate, because no real time passes. With
`random_source` returning `0.5`, equal jitter halves to 75% of the nominal
delay: a 1-second backoff is `0.75s` and a 2-second backoff is `1.5s`. Those
numbers are asserted literally in `test_transient_5xx_is_retried_and_then_succeeds`
and `test_retry_after_in_the_past_does_not_produce_a_negative_wait`.

The fixture capture process asserts that trimming a page to its smallest
parseable subtree leaves the parsed result identical to the original, so no
fixture can drift away from what the site actually served.

## Defects found and fixed by these tests

Worth recording, because they are the argument for writing them:

1. **Block detection used a marker present on every page.** The catalogue's
   hidden honeypot link text appears on all pages, so checking for it flagged
   challenge markers, with a test asserting no real fixture contains one.
2. **The parser rejected empty search results.** An out-of-range page and a
   no-match query have different HTML shapes; only the first parsed. Now both
   are accepted, and only genuine drift raises.
3. **Author and reading-ease parsing silently returned null.** Grid rows and
   list rows mark authors and print the reading ease differently. Both layouts
   are now handled.
4. **Sort keys were validated against one list.** `relevance` does not exist
   without a query. Browsing with it silently produced a wrong upstream URL;
   it is now rejected with `BAD_REQUEST`.
5. **Starlette's own 404s bypassed the error envelope.** An unknown route
   returned `{"detail": ...}` instead of `{"error": ...}`. Now handled.
6. **Drift was logged without the missing selector.** The upstream error
   handler logged the error code and the path, so a maintainer seeing
   `UPSTREAM_CHANGED` had nothing pointing at the parser to fix. The log
   line now names the selector, found while writing the test the brief asks
   for.

## Known gaps

- No load test. Rate limiting is verified by injected-clock assertions, not by
  saturating a running server.
- No test for concurrency. The limiter and cache both take a lock; that the
  lock is correct under contention is reasoned about, not measured.
- Live tests are order-dependent in one respect: `test_live_cache_avoids_a_second_round_trip`
  uses a distinct page so it does not depend on an earlier test having run.
- HTML fixtures go stale if the site redesigns. That is the intended failure
  mode — a drift error, not a silent wrong answer.