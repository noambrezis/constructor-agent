# Bob Agent — Modular Implementation Plan

## Context
The spec (constructor-agent/spec/tech_spec.md) is fully written across 29 sections.
The task is to scaffold and implement the actual `bob-agent/` application from scratch
inside the constructor-agent repo, module by module, so each can be built, tested,
and deployed independently before the next begins.

The stack: Python 3.12 · FastAPI · LangGraph · PostgreSQL (Neon) · Redis (Upstash) ·
ARQ task queue · WhatsApp Bridge (existing, Node.js on Railway).

---

## Module Map (Dependency Order)

```
M0: Repo Scaffold          ← no deps
M1: Infrastructure         ← no deps (external services)
M2: Database Layer         ← M0, M1
M3: Core Services          ← M0, M1
M4: Agent Core             ← M2, M3
M5: Agent Tools            ← M2, M3, M4
M6: API Layer              ← M2, M3, M5, M7
M7: Task Queue             ← M3, M5
M8: Admin API              ← M2, M3
M9: Observability          ← M0 (cross-cutting, added incrementally)
M10: Testing               ← all modules
M11: CI/CD                 ← M10
```

---

## M0 — Repo Scaffold

**Delivers:** Empty but runnable Python project with all tooling configured.
No business logic — just the skeleton that every other module builds on.

**Files created:**
```
bob-agent/
├── app/__init__.py
├── app/main.py              # FastAPI stub (returns 200 on /health only)
├── app/config.py            # Full Settings class (pydantic-settings, all fields)
├── pyproject.toml           # ruff, mypy, pytest config
├── requirements.txt         # all production deps pinned
├── requirements-dev.txt     # ruff, mypy, pytest, pytest-asyncio, pytest-cov, httpx
├── Dockerfile               # python:3.12-slim, STOPSIGNAL SIGTERM
├── docker-compose.yml       # bob-agent + bob-worker + postgres:16 + redis:7-alpine
├── docker-compose.test.yml  # test-db + test-redis only
├── alembic.ini
├── .env.example             # all keys, blank values
├── .gitignore               # .env, __pycache__, .mypy_cache, .pytest_cache
└── .pre-commit-config.yaml  # ruff, ruff-format, detect-private-key, no-commit-to-branch
```

**Key decisions:**
- `app/config.py` is fully written here with ALL settings from spec §11 so every
  subsequent module can import `from app.config import settings` immediately
- `docker-compose.yml` includes healthchecks on db and redis from day one (spec §28)
- `pyproject.toml` sets `asyncio_mode = "auto"` for pytest and `strict = true` for mypy

**Done criteria:**
- `docker compose up` starts without errors
- `GET /health` returns `{"status": "ok"}`
- `ruff check .` and `mypy app/` pass with zero errors

---

## M1 — Infrastructure

**Delivers:** All external services provisioned and connection strings ready.
Nothing to deploy — this is account setup and configuration only.

**Steps (manual, one-time):**

### 1. Neon PostgreSQL
- Create project `bob-agent` at neon.tech
- Create three branches: `main` (prod), `staging`, `dev`
- Get connection strings for each branch (format: `postgresql+asyncpg://...`)
- Enable connection pooling (PgBouncer) on each branch

### 2. Upstash Redis
- Create database `bob-agent` at upstash.com (single-region, EU-West for Israel proximity)
- Get Redis URL (`rediss://...` with TLS)
- Note: Upstash REST API URL also available — not needed for ARQ but useful for admin scripts

### 3. Railway Services
- In the existing `constructor` Railway project, add two new services:
  - `bob-agent` — points to `constructor-agent` repo, root `bob-agent/`, start command from §13.3
  - `bob-worker` — same repo/root, worker start command from §13.3
- Set environment variables from `.env.example` (populate from Neon + Upstash)

### 4. Cloudflare
- Add Railway domain for `bob-agent` behind Cloudflare proxy
- Create firewall rule: `/webhook/agent` only accepts requests where
  `ip.src in {railway_egress_ips}` (get from Railway docs)
- Enable "Under Attack Mode" on the webhook path as fallback

### 5. Doppler
- Create project `bob-agent` with environments: `dev`, `staging`, `prd`
- Populate all secrets from `.env.example`
- Connect Doppler → Railway for `bob-agent` and `bob-worker` services
- Connect Doppler → GitHub Actions secrets

