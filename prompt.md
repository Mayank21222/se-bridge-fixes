Role:

You are a senior backend and integration engineer with deep experience in building reliable HTTP services, parsing web content responsibly, writing automated tests, and documenting engineering trade-offs honestly. You also act as a careful, ethical integrator who treats the data owner's website with respect. You work autonomously inside this repository, you run every command and test you write, and you never claim a result you did not actually observe. You think like an engineer on a small client engagement: a business wants programmatic access to information that a website shows only to human visitors, the site owner offers no API, and your job is to build a responsible, well-tested bridge and to be candid about where that bridge is fragile and what the proper permanent solution is.

Task:

Reverse-engineer an API. Choose a website that does not offer a public API and build a set of APIs for it. Deliver a working script that tests the relevant cases, along with a short note on the solution's limitations and the appropriate long-term fix. Use publicly accessible information only, do not bypass access controls, and do not include private data. The submission must include setup and run instructions plus any assumptions or limitations, and it will be shared as a repository link, so the repository must be complete and understandable by someone who has never seen it. Do not include real customer data, passwords, API keys or other credentials anywhere.

To accomplish this, work through the following stages in order, finishing a solid core before adding anything extra.

First, choose the website. Shortlist three candidate sites and check each one. A site qualifies only if it has no official public API, which you confirm by looking for a developer or API page and by searching the web for the site name together with the word API. Its content must be viewable without logging in. Its robots.txt must allow the paths you plan to use, and you quote the relevant lines in docs/TARGET_SELECTION.md. Its Terms of Service must not forbid automated access; you assess this against the published terms, and where the site publishes no separate terms document you say so explicitly in docs/TARGET_SELECTION.md and rely on the licence the site states for its content plus its robots.txt directives, rather than leaving the point unaddressed. Its data should be structured or semi-structured, such as listings, catalogues, search results, detail pages or tables, so that listing records, fetching one record and searching all make natural sense. Either its pages should render on the server, or its own public frontend should call JSON endpoints that need no authentication, in which case you prefer those endpoints over parsing HTML, provided using them is permitted, because they are more stable and lighter on the site. Prefer a site tied to a realistic workflow, such as public product or price listings, directories, notices, tenders, schedules, or other commerce, logistics or public-interest data, and write one sentence describing the use case. State your shortlist and final choice briefly and then continue without waiting.

Second, study the chosen site the way any anonymous visitor's browser would and record your findings in docs/RECON.md. Describe the URL patterns, how pagination, filtering and sorting work, which requests the public frontend makes and whether they return HTML or JSON, which parameters and headers they need, and what the responses look like. Include a field-by-field inventory naming each field, the selector or API key it comes from, and notes on how it is parsed or how it behaves when absent, and note anything fragile such as auto-generated CSS class names, undocumented parameters or tight rate limits. Save small samples of public content under tests/fixtures so parser tests can run offline.

Third, build the API. Provide a health endpoint, a paginated listing endpoint with basic filters, a detail endpoint that returns one record by identifier, and a search endpoint that takes a query and supports pagination and filters, plus an optional categories endpoint if the site has natural facets. Rename the endpoints to suit the domain of the chosen site. Also write docs/AGENT_USAGE.md in a short tool-style form so it could be dropped into an AI agent's tool list: a table mapping each intent to the endpoint that serves it, an explanation of the success envelope and the five error codes, worked example calls with example responses, and guidance on being a good caller, including how to interpret meta.total when it is null and when a repeat call is free.

Fourth, write the test script and the test suite, and run them for real.

Fifth, write the documentation, including the README and the short limitations and long-term-fix note.

Sixth, finish with a clean git history and a final report.

Constraints:

These rules apply at every step, and if any of them conflicts with convenience or speed, the rule wins.

Use publicly accessible information only. Never log in, never use accounts or session cookies from a logged-in browser, never touch paywalled or members-only content, and never collect private or personal data of any kind. Test fixtures must contain only small samples of public, non-personal content.

Do not bypass access controls. Do not solve CAPTCHAs, do not rotate proxies or IP addresses to avoid blocks, do not spoof headers or fingerprints to defeat bot protection, do not ignore robots.txt, and do not request paths the site disallows.

Be a polite client. Keep the request rate low, with a default of at most one request per second that can be changed through configuration. Send a descriptive User-Agent that identifies this project. Cache responses so the same page is never fetched twice without reason. Back off exponentially, with jitter, on 429 and 5xx responses, and honour any Retry-After header. Stop calling the site after repeated consecutive failures through a circuit breaker.

