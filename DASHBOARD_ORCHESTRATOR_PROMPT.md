# Orchestrator Prompt — Live Dashboard Build

You are the **Build Orchestrator**. Your job is to execute the complete build of the 24/7 Live Dashboard for the Crypto Quant Alpha Scanner. The scanner CLI (v0.1.0) is already built and fully tested with 48 passing tests. You are upgrading it with a web-based dashboard using FastAPI + HTMX + WebSocket.

---

## YOUR RULES (NON-NEGOTIABLE)

1. **You do NOT write implementation code yourself.** You spawn Builder agents to write code. You only run gate commands, read test output, and make pass/fail decisions.
2. **Stories execute in strict sequential order** EXCEPT where explicitly marked as parallelizable below. A story cannot begin until every prior dependency has its gate PASSED.
3. **Gate commands are sacred.** When a gate fails, you read the full error output, send the exact traceback to the Builder agent, and instruct it to fix ONLY the failing issue. Maximum 3 retries per gate before you stop and report the blocker.
4. **No code is merged without a passing gate.** If a Builder produces code that fails its gate, that code is rejected until fixed.
5. **Zero network calls in tests.** If any test attempts a real HTTP/exchange call, that is an automatic failure regardless of test outcome.
6. **No secrets in code.** If any Builder hardcodes an API key, token, or credential, reject immediately.
7. **FROZEN files.** These files must NOT be modified under any circumstance — they are proven correct with 48 tests:
   - `src/quant_scanner/ingestion_engine.py`
   - `src/quant_scanner/math_engine.py`
   - `src/quant_scanner/screener_engine.py`
   - `src/quant_scanner/dashboard.py` (the Rich CLI renderer)
   - `tests/conftest.py`
   - `tests/test_ingestion.py`
   - `tests/test_math.py`
   - `tests/test_screener.py`
   - `tests/test_scaffold.py`
   - `pytest.ini`
8. **The 48 existing tests must pass at EVERY gate.** If any existing test breaks, the gate fails.

---

## STEP 0: READ THE PLAN (Do this FIRST, before spawning any agent)

Read these files in this exact order:

1. `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — Master dashboard architecture, data flow, edge cases, failure registry, and known limitations.
2. `F:\TradingScanner\.claude\dashboard_prd.json` — The 8 stories with hardened acceptance criteria and gate commands. **This is the single source of truth for what each story must do.**
3. `F:\TradingScanner\.claude\docs\PLAN.md` — Original build plan (context only — understand the existing pipeline).
4. `F:\TradingScanner\.claude\docs\ARCHITECTURE.md` — ADRs and component diagrams.

Also read the existing code to understand what you're building on top of:
5. `F:\TradingScanner\src\quant_scanner\screener_engine.py` — The `run_screen()` function that the scheduler will call.
6. `F:\TradingScanner\src\quant_scanner\cli.py` — The existing CLI you will modify.
7. `F:\TradingScanner\pyproject.toml` — Current dependencies you will extend.

Do NOT proceed until you have read and understood all documents.

---

## CRITICAL BUGS CAUGHT IN AUDIT (Builders MUST know these)

Every Builder prompt below includes the relevant warnings, but here is the master list:

| # | Severity | Bug | Required Fix |
|---|----------|-----|-------------|
| 1 | **CRITICAL** | `uvicorn[standard]` installs `uvloop` which **crashes on Windows** | Use `uvicorn>=0.27` (no `[standard]`), add `websockets>=12.0` explicitly |
| 2 | **CRITICAL** | `np.nan` in DataFrame → `json.dumps` produces `NaN` which is invalid JSON | `get_latest_as_records()` must convert NaN→None via `df.where(df.notna(), None)` |
| 3 | **HIGH** | `httpx.ASGITransport` cannot test WebSocket endpoints | Use Starlette `TestClient` for WS tests, `httpx.AsyncClient` for HTTP |
| 4 | **HIGH** | HTMX poll + WebSocket fire at same time → double table refresh | WS triggers via JS `htmx.ajax()`, NOT a second `hx-trigger` attribute |
| 5 | **HIGH** | `get_latest()` returns mutable reference → route handler could corrupt store | Return `self._latest.copy()`, store `df.copy()` on update |
| 6 | **HIGH** | No rate limit on POST /api/refresh → DoS vector | 10-second cooldown in `trigger_now()` |
| 7 | **HIGH** | `httpx.AsyncClient` may not trigger lifespan unless used as async context manager | ALL tests must use `async with httpx.AsyncClient(...)` |
| 8 | **MEDIUM** | Tests using `asyncio.sleep` for timing → flaky on Windows | Use `asyncio.Event` synchronization instead |
| 9 | **MEDIUM** | Scan takes longer than interval → scan drift | Sleep = `max(0, interval - scan_duration)` using `time.monotonic()` |
| 10 | **MEDIUM** | CDN-only HTMX/Charts → dashboard broken without internet | Bundle local copies in `static/vendor/` with fallback script tags |
| 11 | **MEDIUM** | `_server_config` module-level mutable state pollutes tests | Autouse fixture resets to `_DEFAULT_CONFIG` |
| 12 | **MEDIUM** | SIGTERM not supported on Windows | Document: only SIGINT (Ctrl+C) works |

---

## STEP 1: DASH-001 — Dependencies & Server Skeleton (SEQUENTIAL, BLOCKING)

This story MUST complete first because it installs FastAPI/uvicorn and creates the server module all subsequent stories depend on.

**Spawn one Builder agent with this exact instruction:**

> **Your task: DASH-001 — Dashboard Dependencies & FastAPI Server Skeleton**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\dashboard_prd.json` — story "DASH-001" for all acceptance criteria
> - `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — "New Dependencies" section and DASH-001 section
> - `F:\TradingScanner\pyproject.toml` — existing dependencies (you will ADD to this file, not replace)
>
> You must edit/create these files:
> - `F:\TradingScanner\pyproject.toml` — ADD new dependencies and package-data
> - `src/quant_scanner/server.py` — CREATE FastAPI app with health endpoint
> - `tests/test_server.py` — CREATE with httpx.AsyncClient tests
>
> **CRITICAL WARNINGS:**
> - **DO NOT use `uvicorn[standard]`** — it installs `uvloop` which CRASHES on Windows. Use plain `uvicorn>=0.27`
> - **ADD `websockets>=12.0`** — required for FastAPI WebSocket support (normally included in `[standard]`)
> - **ADD `[tool.setuptools.package-data]`** to pyproject.toml: `quant_scanner = ["templates/**/*.html", "static/**/*"]`
> - Use `time.monotonic()` for uptime tracking, NOT `datetime.now()` (immune to NTP sync)
> - Add `GET /favicon.ico` → 204 No Content (prevents browser 404 log spam)
> - Tests MUST use `async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:` — the async context manager triggers lifespan events
>
> After editing pyproject.toml, run: `.venv/Scripts/python -m pip install -e ".[dev]"`
>
> When done, report back. Do NOT run the gate command yourself.

**After the Builder reports, YOU run the gate:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_server.py tests/test_scaffold.py tests/test_math.py tests/test_ingestion.py tests/test_screener.py tests/test_cli.py -v
```

**Pass criteria:** Exit code 0. All new server tests PASSED. All 48 existing tests still PASSED.

---

## STEP 2: DASH-002 + DASH-003 — IN PARALLEL

These two stories have ZERO file overlap. DASH-002 creates `scan_store.py`. DASH-003 creates `scheduler.py`. **Spawn both Builder agents simultaneously.**

### Builder Agent A: DASH-002 — ScanStore

> **Your task: DASH-002 — ScanStore: Coroutine-Safe In-Memory Data Store**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\dashboard_prd.json` — story "DASH-002" for all acceptance criteria
> - `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — DASH-002 section
>
> You must create:
> - `src/quant_scanner/scan_store.py` — the ScanStore class
> - `tests/test_scan_store.py` — all tests listed in the PRD
>
> **CRITICAL WARNINGS:**
> - This is "coroutine-safe" (asyncio.Lock), NOT thread-safe. Add docstring stating this.
> - `update()` MUST store `df.copy()` — not the original reference
> - `get_latest()` MUST return `self._latest.copy()` — prevents route handlers from mutating stored data
> - `get_latest_as_records()` MUST convert NaN→None: `df.where(df.notna(), None).to_dict(orient="records")`. This is the ONLY method API routes should use for JSON. Without this, `json.dumps(float('nan'))` produces `NaN` which is INVALID JSON (RFC 8259).
> - `get_status()` does NOT include `uptime_seconds` — that belongs only in `/api/health`
> - Include `set_scanning()` and `set_next_scan_at()` methods
> - The `test_get_latest_as_records_nan_safe` test must verify `json.dumps()` succeeds on the output
>
> When done, report back. Do NOT run the gate command yourself.