**Done criteria:**
- Can connect to Neon from local machine: `psql $DATABASE_URL -c "SELECT 1"`
- Can ping Upstash: `redis-cli -u $REDIS_URL PING` returns `PONG`
- Railway services exist (not yet deployed — no code yet)
- Doppler CLI `doppler run -- env` shows all secrets populated

---

## M2 — Database Layer

**Delivers:** SQLAlchemy models, Alembic migrations, and repository classes.
The only module that touches the database — all other modules go through repos.

**Files created:**
```
app/db/
├── __init__.py
├── database.py          # async engine, session factory, init_db_engine()
├── models.py            # Site, Defect, ProcessedMessage, AgentMemory ORM models
├── migrations/
│   ├── env.py           # Alembic env with async support
│   └── versions/
│       └── 0001_initial.py   # all tables from spec §4.1
└── repositories/
    ├── __init__.py
    ├── site_repo.py     # get_by_group_id, create, update, disable, get_all
    ├── defect_repo.py   # get_next_defect_id (advisory lock), create, update, get_all
    └── dedup_repo.py    # is_already_processed, mark_as_processed
```

**Key implementation notes:**

`database.py`:
```python
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,   # detect stale connections
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db_engine():
    # Called from FastAPI lifespan — validates connection on startup
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
```

`defect_repo.py` — advisory lock (spec §4.3):
```python
async def get_next_defect_id(session, site_id: int) -> int:
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": site_id})
    result = await session.execute(
        select(func.max(Defect.defect_id)).where(Defect.site_id == site_id)
    )
    return (result.scalar() or 0) + 1
```

`dedup_repo.py`:
- `is_already_processed` uses `SELECT EXISTS` — fast, index-backed
- `mark_as_processed` uses `INSERT ... ON CONFLICT DO NOTHING` — safe for concurrent calls

**Migration 0001:**
- Creates: `sites`, `defects`, `agent_memory`, `processed_messages`
- Creates all indexes from spec §4.1
- `agent_memory` table managed by LangGraph PostgresSaver (auto-creates its own schema
  on first connect — do NOT manually create it, let LangGraph handle it)

**Done criteria:**
- `alembic upgrade head` runs against Neon dev branch with zero errors
- `alembic downgrade base` then `alembic upgrade head` also works (migration is reversible)
- Unit test: `test_get_next_defect_id_concurrent` spawns 10 concurrent tasks for same
  site, asserts all get unique IDs, no unique constraint violations

---

## M3 — Core Services

**Delivers:** Stateless service classes for all external integrations.
No agent logic here — pure I/O wrappers.

**Files created:**
```
app/services/
├── __init__.py
├── bridge_service.py    # BridgeClient singleton (spec §9)
├── soniox_service.py    # transcribe() with 60s timeout + polling (spec §8)
├── pdf_service.py       # generate() via PDFMonkey API
├── fuzzy_service.py     # validate_field() using rapidfuzz (spec §20)
└── scheduler_service.py # thin wrapper around bridge.schedule_message()
app/cache/
└── site_cache.py        # get/set/invalidate via Redis (spec §21)
```

**Key implementation notes:**

`bridge_service.py` — singleton lifecycle:
- `bridge = BridgeClient()` at module level (not yet connected)
- `await bridge.startup()` called from FastAPI lifespan
- All methods decorated with `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))`
- `confirm_processing` retries independently — never silently swallowed

`soniox_service.py`:
- Async poll loop with `asyncio.sleep(1.0)` and hard `MAX_POLL_SECONDS = 60` timeout
- On timeout: logs warning, returns `""` (empty string) — agent handles gracefully
- Construction terms list from spec §8 hardcoded, site-specific terms injected per call

`fuzzy_service.py`:
- `MATCH_THRESHOLD = 85` constant (tunable)
- Returns typed dict: `{"status": "exact"|"fuzzy"|"no_match", "value": str, "score": int}`
- Empty string input always returns `{"status": "exact", "value": ""}` — not validated

`site_cache.py`:
- Uses module-level `redis_client: aioredis.Redis` populated in lifespan
- TTL from `settings.SITE_CACHE_TTL_SECONDS` (default 300s)
- `invalidate_site_cache` called by Admin API on any site update