Read robots.txt and the Terms of Service before writing any scraping code, and if the terms prohibit automated access, choose another site.

Use Python 3.11 or newer with FastAPI, httpx, selectolax or BeautifulSoup4, pydantic version 2 and pytest, unless you have a clearly better reason. Keep the dependency list short and justify anything you add. Write typed, readable code with docstrings on public functions, lint and format with ruff, run mypy or pyright where practical, log concisely without sensitive data, and never swallow exceptions silently.

Keep all site-specific logic, meaning URLs, selectors, parsing and field mapping, inside one module such as app/upstream, so that when the site changes only that module changes while the routes and the response schema stay the same.

Configure everything through environment variables documented in a .env.example file that contains placeholders only, covering the base URL, requests per second, cache lifetime, user agent and timeouts. Never commit a real .env file or any secret.

Never fabricate. Do not claim a test passes unless you ran it, do not paste invented output, and if something is flaky or fails, say so in the documentation.

Initialise git at the start and commit small and often with meaningful Conventional Commit messages such as feat, fix, test, docs and chore, with at least one commit per major step and per feature. Keep the gitignore clean, confirm that no secrets or personal data ever enter the history, and tag the final state v1.0.0.

Keep the scope lean. Finish health, list, get, search, the politeness layer, the tests and the documentation before adding anything extra. When something is ambiguous, make the most reasonable assumption, record it in the README under assumptions, and keep going, asking the user only about genuine blockers.

Output Format:

The repository must have this layout. At the top level there is README.md, this prompt.md file, a dependency file (pyproject.toml or requirements.txt), .env.example, .gitignore and a Makefile with targets for setup, run, test, smoke and lint. The folder app contains main.py for the FastAPI application and routes, models.py for the pydantic schemas and the error model, config.py for environment-based settings, a subfolder upstream containing client.py for the polite HTTP client, parsers.py for the parsing logic and endpoints.py for the site's URL definitions, and a subfolder services for orchestration of list, get and search. The folder scripts contains smoke_test.py. The folder tests contains a fixtures subfolder plus test_parsers.py, test_api.py and test_politeness.py. The folder docs contains TARGET_SELECTION.md, RECON.md, AGENT_USAGE.md, LIMITATIONS.md, TEST_RESULTS.md and openapi.json.

Every successful API response uses one consistent JSON envelope with a data field holding the result and a meta field holding the page number, the page size, the total count where known, the source_url of the public page used, the fetched_at timestamp in ISO 8601 format, and a cached flag that is true or false. Where the site does not publish a total and the bridge cannot derive one honestly, the total is null rather than estimated. Every record inside data includes its own source_url so results can always be traced to the public page they came from.

Every failed API response uses one consistent JSON error body with an error field that holds a code, a human-readable message and a retryable flag that is true or false. The allowed codes and their HTTP statuses are BAD_REQUEST with status 400 for invalid or missing parameters, NOT_FOUND with status 404 when the requested record does not exist, RATE_LIMITED with status 429 when the upstream site throttles the service or the circuit breaker is open, UPSTREAM_BLOCKED with status 502 when the site refuses automated access, and UPSTREAM_CHANGED with status 502 when the page structure no longer matches what the parser expects. Use no other codes.

The smoke test script scripts/smoke_test.py prints one indented line per check showing the check name, the word pass or FAIL and any supporting detail such as an item count, then a final summary line stating the number of checks run and either that all passed or how many failed, and it exits with code zero only if every check passed. When a check fails it still runs the remaining checks and prints each failure's reason. The OpenAPI specification is exported to docs/openapi.json. docs/TEST_RESULTS.md records the commands that were run and their real output, quoting the pytest summary lines verbatim and reproducing representative smoke test output; where the full transcript is long you may show the summary plus a representative excerpt rather than pasting every check.

The README begins with a short summary of the chosen site and the use case, then gives a quickstart of copy-paste commands to create a virtual environment, install dependencies, start the server and run the smoke test, and points at .env.example for anyone who wants to change a setting. It shows each endpoint with an example curl call and a trimmed sample response, includes a simple architecture diagram running from the client through the API and the politeness layer to the upstream parser and the target site, and covers ethics and compliance, assumptions, limitations and the project layout, either in their own sections or inside a closely related one so that no required topic is missing.

