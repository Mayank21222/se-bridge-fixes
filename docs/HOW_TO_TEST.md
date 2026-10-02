# How to test this project

Everything below was run on the machine that wrote this file, and the output is
reproduced from those runs. Five levels, cheapest first. You do not need to run
all of them.

| # | Level | Command | Needs the internet | Takes |
| --- | --- | --- | --- | --- |
| 1 | Lint and types | `make lint` | no | ~5s |
| 2 | Offline tests | `make test` | no | ~0.5s |
| 3 | Live tests | `make test-live` | yes | ~11s |
| 4 | Smoke test | `make run` + `make smoke` | yes | ~15s |
| 5 | By hand | `curl` | yes | a minute |

---

## Before anything else

```bash
cd /Users/mayankkashyap/Desktop/FDE_Razorpay
make setup
```

This creates `.venv` and installs the runtime and dev dependencies. It needs
Python 3.11 or newer; the Makefile asks for 3.12. Everything after this point
uses that virtualenv, so you never install anything into your system Python.

---

## Level 1 — lint, format and types

```bash
make lint
```

```
$ make lint
.venv/bin/ruff check .
All checks passed!
.venv/bin/ruff format --check .
28 files already formatted
.venv/bin/python -m mypy app
Success: no issues found in 12 source files
```

Exit code 0. `ruff check` looks for style and common errors, `ruff format
--check` confirms the formatting matches, and `mypy` type-checks the `app`
package. No network access.

---

## Level 2 — the offline suite

```bash
make test
```

```
$ make test
.venv/bin/pytest
.................................................................sssssss [ 52%]
sssssss...........................................................       [100%]
=============================== warnings summary ===============================
tests/test_api.py::test_root_points_at_the_docs
  .../fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx`
  with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
124 passed, 14 skipped, 1 warning in 0.38s
```

**Expected: `124 passed, 14 skipped`.** The 14 skips are the live tests, which
are opt-in. This level touches no network at all — the upstream client is
replaced by a scripted transport, a fake clock and a recording sleeper, so it
finishes in under half a second and never depends on the site being up.

What the four files cover:

| File | Tests | Covers |
| --- | --- | --- |
| `tests/test_parsers.py` | 28 | Every parser against the 12 recorded pages in `tests/fixtures/` |
| `tests/test_politeness.py` | 31 | Cache, rate limiter, retries, `Retry-After`, circuit breaker, block detection |
| `tests/test_api.py` | 65 | The envelope, the five error codes, validation, routing |
| `tests/test_live.py` | 14 | The real site; skipped unless you pass `--live` |

The one warning comes from Starlette's test client and is not a failure.

---

## Level 3 — the live suite

```bash
make test-live
```

```
$ make test-live
138 passed, 1 warning in 10.75s
```

**Expected: `138 passed`.** These 14 extra tests hit `standardebooks.org`
through the real polite client — no mocks — so they prove the selectors still
match the live site. If one fails, the site changed rather than your code.

Expect roughly 11 seconds. That is the one-request-per-second rate limiter
working, not slowness.

---

## Level 4 — the smoke test, end to end

This is the closest thing to what a reviewer would do by hand: a real server,
real HTTP, real network, no mocks.

Terminal one:

```bash
make run
```

Terminal two:

```bash
make smoke
```

```
$ make smoke
.venv/bin/python scripts/smoke_test.py

Smoke test against http://127.0.0.1:8000

service
  PASS  GET / returns a pointer to the docs (17ms) HTTP 200
  PASS  root advertises docs, openapi and health (0ms)
  PASS  openapi.json is served (1ms) HTTP 200
  PASS  openapi documents all six endpoints (0ms) 6 paths

health
  PASS  GET /health answers 200 (1ms) HTTP 200
  PASS  upstream is reachable (0ms) breaker=closed
  PASS  the health probe went through the same limiter as traffic (0ms)
  ...

------------------------------------------------------------
70 checks run, 70 passed, 0 failed
```

**Expected: `70 checks run, 70 passed, 0 failed`.** Each line carries the check
name, PASS or FAIL, and how long it took. The script exits 0 only if every check
passed; if one fails it still runs the rest, prints each reason, and exits
non-zero.

If you want the full transcript, it is in
[`docs/TEST_RESULTS.md`](TEST_RESULTS.md) unedited.

---

## Level 5 — checking it by hand

Start the server with `make run`, then in another terminal.

**Health — is the bridge up and is the site reachable?**

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

```json
{
    "data": {
        "status": "ok",
        "upstream_reachable": true,
        "circuit_breaker": "closed",
        "upstream_check_url": "https://standardebooks.org/ebooks?view=list&per-page=1&page=1",
        "service_version": "1.0.0"
    },
    "meta": { "...": "..." }
}
```

`upstream_reachable: false` would still be HTTP 200 — a monitor can tell a
degraded bridge from a broken one by the body, not the status code.

**Every endpoint answers 200:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/v1/ebooks?page_size=2"
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/v1/search?q=shakespeare&page_size=1"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/v1/ebooks/edwin-a-abbott/flatland
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/v1/subjects
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/v1/authors/edwin-a-abbott
```