**Done criteria:**
- `bridge_service.py`: unit test mocks `httpx.AsyncClient`, asserts retry fires on 500
- `soniox_service.py`: unit test mocks HTTP, asserts TimeoutError raised after 60 polls,
  and that empty string is returned when called with fallback handling
- `fuzzy_service.py`: unit test covers exact/fuzzy/no-match for Hebrew strings including
  common misspellings of supplier names (e.g., "דיאבב" → "דיאב")

---

## M4 — Agent Core

**Delivers:** The LangGraph graph, state definition, and memory management.
No tools yet — graph has placeholder tool nodes. Fully runnable with mock tools.

**Files created:**
```
app/agent/
├── __init__.py
├── state.py       # AgentState TypedDict (spec §5.1)
├── prompts.py     # SYSTEM_PROMPT_TEMPLATE + build_system_prompt() (spec §6)
├── nodes.py       # preprocess, transcribe, build_input, agent, post_process,
│                  # send_reply, confirm_processing graph nodes
├── graph.py       # LangGraph graph wiring + run_agent() entry point
└── tools/
    └── __init__.py   # empty — tools registered in M5
```

**Key implementation notes:**

`state.py` — full AgentState from spec §5.1:
```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    group_id: str
    sender: str
    session_id: str
    site: dict
    chat_input: str
    tool_was_called: bool
    transcript: Optional[str]
    image_url: Optional[str]
    video_url: Optional[str]
    is_reaction: bool
    is_close_reaction: bool
    original_message_text: Optional[str]
```

`graph.py` — LangGraph wiring (spec §5.2):
- `PostgresSaver.from_conn_string(settings.DATABASE_URL)` as checkpointer
- Session key: `{"configurable": {"thread_id": f"group_{group_id}"}}`
- Memory cleared after any tool call: `checkpointer.delete(config)`
- Max iterations: `settings.AGENT_MAX_ITERATIONS` (default 3)
- Model: `ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)`

`nodes.py` — graph nodes:
- `preprocess`: site lookup (cache-first via M3), training phase gate, reaction routing
- `transcribe`: calls `soniox_service.transcribe()` — only reached for audio/video
- `build_input`: constructs `chat_input` JSON string from spec §4.2 Step 6
- `agent`: LangGraph `create_react_agent` node with GPT-4.1-mini + system prompt injected
- `post_process`: detects `tool_was_called` from intermediateSteps, clears memory if true
- `send_reply`: calls `bridge.send_message()`
- `confirm_processing`: calls `bridge.confirm_processing()` — always runs (finally-equivalent)

**Done criteria:**
- `run_agent(mock_body)` with mock LLM completes without error
- Graph visualisation renders (LangGraph has `.get_graph().draw_mermaid()`)
- Unit test: Hebrew greeting → no tool called → confirm_processing still fires
- Memory cleared after mock tool call, not cleared after text-only response

---

## M5 — Agent Tools

**Delivers:** All 6 LangChain tools from spec §7. Each is a standalone `@tool` async
function. Each is independently testable with mocked repos and bridge.

**Files created:**
```
app/agent/tools/
├── __init__.py          # exports all 6 tools as TOOLS list for graph.py
├── add_defect.py        # spec §7.1
├── update_defect.py     # spec §7.2
├── get_report.py        # spec §7.3 (send_whatsapp_report)
├── send_pdf.py          # spec §7.4
├── add_event.py         # spec §7.5
└── update_logo.py       # spec §7.6
```

**Key implementation notes:**

Every tool function signature injects `group_id` and `reporter` from agent state,
NOT from the LLM. The LLM only provides domain parameters (description, supplier, etc.).
This is enforced by using `InjectedToolArg` or binding at graph construction time.

`add_defect.py` — fuzzy pre-validation before DB write:
```python
supplier_result = validate_field(supplier, site["context"].get("suppliers", []))
if supplier_result["status"] == "fuzzy":
    return f"התכוונת ל-{supplier_result['value']}?"
if supplier_result["status"] == "no_match":
    opts = ", ".join(site["context"].get("suppliers", []))
    return f"הספק '{supplier}' לא נמצא. הספקים הזמינים: {opts}"
# Only reach here on exact match or empty
```
- Calls `defect_repo.get_next_defect_id()` inside a DB transaction (advisory lock)
- Sends confirmation message via bridge
- Calls `get_report` internally to show updated list after add