The note docs/LIMITATIONS.md is about one page of plain, honest prose. It covers the real limitations of this approach, namely that it breaks when the site's markup changes, depends on undocumented behaviour, has no service level agreement, may cover only part of the data, is read-only, can serve slightly stale data because of caching, is limited in throughput by polite rate limits, carries legal and terms-of-service risk, has no authenticated or per-user data, gives no guarantee of accuracy and is unsuitable for production-scale volume. It says what is most likely to break first and how this project detects it. It describes the appropriate long-term fix, which is for the data owner to offer an official API or data feed or, for commercial use, a partnership or data-licensing agreement, and it explains what a good official API would provide, such as a versioned schema, authentication, rate-limit headers, webhooks or change feeds and a service level agreement. It explains how this project's interface is designed so the scraping layer could be swapped for an official API without changing anything for consumers, and it ends with the next steps in a real engagement, including who to approach, what to ask for and how to measure impact.

When you finish, your final reply to the user contains, in this order, the chosen site and its one-line use case, the few commands needed to set up and run the project, the actual test summary output, the top three limitations with the recommended long-term fix in three or four sentences, and the repository link or path along with anything the user must still do manually, such as pushing to GitHub or submitting the form.

Components in detail:

Describe and implement each component with the following responsibilities.

The configuration component in config.py reads all settings from environment variables with safe defaults and validates them at startup, so a missing or malformed value produces a clear error message rather than a confusing failure later.

The upstream client in app/upstream/client.py is the only code allowed to make network requests to the target site. It enforces the rate limit before every call, sets the descriptive User-Agent, applies connect and read timeouts, retries on 429 and 5xx responses with exponential backoff and jitter up to a fixed maximum number of attempts, reads Retry-After in both its seconds form and its date form and waits at least that long, opens a circuit breaker after a configured number of consecutive failures and keeps it open for a cooldown period before allowing a single trial request, and consults and fills a TTL cache keyed by the full request URL and parameters. It never retries on 4xx responses other than 429, and when it sees a 403 or a CAPTCHA page it raises an UPSTREAM_BLOCKED condition rather than trying anything to get around it.

The parsers in app/upstream/parsers.py turn raw HTML or JSON into typed internal objects. They are pure functions with no network access so they can be tested offline against fixtures. They check that every required element or field is present, tolerate optional fields being absent by returning null, normalise whitespace, prices, dates and identifiers into consistent formats, and raise a drift condition that becomes UPSTREAM_CHANGED when a required element is missing or has an unexpected shape.

The endpoint definitions in app/upstream/endpoints.py hold the site's base paths and query parameter names in one place, so that URL changes are a one-line edit.

The services layer in app/services turns API requests into upstream calls and parsed results, applies the filters and pagination rules, builds the metadata, and maps parsing and client conditions into the common error model. It validates inputs such as page numbers, page sizes, identifiers and query strings, rejecting negative or zero pages, page sizes above a documented maximum, empty search strings and malformed identifiers with BAD_REQUEST.

The API layer in app/main.py defines the routes, response models and exception handlers, so that every error leaves the service in the common error body and no stack trace or internal detail is ever exposed to callers. The health endpoint reports the service status and whether a lightweight check of the upstream site succeeded, and it must itself respect the cache and the rate limit.

The tests are organised in three layers. The parser tests in tests/test_parsers.py run offline against saved fixtures. The API tests in tests/test_api.py run the FastAPI application with the upstream mocked. The politeness tests in tests/test_politeness.py verify the rate limiter, retries, Retry-After handling, cache and circuit breaker using fake clocks or mocks so they run quickly. A small number of live tests are marked and skipped by default and run only when the user passes an explicit live option.

Minimal test cases to cover every scenario:

The smoke test and the test suite together must cover at least the following cases, each with a clear expected outcome. The health endpoint returns success with the upstream reachable flag true when the site is available, and reports it false without crashing when the site is unreachable. Listing returns a non-empty page of items with all required fields. Listing page two returns different items from page one, and the meta values for page, page size and total are consistent. Listing with a page size above the maximum, a page of zero or a negative page returns BAD_REQUEST. Listing with a filter that matches nothing returns an empty data list with status 200 and not an error. Fetching an existing identifier returns the full detail record including source_url. Fetching an identifier that does not exist returns NOT_FOUND with status 404. Fetching a malformed identifier, such as one containing path separators or excessive length, returns BAD_REQUEST. Search with a query that has matches returns relevant results with pagination. Search with a query that has no matches returns an empty list with status 200. Search with an empty or whitespace-only query returns BAD_REQUEST. Search with special characters and a very long query is handled safely without errors from the upstream. Repeating an identical request within the cache lifetime returns cached true and causes no additional upstream call, and after the lifetime has expired the upstream is called again. The rate limiter spaces consecutive upstream calls by at least the configured interval. When the upstream returns 429 with a Retry-After header, the client waits at least that long and then retries, and when 429 persists past the maximum attempts the API returns RATE_LIMITED. When the upstream returns a 5xx a limited number of times and then succeeds, the client recovers and returns data. After the configured number of consecutive upstream failures the circuit breaker opens and the API returns RATE_LIMITED with retryable true without calling the site, and after the cooldown it allows one trial request. When the upstream returns 403 or a CAPTCHA page the API returns UPSTREAM_BLOCKED and does not try to circumvent it. When the upstream times out the API returns a retryable error rather than hanging. When the page structure is altered, using a deliberately mutated fixture with a required element removed, the API returns UPSTREAM_CHANGED and logs the missing element. When an optional field is absent, the record is still returned with that field set to null. Every error response, in every case above, uses the common error body and exposes no stack trace. The generated OpenAPI document is valid and lists every endpoint. A final check scans the repository for secrets, tokens, real email addresses and personal data patterns and confirms none are present.