### Builder Agent B: DASH-003 — Scheduler

> **Your task: DASH-003 — Background Scan Scheduler**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\dashboard_prd.json` — story "DASH-003" for all acceptance criteria
> - `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — DASH-003 section
> - `src/quant_scanner/screener_engine.py` — understand `run_screen()` signature (you will call it)
> - `src/quant_scanner/scan_store.py` — READ the ScanStore interface (if DASH-002 isn't done yet, use the interface from the PRD acceptance criteria)
>
> You must create:
> - `src/quant_scanner/scheduler.py` — the ScanScheduler class
> - `tests/test_scheduler.py` — all tests listed in the PRD
>
> **CRITICAL WARNINGS:**
> - Import `run_screen` LAZILY inside `_run_one_scan()` (not at module top) — this prevents circular imports and ensures `--dry-run` works without importing the server
> - Use `time.monotonic()` for scan duration tracking, NOT `datetime.now()`
> - Sleep after scan = `max(0, interval - (time.monotonic() - scan_start))` — prevents drift when scans take a long time
> - `trigger_now()` has a 10-second cooldown: `if time.monotonic() - self._last_trigger_time < 10: return`
> - `_run_one_scan()` must catch ALL exceptions (bare `except Exception`), call `store.set_error(str(e))` and `logger.exception()`, and NOT re-raise. The loop MUST continue.
> - Use `asyncio.Event` for trigger mechanism, NOT polling
> - **TEST FLAKINESS PREVENTION:** Do NOT use `asyncio.sleep` in tests for timing. Instead, mock `run_screen` to set an `asyncio.Event` when called, and have tests `await` that event. Use a pytest fixture with `yield` + `await sched.stop()` for cleanup.
>
> When done, report back. Do NOT run the gate command yourself.

**After BOTH Builders report, YOU run both gates (can run in parallel):**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_scan_store.py -v
```

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_scheduler.py -v
```

**Pass criteria:** Both exit code 0, all tests PASSED.

---

## STEP 3: DASH-004 — Routes & Templates (SEQUENTIAL, depends on DASH-001 + 002 + 003)

**Spawn one Builder agent:**

> **Your task: DASH-004 — FastAPI Routes & Jinja2 Template Rendering**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\dashboard_prd.json` — story "DASH-004" for all acceptance criteria
> - `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — DASH-004 section
> - `src/quant_scanner/server.py` — the existing server skeleton from DASH-001
> - `src/quant_scanner/scan_store.py` — the ScanStore from DASH-002
> - `src/quant_scanner/scheduler.py` — the ScanScheduler from DASH-003
>
> You must edit/create:
> - `src/quant_scanner/server.py` — ADD lifespan wiring, routes, Jinja2 config, static mount
> - `src/quant_scanner/templates/index.html` — minimal valid HTML5 with HTMX
> - `src/quant_scanner/templates/partials/table.html` — scan results table
> - `src/quant_scanner/templates/partials/status.html` — status bar
> - `tests/test_server.py` — ADD route tests
>
> **CRITICAL WARNINGS:**
> - **NaN JSON serialization:** `GET /api/scan` MUST use `store.get_latest_as_records()` (which converts NaN→None), NEVER `df.to_dict()` directly. Test this with `test_api_scan_nan_safe`.
> - **Jinja2 filters MUST handle None and NaN without crashing:** `format_mcap(None)` → "N/A", `format_mcap(float('nan'))` → "N/A". Use `math.isnan()` with try/except TypeError for the NaN check.
> - **Server config:** Create `_DEFAULT_CONFIG` dict and `_server_config` dict (copy of defaults). The `configure()` function updates `_server_config`. Export `_DEFAULT_CONFIG` so tests can reset state.
> - **Test pollution prevention:** Add an autouse fixture that resets `_server_config` to `_DEFAULT_CONFIG` before and after each test.
> - **Lifespan in tests:** Use `async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:` — the async context manager is REQUIRED to trigger lifespan (which creates store/scheduler).
> - Mock `run_screen` in ALL tests — ZERO network calls. Use `unittest.mock.patch("quant_scanner.screener_engine.run_screen")`.
>
> When done, report back. Do NOT run the gate command yourself.

**After the Builder reports, YOU run the gate:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_server.py -v
```

**Pass criteria:** Exit code 0, all route tests PASSED.

---

## STEP 4: DASH-005 — Frontend (SEQUENTIAL, depends on DASH-004)

> **Your task: DASH-005 — Frontend Styling, Color Coding & Chart Placeholder**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\dashboard_prd.json` — story "DASH-005" for all acceptance criteria
> - `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — DASH-005 section
> - `src/quant_scanner/templates/index.html` — the minimal template from DASH-004 (you will upgrade it)
> - `src/quant_scanner/dashboard.py` — the Rich CLI renderer (understand the color rules to replicate)
>
> You must edit/create:
> - `src/quant_scanner/templates/index.html` — UPGRADE to full production layout
> - `src/quant_scanner/templates/partials/table.html` — ADD CSS color classes
> - `src/quant_scanner/templates/partials/status.html` — ADD colored badges
> - `src/quant_scanner/static/style.css` — CREATE dark theme
> - `src/quant_scanner/static/charts.js` — CREATE placeholder
> - `src/quant_scanner/static/vendor/htmx.min.js` — DOWNLOAD and bundle
> - `src/quant_scanner/static/vendor/lightweight-charts.min.js` — DOWNLOAD and bundle
> - `tests/test_server.py` — ADD frontend tests
>
> **CRITICAL WARNINGS:**
> - **CDN with local fallback:** Load HTMX from CDN first, then fallback:
>   `<script src="https://unpkg.com/htmx.org@2.0.4"></script>`
>   `<script>window.htmx || document.write('<script src="/static/vendor/htmx.min.js"><\/script>')</script>`
>   Same pattern for Lightweight Charts. Without the local fallback, the dashboard is completely non-functional without internet.
> - **Download the vendor files:** Use curl or similar to download the minified JS files into `static/vendor/`. These are ~60KB total and MUST be committed.
> - **Display active config:** Show the active exchange, min_beta, min_corr, min_volume in the header or status area so the user knows which filters are running.
> - **Dark theme colors:** Background `#0d1117`, text `#c9d1d9`, green `#3fb950`, yellow `#d29922`, dim `#484f58`
> - **Do NOT add WebSocket JavaScript yet** — that is DASH-006's responsibility. Only add the HTMX polling triggers.
>
> When done, report back. Do NOT run the gate command yourself.

**After the Builder reports, YOU run the gate:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_server.py -v && .venv/Scripts/python -c "from quant_scanner.server import app; print('Server imports OK')"
```

**Pass criteria:** Exit code 0, all tests PASSED, import succeeds.

---

## STEP 5: DASH-006 — WebSocket (SEQUENTIAL, depends on DASH-005)

> **Your task: DASH-006 — WebSocket Live Push Updates**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\dashboard_prd.json` — story "DASH-006" for all acceptance criteria
> - `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — DASH-006 section
> - `src/quant_scanner/server.py` — the server you will update
> - `src/quant_scanner/scheduler.py` — the scheduler you will wire to broadcast
> - `src/quant_scanner/templates/index.html` — the template you will add WS JavaScript to
>
> You must create/edit:
> - `src/quant_scanner/ws_manager.py` — CREATE ConnectionManager class
> - `src/quant_scanner/server.py` — ADD WS endpoint, wire manager to scheduler
> - `src/quant_scanner/templates/index.html` — ADD WebSocket JavaScript (ONLY the `<script>` block, do NOT modify the HTML structure from DASH-005)
> - `tests/test_ws_manager.py` — CREATE with mock WebSocket tests
> - `tests/test_server.py` — ADD WebSocket endpoint integration test
>
> **CRITICAL WARNINGS:**
> - **Double-refresh prevention:** When WS `scan-complete` fires, the JS must:
>   1. `htmx.trigger('#results-table', 'htmx:abort')` — cancel any pending HTMX poll
>   2. `htmx.ajax('GET', '/partials/table', '#results-table')` — fetch fresh table
>   Do NOT add a second `hx-trigger` attribute. The table div keeps `hx-trigger="every 60s"` only. WS triggers via JS.
> - **WebSocket testing:** `httpx.ASGITransport` CANNOT test WebSocket. For the WS endpoint integration test, use Starlette's `TestClient`:
>   ```python
>   from starlette.testclient import TestClient
>   def test_ws_endpoint_connects():
>       with TestClient(app) as client:
>           with client.websocket_connect("/ws/updates") as ws:
>               pass  # connection established
>   ```
>   Note: This test is synchronous (Starlette TestClient uses anyio internally).
> - **Auto-reconnect:** JS must reconnect on close/error with exponential backoff (1s, 2s, 4s, 8s, max 30s).
> - **broadcast() must be fault-tolerant:** If one client's `send_json` raises, catch it, remove that client, continue to other clients. NEVER let one bad client crash the broadcast loop.
>
> When done, report back. Do NOT run the gate command yourself.

**After the Builder reports, YOU run the gate:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_ws_manager.py tests/test_server.py -v
```

**Pass criteria:** Exit code 0, all WebSocket manager tests PASSED, all server tests PASSED.

---

## STEP 6: DASH-007 — CLI --serve (SEQUENTIAL, depends on DASH-006)

> **Your task: DASH-007 — CLI --serve Integration**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\dashboard_prd.json` — story "DASH-007" for all acceptance criteria
> - `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — DASH-007 section
> - `src/quant_scanner/cli.py` — the existing CLI you will modify
> - `src/quant_scanner/server.py` — the server you will launch
>
> You must edit:
> - `src/quant_scanner/cli.py` — ADD --serve, --port, --host, --refresh-interval flags
> - `tests/test_cli.py` — ADD new argument tests
>
> **CRITICAL WARNINGS:**
> - **LAZY IMPORTS:** When `args.serve` is True, import `server` and `uvicorn` INSIDE the if-block, NOT at module top. This ensures `--dry-run` works even if FastAPI isn't importable. The existing `--dry-run` path must NOT import any dashboard modules.
> - **Mutual exclusion:** `--serve` + `--dry-run` together → print error, `sys.exit(1)`
> - **Port-in-use handling:** Wrap `uvicorn.run()` in `try/except OSError` and print a friendly message: `"Port {port} is already in use. Try --port {port+1}"`
> - **Configuration flow:** Build `scan_kwargs` dict from CLI args, call `server.configure(scan_kwargs=scan_kwargs, interval_seconds=args.refresh_interval)` BEFORE `uvicorn.run()`
> - **Existing behavior untouched:** Both `--dry-run` and bare `python -m quant_scanner` (one-shot scan) must work exactly as before
>
> When done, report back. Do NOT run the gate command yourself.

**After the Builder reports, YOU run the gate:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/test_cli.py -v && .venv/Scripts/python -m quant_scanner --dry-run
```

**Pass criteria:** Exit code 0, all CLI tests PASSED, dry-run produces formatted Rich table.

---

## STEP 7: DASH-008 — Resilience & Integration (SEQUENTIAL, depends on ALL)

> **Your task: DASH-008 — Resilience Hardening & Full Integration Tests**
>
> Read these files FIRST:
> - `F:\TradingScanner\.claude\dashboard_prd.json` — story "DASH-008" for all acceptance criteria
> - `F:\TradingScanner\.claude\docs\DASHBOARD_PLAN.md` — DASH-008 section and the full "Edge Cases & Failure Modes Registry" table (29 entries)
>
> Also read ALL source files to understand the complete system:
> - `src/quant_scanner/server.py`
> - `src/quant_scanner/scan_store.py`
> - `src/quant_scanner/scheduler.py`
> - `src/quant_scanner/ws_manager.py`
> - `src/quant_scanner/cli.py`
>
> You must create/edit:
> - `tests/test_integration_dashboard.py` — CREATE with all integration tests
> - `src/quant_scanner/server.py` — ADD enhanced /api/health, structured startup logging
> - `src/quant_scanner/scheduler.py` — ADD scan duration logging
>
> **CRITICAL TEST CASES (all mock run_screen, ZERO network calls):**
> - `test_full_lifecycle`: mock run_screen → start app → GET /api/health ok → trigger scan → GET /api/scan has results → GET /partials/table contains symbols → GET /partials/status shows "idle"
> - `test_error_recovery`: run_screen raises first call, succeeds second → verify error shown then cleared
> - `test_manual_refresh`: long interval, POST /api/refresh → verify results appear without waiting
> - `test_empty_scan_result`: empty DataFrame → "No coins" message, status "idle" not "error"
> - `test_concurrent_requests`: 20 simultaneous GET /api/scan → all return 200
> - `test_nan_in_scan_produces_valid_json`: df with NaN → `json.loads(response.text)` succeeds
> - `test_first_scan_shows_scanning_status`: during scan, status badge shows "scanning"
>
> **Enhanced /api/health response:**
> ```json
> {
>     "status": "ok",
>     "version": "0.1.0",
>     "uptime_seconds": 3600.5,
>     "scanner": {
>         "status": "idle",
>         "last_scan_at": "2026-02-25T14:30:00+00:00",
>         "scan_count": 42,
>         "coin_count": 7,
>         "error": null
>     },
>     "websocket_clients": 2
> }
> ```
>
> When done, report back. Do NOT run the gate command yourself.

**After the Builder reports, YOU run the FINAL gate:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m pytest tests/ -v --tb=short
```

**Pass criteria:** Exit code 0. ALL tests pass — original 48 + new ~58 = ~106 total. Zero failures, zero errors.

**Then run the dry-run to confirm nothing broke:**

```bash
cd /f/TradingScanner && .venv/Scripts/python -m quant_scanner --dry-run
```

**Pass criteria:** Formatted Rich table appears with 3 coins, clean exit.

---

## EXECUTION SUMMARY

```
STEP 0: Read all plan docs                            [YOU, synchronous]
STEP 1: DASH-001 skeleton + deps                      [1 Builder, sequential]
        └── gate: pytest ALL test files -v
STEP 2: DASH-002 store + DASH-003 scheduler            [2 Builders, PARALLEL]
        ├── gate: pytest test_scan_store.py -v
        └── gate: pytest test_scheduler.py -v
STEP 3: DASH-004 routes + templates                    [1 Builder, sequential]
        └── gate: pytest test_server.py -v
STEP 4: DASH-005 frontend + CSS                        [1 Builder, sequential]
        └── gate: pytest test_server.py -v + import check
STEP 5: DASH-006 WebSocket                             [1 Builder, sequential]
        └── gate: pytest test_ws_manager.py + test_server.py -v
STEP 6: DASH-007 CLI --serve                           [1 Builder, sequential]
        └── gate: pytest test_cli.py -v + --dry-run
STEP 7: DASH-008 resilience + integration              [1 Builder, sequential]
        └── gate: pytest tests/ -v --tb=short (ALL ~106 tests)
```

**Total Builder agents spawned: 8** (1 + 2 parallel + 1 + 1 + 1 + 1 + 1)
**Total gate commands: 9** (8 story gates + 1 final dry-run check)

---

## FAILURE PROTOCOL

If a gate fails:
1. Read the FULL pytest traceback or error output
2. Identify the exact assertion or import error
3. Send the error to the responsible Builder agent with instruction: "Fix ONLY this issue. Do not refactor other code. Do not modify FROZEN files."
4. Re-run the gate
5. If it fails 3 times, STOP and report: which story, which test, what the error is, and what you've tried

If a Builder modifies any FROZEN file, reject immediately — that's a constraint violation.
If any existing test from the original 48 breaks, that's an automatic gate failure.

---

## WHAT SUCCESS LOOKS LIKE

When you are done, you should be able to report:

```
DASHBOARD BUILD COMPLETE — All 8 stories passed.

DASH-001: PASSED — FastAPI skeleton, health endpoint, deps installed
DASH-002: PASSED — ScanStore with NaN-safe serialization (11 tests)
DASH-003: PASSED — Scheduler with Event-based sync (8 tests)
DASH-004: PASSED — All routes, Jinja2 templates, HTMX wiring (12 tests)
DASH-005: PASSED — Dark theme CSS, color coding, CDN+local fallback (5 tests)
DASH-006: PASSED — WebSocket manager + endpoint + auto-reconnect JS (8 tests)
DASH-007: PASSED — CLI --serve flag with lazy imports (8 tests)
DASH-008: PASSED — Integration tests, enhanced health, logging (7 tests)

Original 48 tests: ALL PASSING
New dashboard tests: ~58 PASSING
Total: ~106 tests, ZERO failures

Final smoke test:
  python -m quant_scanner --dry-run          → Rich table ✓
  python -m quant_scanner --serve --port 8080 → Dashboard at localhost:8080 ✓
```

Begin now. Start with STEP 0 — read all plan documents.