`update_defect.py`:
- Only updates fields that are non-empty strings
- Validates status against allowed values: `["פתוח", "בעבודה", "סגור"]`

`get_report.py`:
- Pure filter logic from spec §4.4 / §7.3
- `parse_id_filter` handles `"77-90"` and `"5,7,12"` formats
- Chunks results into 20-defect batches before sending

`send_pdf.py`:
- Calls PDFMonkey API, polls for completion, gets download URL
- Posts to bridge as document (not inline message)

**Done criteria (per tool):**
- `add_defect`: unit test confirms fuzzy supplier → returns Hebrew question, no DB write;
  exact supplier → DB write called, bridge.send_message called
- `update_defect`: only specified fields updated; status `"invalid"` raises ValueError
- `get_report`: filter unit tests covering all 4 filter types + combinations
- All tools: `group_id` and `reporter` cannot be overridden by LLM input

---

## M6 — API Layer

**Delivers:** The production FastAPI application — webhook endpoint, middleware stack,
lifespan management. This is the entry point for all incoming WhatsApp messages.

**Files created:**
```
app/main.py                  # FastAPI app, lifespan, all middleware (spec §10)
app/models/
├── __init__.py
├── webhook.py               # WebhookPayload, MessageBody (spec §3)
└── defect.py                # Defect domain model
app/middleware/
├── __init__.py
├── auth.py                  # verify_webhook_secret (hmac.compare_digest) (spec §26.3)
└── rate_limit.py            # Redis sliding-window per groupId (spec §19)
app/utils/
├── __init__.py
├── formatting.py            # format_defect_row()
├── memory.py                # LangGraph checkpoint key helpers
└── request_id.py            # ULID request_id generation + structlog binding
```

**Key implementation notes:**

`main.py` lifespan order (startup):
1. `await bridge.startup()` — httpx pool
2. `await init_db_engine()` — validates DB connection
3. `app.state.redis = await aioredis.from_url(settings.REDIS_URL)` — Redis pool
4. `app.state.arq_pool = await create_pool(...)` — ARQ
5. Inject `app.state.redis` into `site_cache` and `rate_limit` modules

`main.py` middleware stack (outermost → innermost):
1. Body size limit middleware (1 MB, spec §26.1)
2. Request ID middleware (generates ULID, binds to structlog)
3. Webhook secret validation (spec §26.3) — on `/webhook/agent` only
4. Rate limiting (spec §19) — on `/webhook/agent` only
5. Deduplication check (spec §20 of old numbering, now in handler)

Webhook handler flow:
```
POST /webhook/agent
  → verify_webhook_secret()
  → check_rate_limit(groupId)
  → is_already_processed(messageId) → 200 {"status": "duplicate"} if true
  → mark_as_processed(messageId, groupId)
  → arq_pool.enqueue_job("process_message", body.model_dump())
  → 200 {"status": "accepted"}
```

**Done criteria:**
- `GET /health` → 200
- `POST /webhook/agent` without secret → 401
- `POST /webhook/agent` with wrong secret → 401
- `POST /webhook/agent` with correct secret, valid payload → 200 `{"status": "accepted"}`
- Same `messageId` sent twice → second returns `{"status": "duplicate"}`
- >20 messages/min from same group → 429
- >1MB body → 413
- All tests pass with ARQ pool and bridge mocked

---

## M7 — Task Queue

**Delivers:** ARQ worker that durably processes messages. This is where `run_agent()`
is actually called. Decoupled from the API layer — can be scaled independently.

**Files created:**
```
app/tasks/
├── __init__.py
├── process_message.py   # process_message() task + WorkerSettings (spec §10 ARQ section)
└── worker.py            # entry point: `python -m arq app.tasks.worker.WorkerSettings`
```

**Key implementation notes:**

`process_message.py`:
```python
async def process_message(ctx, body_dict: dict):
    body = MessageBody(**body_dict)
    log = logger.bind(group_id=body.groupId, request_id=body_dict.get("_request_id"))
    try:
        await run_agent(body)
        log.info("message_processed")
    except Exception as e:
        log.error("agent_error", error=str(e), exc_info=True)
        sentry_sdk.capture_exception(e)
        await bridge.send_message(body.groupId, "אירעה שגיאה, אנא נסה שנית")
    finally:
        await bridge.confirm_processing(body.messageId)  # always fires
```