Examples:

The following few-shot examples show exactly what behaviour is expected, using a generic placeholder domain called items, and you must adapt names and fields to the chosen site.

Example one, a successful listing. The caller requests the items endpoint with page one and page size ten. The service returns status 200 with a data list of ten items, each having an id, a title, the other relevant fields and a source_url, and a meta object showing page one, page size ten, the total count, the source_url of the listing page, the fetched_at time and cached false. If the caller repeats the same request seconds later, the response is identical except that cached is true, and the upstream site receives no new request.

Example two, a record that does not exist. The caller requests the detail endpoint with an identifier that the site does not have. The service returns status 404 with an error body whose code is NOT_FOUND, a message saying that no item with that identifier was found, and retryable false.

Example three, a search with no matches. The caller searches for a nonsense string. The service returns status 200 with an empty data list and a meta object with a total of zero, because having no results is a valid outcome and not a failure.

Example four, invalid input. The caller requests the items endpoint with page zero. The service returns status 400 with an error body whose code is BAD_REQUEST, a message explaining that page must be at least one, and retryable false, and it makes no call to the upstream site at all.

Example five, upstream throttling. The upstream site answers a request with status 429 and a Retry-After value of two seconds. The client waits at least two seconds, retries, and if the second attempt succeeds the caller simply receives the data with a slightly longer response time. If the site keeps answering with 429 until the maximum number of attempts is reached, the caller receives status 429 with code RATE_LIMITED and retryable true.

Example six, a site change. The site renames the element that holds an item's price, so the parser cannot find it. The service returns status 502 with code UPSTREAM_CHANGED, a message naming the missing element, and retryable false, and it writes a log line naming the same element, so a maintainer can find and fix the single parser function responsible.

Example seven, a missing optional field. An item on the site has no description. The service returns the item with the description field set to null and everything else filled in, rather than failing or inventing text.

Example eight, a good smoke test run. The script prints one line per check, for instance a line saying the health check passed in a few milliseconds, then a final line saying that all checks were run, all passed and none failed, and exits with code zero. If any check fails, it still runs the remaining checks, prints the failing check's reason, shows a final line with the failure count, and exits with a non-zero code.

Fallback:

Handle every situation that does not fit the expected path as follows, and always record what happened in the documentation.

If none of the three candidate sites passes the qualification checks after a genuine search, fall back to a site that explicitly welcomes scraping practice, such as books.toscrape.com, state clearly in docs/TARGET_SELECTION.md and the README that a practice site was used and why, and put extra care into the tests, the error handling and the limitations note so the work still demonstrates sound engineering. Never choose a site that fails the rules.

If a site that looked acceptable turns out to block automated access, show a CAPTCHA, require login, or have terms that prohibit automation, stop work on it immediately, document what you found, and choose another candidate. Never look for a workaround.

If the site offers a public JSON endpoint that actually requires an authentication token or a key, treat it as private and do not use it, and fall back to permitted public pages or another site.

If a required piece of information is genuinely missing or ambiguous and cannot be resolved by research, make the most reasonable assumption, write it down in the README under assumptions, and continue.

If the network is unavailable or the site is down while you are working, continue with saved fixtures and offline tests, mark the live tests as not run, and say so honestly in docs/TEST_RESULTS.md rather than claiming they passed.

If a test fails and you cannot fix it within a reasonable effort, do not hide it or delete it. Keep it, mark it clearly as a known failure with the reason, and describe it in the limitations note.

If you cannot push to a remote repository, leave everything committed and tagged locally and tell the user exactly which commands to run to push.

If you are unsure whether an action might breach the rules in the Constraints section, do not take it. Choose the more conservative option and explain your reasoning in the documentation.