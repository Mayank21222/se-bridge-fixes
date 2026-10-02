# Test results

Everything below was run on this machine. Commands are reproducible with `make`.

```
Python 3.12.14 · pytest 8.4.2 · uv 0.x · platform darwin
```

## Offline suite — `make test`

```
$ .venv/bin/pytest
119 passed, 14 skipped, 1 warning in 0.35s
```

The 14 skips are the live tests, which are opt-in. **0.35 seconds, no network
access at all.**

| File | Tests | Covers |
| --- | --- | --- |
| `tests/test_parsers.py` | 25 | Every parser against the 12 recorded fixtures |
| `tests/test_politeness.py` | 31 | Cache, rate limit, retries, breaker, block detection |
| `tests/test_api.py` | 63 | Envelope, error vocabulary, validation, routing |
| `tests/test_live.py` | 14 | Real site (skipped without `--live`) |

## Live suite — `make test-live`

```
$ .venv/bin/pytest --live
133 passed, 1 warning in 10.78s
```

All 14 live tests passed against `standardebooks.org`. At one request per
second, 10.78 seconds is the rate limiter working, not slowness.

## Smoke test — `make smoke`

Against a real `uvicorn` on `http://127.0.0.1:8000`:

```
$ .venv/bin/python scripts/smoke_test.py
...
------------------------------------------------------------
all 70 checks passed
```

70 live checks over real HTTP: the envelope, both pages differing, cache hits,
search hits and misses, filters, facets, detail records, every error code, and
the politeness layer holding under repeated traffic.

## Lint, format, types — `make lint`

```
ruff check .        → All checks passed!
ruff format --check → 22 files already formatted
mypy app            → Success: no issues found in 12 source files
```

## Secret scan — `make scan`

```
scanned 29 of 31 tracked files against 9 rules
no secrets, credentials or personal e-mail addresses found
```

Nine rules: private keys, AWS keys, GitHub/Slack/PyPI tokens, generic secret
assignments, credentials in URLs, OPDS membership credentials, and personal
e-mail addresses. Placeholders on `.invalid` and `.example` are allowed through;
everything else fails the build. The scanner was verified against deliberately
injected violations and caught all of them, including one inside a URL.

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
| Parser drift → `UPSTREAM_CHANGED` | `test_unrelated_html_is_reported_as_upstream_changed`, `test_drift_error_names_the_missing_selector` | pass |
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
   every successful response as `UPSTREAM_BLOCKED`. Replaced with HTTP 403 and
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

## Known gaps

- No load test. Rate limiting is verified by injected-clock assertions, not by
  saturating a running server.
- No test for concurrency. The limiter and cache both take a lock; that the
  lock is correct under contention is reasoned about, not measured.
- Live tests are order-dependent in one respect: `test_live_cache_avoids_a_second_round_trip`
  uses a distinct page so it does not depend on an earlier test having run.
- HTML fixtures go stale if the site redesigns. That is the intended failure
  mode — a drift error, not a silent wrong answer.