`WorkerSettings`:
```python
class WorkerSettings:
    functions = [process_message]
    redis_settings_from_dsn = True
    max_jobs = 10
    job_timeout = 120
    shutdown_timeout = 60
    keep_result = 60
    retry_jobs = True
    max_tries = 3
    on_startup = worker_startup    # initialise bridge, DB, Redis
    on_shutdown = worker_shutdown  # close connections
```

The worker needs its own startup/shutdown hooks because it's a separate process
from the FastAPI app — it must initialise `bridge`, DB engine, and Redis independently.

**Passing `request_id` through the queue:**
Inject `_request_id` into `body_dict` before enqueue in M6, read it in M7.
This allows end-to-end tracing across the API→worker boundary.

**Done criteria:**
- Worker starts with `python -m arq app.tasks.worker.WorkerSettings`
- Enqueue a job via `arq_pool.enqueue_job("process_message", ...)`, worker picks it up
- Worker calls `confirm_processing` even when `run_agent` raises
- Worker retries up to 3 times on failure; `processed_messages` prevents double-execution
- `docker compose up bob-worker` runs without error

---

## M8 — Admin API

**Delivers:** REST API for site management. Allows registering new sites, updating
supplier/location lists, and managing training phase — without touching the DB directly.

**Files created:**
```
app/admin/
├── __init__.py
├── router.py        # CRUD routes (spec §22)
└── schemas.py       # SiteCreate, SiteUpdate, SiteResponse Pydantic models
```

**Routes:**
```
POST   /admin/sites              → create site (register new WhatsApp group)
GET    /admin/sites              → list all sites
GET    /admin/sites/{group_id}   → get single site
PATCH  /admin/sites/{group_id}  → update (locations, suppliers, training_phase, logo)
DELETE /admin/sites/{group_id}  → soft-delete (set training_phase = "Disabled")
```

**Auth:** `X-Admin-Key: {settings.ADMIN_API_KEY}` header, checked via `Depends(require_admin_key)`.
Uses `hmac.compare_digest` same as webhook secret.

**Side effects:**
- Every `PATCH` and `DELETE` calls `invalidate_site_cache(group_id)` (M3)
- Every write operation emits a structlog audit entry with `caller_ip` and `action`

**Done criteria:**
- `POST /admin/sites` without header → 401
- `POST /admin/sites` with valid payload → 201, site in DB
- `PATCH /admin/sites/{group_id}` → site updated in DB, Redis cache key deleted
- Audit log entry appears for every write
- Integration test: create site → site lookup succeeds in `site_repo.get_by_group_id`

---

## M9 — Observability

**Delivers:** Structured logging, Prometheus metrics, Sentry, request ID propagation.
This is cross-cutting — pieces are wired into M2–M8 as those modules are built,
but this module standardises the configuration and ensures all pieces are connected.

**Files created:**
```
app/utils/request_id.py     # ULID generation, structlog context binding
app/utils/metrics.py        # Prometheus counter/histogram definitions
app/logging_config.py       # structlog configuration (JSON in prod, pretty in dev)
```

**Configuration steps:**
1. `structlog` configured in `logging_config.py`, imported by `main.py` on startup
2. `request_id` middleware generates ULID per request, binds to structlog context
3. Prometheus metrics defined in `metrics.py`, incremented in:
   - `main.py` webhook handler (`bob_requests_total`)
   - each tool function (`bob_tool_calls_total`)
   - `nodes.py` agent node (`bob_agent_duration_seconds`, `bob_agent_iterations`)
   - `soniox_service.py` (`bob_soniox_duration_seconds`, `bob_soniox_timeouts_total`)
   - `tasks/worker.py` (`bob_queue_depth` gauge, updated on job start/end)
4. `GET /metrics` endpoint added to FastAPI app (prometheus_client ASGI)
5. Sentry: `sentry_sdk.init(dsn=settings.SENTRY_DSN)` in `main.py` lifespan startup
   (skip init if `SENTRY_DSN` is empty — dev/test environments)
6. LangSmith: set `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_PROJECT` env vars —
   LangChain picks these up automatically, no code changes needed