Observed: `200` on all six.

**Bad input is rejected before any request goes upstream:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/v1/ebooks?page=0"
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/v1/ebooks?page_size=99"
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/v1/search?q="
```

Observed: `400`, `400`, `400`. And the body is always the same shape:

```bash
curl -s "http://127.0.0.1:8000/v1/ebooks?page=0" | python3 -m json.tool
```

```json
{
    "error": {
        "code": "BAD_REQUEST",
        "message": "page must be at least 1",
        "retryable": false
    }
}
```

**A missing record is 404, and a traversal attempt is 400:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/v1/ebooks/nobody/nothing
curl -s --path-as-is -o /dev/null -w "%{http_code}\n" \
  "http://127.0.0.1:8000/v1/ebooks/../../../etc/passwd"
```

Observed: `404` then `400 BAD_REQUEST`. Use `--path-as-is`, because curl
normalises `../` away before sending and the request would never reach the app.

**No matches is a 200 with an empty list, not an error:**

```bash
curl -s -o /tmp/nr.json -w "%{http_code}\n" "http://127.0.0.1:8000/v1/search?q=zzzznotarealbook"
python3 -c "import json;print('items:',len(json.load(open('/tmp/nr.json'))['data']))"
```

Observed: `200` and `items: 0`.

**The cache means a repeat call is free.** Call the same URL twice and watch
`meta.cached` change:

```bash
curl -s "http://127.0.0.1:8000/v1/ebooks?page_size=3" \
  | python3 -c "import sys,json;print('cached:',json.load(sys.stdin)['meta']['cached'])"
curl -s "http://127.0.0.1:8000/v1/ebooks?page_size=3" \
  | python3 -c "import sys,json;print('cached:',json.load(sys.stdin)['meta']['cached'])"
```

Observed: `cached: False` then `cached: True`. The second call cost the target
site nothing.

**The OpenAPI document lists all six endpoints, 17 schemas:**

```bash
curl -s http://127.0.0.1:8000/openapi.json \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d['paths']),'paths');print(len(d['components']['schemas']),'schemas')"
```

Observed: `6 paths` and `17 schemas`. Interactive docs are at
<http://127.0.0.1:8000/docs>.

---

## The secret scan

```bash
make scan
```

```
$ make scan
.venv/bin/python scripts/secret_scan.py
scanned 31 of 33 tracked files against 9 rules
no secrets, credentials or personal e-mail addresses found
rules checked: private key, AWS access key id, GitHub token, Slack token,
PyPI token, generic secret assignment, credential in a URL, opds membership
credential, personal e-mail address
```

Two tracked files are skipped deliberately, and the reason is worth knowing: the
scanner itself contains every pattern it looks for, and `docs/TEST_RESULTS.md`
contains a deliberately injected example e-mail address used to prove the rules
still fire. Scanning either would always report a finding.

---

## Refreshing the OpenAPI document

```bash
make openapi
```

Rewrites `docs/openapi.json` from the running app. Run it after changing a
route, a parameter or a response model, then commit the result.

---

## What a failure looks like, and what to do

| Symptom | Meaning | Do |
| --- | --- | --- |
| Level 2 fails | Your change broke a parser, the envelope or validation | Read the failure; it names the test |
| Level 2 passes, level 3 fails | The **site** changed | `UPSTREAM_CHANGED` names the selector; fix `app/upstream/parsers.py` |
| Levels 3 and 4 fail on connection | The site is down, or you are offline | Nothing to fix; level 2 still works |
| `retryable: true` | The bridge is throttling itself | Wait, then retry. Do not raise the rate limit |
| `UPSTREAM_BLOCKED` | The site refused this client | Stop. Do not work around it |
| Level 4 fails but 3 passes | Stale server | Restart `make run` |

Level 2 is the one to run while you work: it is fast, deterministic and offline.

---

## Running a single test

```bash
.venv/bin/pytest tests/test_parsers.py -v
.venv/bin/pytest -k "cache"
.venv/bin/pytest --live -k "search"
```

`--live` is what enables the tests that touch the real site; without it they
are skipped.

---

## The short version

```bash
make setup
make test          # 124 passed, 14 skipped, no network
make lint          # ruff and mypy clean
make run           # terminal 1
make smoke         # terminal 2 — 70 checks run, 70 passed, 0 failed
```