**Done criteria:**
- `GET /metrics` returns Prometheus text format with all defined metrics
- Single test message → structlog output contains `group_id`, `request_id`, `tool_called`
- `messageText` does NOT appear in any log output
- Sentry receives a test event when an exception is deliberately raised in staging

---

## M10 — Testing

**Delivers:** Full test suite covering unit, integration, and contract tests.
Tests are written alongside each module but consolidated here as a final coverage pass.

**Files:**
```
tests/
├── conftest.py
├── unit/
│   ├── test_tools.py         # all 6 tools, mocked deps
│   ├── test_fuzzy.py         # Hebrew string matching edge cases
│   ├── test_formatting.py    # format_defect_row()
│   ├── test_filter.py        # filter_defects() all combinations
│   ├── test_rate_limit.py    # sliding window edge cases
│   └── test_dedup.py         # is_already_processed concurrent inserts
├── integration/
│   ├── test_webhook.py       # full POST → ARQ → DB round-trip
│   ├── test_agent_graph.py   # graph end-to-end with mock LLM
│   └── test_admin_api.py     # site CRUD + cache invalidation
└── fixtures/
    ├── payloads.py            # realistic webhook payloads (text, voice, image, reaction)
    └── sites.py               # test site objects
```

**conftest.py fixtures:**
- `test_db`: real asyncpg session against `docker-compose.test.yml` Postgres;
  runs `alembic upgrade head` before session, `alembic downgrade base` after
- `test_redis`: real Redis against `docker-compose.test.yml` Redis; flush before each test
- `mock_llm`: monkeypatches `ChatOpenAI` — returns deterministic tool calls or text
- `mock_bridge`: AsyncMock of all BridgeClient methods
- `test_client`: `httpx.AsyncClient(app=app, base_url="http://test")` with lifespan

**Coverage targets:**
- Unit: 90%+ per module
- Integration: covers every user story from `user_story.md` (10 stories)
- Overall: `--cov-fail-under=80`

**Done criteria:**
- `pytest tests/ --cov=app --cov-fail-under=80` passes
- All 10 user story flows have a corresponding integration test
- `docker compose -f docker-compose.test.yml run --rm test pytest` also passes

---

## M11 — CI/CD

**Delivers:** Automated lint, type check, test, and deploy pipeline.

**Files:**
```
.github/workflows/
├── ci.yml      # on: pull_request — lint → typecheck → test
└── deploy.yml  # on: push to main — build Docker → push → Railway deploy
.pre-commit-config.yaml
```

**CI pipeline (ci.yml):**
```
lint-and-typecheck job:
  ruff check . && ruff format --check . && mypy app/

test job (needs: lint-and-typecheck):
  services: postgres:16, redis:7-alpine
  pytest tests/ --cov=app --cov-report=xml --cov-fail-under=80
  codecov upload
```

**Deploy pipeline (deploy.yml):**
```
on: push to main
  docker build -t ghcr.io/noambrezis/constructor-agent:$SHA .
  docker push
  railway redeploy --service bob-agent
  railway redeploy --service bob-worker
```

**Secrets required in GitHub (via Doppler):**
`DATABASE_URL`, `REDIS_URL`, `OPENAI_API_KEY`, `SONIOX_API_KEY`,
`PDFMONKEY_API_KEY`, `PDFMONKEY_TEMPLATE_ID`, `BRIDGE_URL`, `WEBHOOK_SECRET`,
`ADMIN_API_KEY`, `RAILWAY_TOKEN`, `SENTRY_DSN`, `LANGCHAIN_API_KEY`

**Done criteria:**
- PR with a failing test → CI blocks merge
- PR with passing tests → CI green, merge allowed
- Merge to main → Railway redeploys automatically within 5 minutes
- Pre-commit blocks commit if private key detected

---

## Build Order & Parallelism

Strict sequential (each unlocks the next):
```
M0 (1–2h) → M1 (2–4h, mostly waiting for account setup)
          → M2 (3–4h) → M4 (4–6h) → M5 (4–6h) → M7 (2–3h) → M6 (3–4h)
          → M3 (3–4h) ↗
M8 can be built after M2+M3 in parallel with M4/M5
M9 is wired in incrementally — no single build session
M10 is written alongside each module, final pass after M8
M11 is set up after M10 passes locally
```

Total estimated effort: **32–48 focused hours** (1–2 developer weeks)
