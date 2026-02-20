# Technical Specification: Bob — WhatsApp AI Site Management Assistant
**Version:** 1.0
**Date:** 2026-02-19
**Stack:** Python · FastAPI · LangGraph · LangChain · PostgreSQL · Google Sheets (optional)

---

## 1. System Overview

Bob is a multi-tenant, stateful AI agent exposed via HTTP webhook. It receives structured WhatsApp messages from a Node.js bridge, processes them through a LangGraph agent loop, executes tool calls against a data layer, and returns Hebrew natural-language replies via the bridge.

```
┌─────────────────────────────────────────────────────────────────────┐
│  WhatsApp Groups (one per site)                                     │
└────────────────────────┬────────────────────────────────────────────┘
                         │ incoming messages, media, reactions
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  WhatsApp Bridge  (Node.js / Baileys / Railway)                     │
│  • Maintains WA connection                                          │
│  • Pre-uploads audio/video to Soniox                                │
│  • Routes by group to correct webhook                               │
│  • Exposes REST API for outbound sends                              │
└────────────────────────┬────────────────────────────────────────────┘
                         │ POST /webhook/agent
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Bob Agent Service  (Python / FastAPI)                              │
│                                                                     │
│  ┌─────────────┐   ┌──────────────────┐   ┌────────────────────┐   │
│  │ Webhook     │──▶│  Pre-processing  │──▶│  LangGraph Agent   │   │
│  │ Handler     │   │  - Site lookup   │   │  - GPT-4.1-mini    │   │
│  │             │   │  - Media routing │   │  - Tool executor   │   │
│  │             │   │  - Soniox STT    │   │  - Memory mgr      │   │
│  └─────────────┘   └──────────────────┘   └────────┬───────────┘   │
│                                                     │               │
│                    ┌────────────────────────────────▼─────────┐    │
│                    │  Tools                                    │    │
│                    │  add_defect · update_defect               │    │
│                    │  get_report · send_pdf · add_event        │    │
│                    │  update_logo                              │    │
│                    └────────────────────────────────┬─────────┘    │
└─────────────────────────────────────────────────────┼──────────────┘
                                                       │
              ┌────────────────────────────────────────┼──────────────┐
              │  Data & External Services              │              │
              │                                        │              │
              │  ┌──────────────┐  ┌────────────────┐ │              │
              │  │  PostgreSQL  │  │  Google Sheets │ │              │
              │  │  (primary)   │  │  (optional     │ │              │
              │  │              │  │   export layer)│ │              │
              │  └──────────────┘  └────────────────┘ │              │
              │  ┌──────────────┐  ┌────────────────┐ │              │
              │  │  Soniox STT  │  │  PDFMonkey     │ │              │
              │  │  (async)     │  │  (PDF render)  │ │              │
              │  └──────────────┘  └────────────────┘ │              │
              └────────────────────────────────────────┘
```

---

## 2. Repository Structure

```
bob-agent/
├── app/
│   ├── main.py                  # FastAPI app, lifespan, webhook endpoint
│   ├── config.py                # Settings (pydantic-settings)
│   ├── models/
│   │   ├── webhook.py           # Pydantic models for incoming webhook payload
│   │   └── defect.py            # Defect, Site domain models
│   ├── services/
│   │   ├── site_service.py      # Site lookup, context loading
│   │   ├── soniox_service.py    # STT polling logic
│   │   ├── bridge_service.py    # WhatsApp Bridge HTTP client (singleton)
│   │   ├── pdf_service.py       # PDFMonkey integration
│   │   ├── fuzzy_service.py     # Supplier/location fuzzy matching (rapidfuzz)
│   │   └── scheduler_service.py # Event/reminder scheduling
│   ├── db/
│   │   ├── database.py          # SQLAlchemy async engine + session factory
│   │   ├── migrations/          # Alembic migrations
│   │   └── repositories/
│   │       ├── site_repo.py
│   │       ├── defect_repo.py   # Includes get_next_defect_id with FOR UPDATE lock
│   │       └── dedup_repo.py    # processed_messages deduplication
│   ├── agent/
│   │   ├── graph.py             # LangGraph graph definition
│   │   ├── state.py             # AgentState TypedDict
│   │   ├── nodes.py             # Graph nodes (pre-process, agent, post-process)
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── add_defect.py
│   │   │   ├── update_defect.py
│   │   │   ├── get_report.py
│   │   │   ├── send_pdf.py
│   │   │   ├── add_event.py
│   │   │   └── update_logo.py
│   │   └── prompts.py           # System prompt template
│   ├── middleware/
│   │   ├── auth.py              # X-Webhook-Secret + X-Admin-Key validation
│   │   └── rate_limit.py        # Per-group sliding-window rate limiter (Redis)
│   ├── admin/
│   │   ├── router.py            # Admin API routes (site CRUD, training phase)
│   │   └── schemas.py           # Admin request/response Pydantic models
│   ├── tasks/
│   │   ├── worker.py            # ARQ worker entry point
│   │   └── process_message.py   # Durable async task (enqueued per webhook call)
│   ├── cache/
│   │   └── site_cache.py        # Redis-backed site context cache (TTL 5 min)
│   └── utils/
│       ├── memory.py            # LangGraph checkpoint key helpers
│       ├── formatting.py        # Defect row formatter
│       └── request_id.py        # X-Request-ID propagation helper
├── tests/
│   ├── unit/
│   │   ├── test_tools.py        # Per-tool unit tests (mocked DB + bridge)
│   │   ├── test_fuzzy.py        # Fuzzy matching edge cases
│   │   ├── test_formatting.py
│   │   └── test_filter.py       # Defect filter logic
│   ├── integration/
│   │   ├── test_webhook.py      # Full webhook → agent → DB round-trip
│   │   ├── test_dedup.py        # Duplicate messageId handling
│   │   └── test_agent_graph.py  # LangGraph graph end-to-end (real LLM off)
│   └── conftest.py              # Shared fixtures (test DB, mock bridge, mock LLM)
├── Dockerfile
├── docker-compose.yml
├── docker-compose.test.yml      # Isolated test environment
├── requirements.txt
├── requirements-dev.txt         # ruff, mypy, pytest, pytest-asyncio, httpx[test]
├── alembic.ini
├── .github/
│   └── workflows/
│       ├── ci.yml               # lint → typecheck → test on every PR
│       └── deploy.yml           # build + push Docker image on main merge
└── .env.example
```

---

## 3. Incoming Webhook Payload

```python
# app/models/webhook.py

from pydantic import BaseModel
from typing import Optional

class OriginalMessage(BaseModel):
    text: Optional[str] = None

class MessageBody(BaseModel):
    messageId: str
    groupId: str                          # WhatsApp JID e.g. "120363XXXXX@g.us"
    sender: str                           # WhatsApp JID of sender
    reactor: Optional[str] = None         # JID of person who reacted (reactions only)
    messageText: Optional[str] = None
    type: str                             # "message" | "reaction"
    emoji: Optional[str] = None           # e.g. "👍"
    mediaUrl: Optional[str] = None
    mediaType: Optional[str] = None       # "image" | "video" | "audio"
    mediaPlaybackUrl: Optional[str] = None
    sonioxFileId: Optional[str] = None    # Pre-uploaded file ID
    originalMessage: Optional[OriginalMessage] = None

class WebhookPayload(BaseModel):
    body: MessageBody
```

---

## 4. Database Schema

### 4.1 PostgreSQL (Primary)

```sql
-- Sites table (mirrors the Google Sheets central registry)
CREATE TABLE sites (
    id              SERIAL PRIMARY KEY,
    group_id        VARCHAR(64) UNIQUE NOT NULL,   -- WhatsApp JID
    name            VARCHAR(255),
    document_url    TEXT,                          -- Google Sheets URL (if used)
    sheet_name      VARCHAR(255),
    training_phase  VARCHAR(64) DEFAULT '',        -- '' | 'Finished'
    context         JSONB DEFAULT '{}',            -- { locations: [], suppliers: [] }
    logo_url        TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Defects table (per site)
CREATE TABLE defects (
    id              SERIAL PRIMARY KEY,
    defect_id       INTEGER NOT NULL,              -- site-scoped auto-increment
    site_id         INTEGER REFERENCES sites(id) ON DELETE CASCADE,
    description     TEXT NOT NULL,
    reporter        VARCHAR(64),                   -- WhatsApp JID
    supplier        VARCHAR(255) DEFAULT '',
    location        VARCHAR(255) DEFAULT '',
    image_url       TEXT DEFAULT '',
    status          VARCHAR(32) DEFAULT 'פתוח',    -- פתוח | בעבודה | סגור
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (site_id, defect_id)
);

-- Chat memory (checkpointing for LangGraph — managed by PostgresSaver)
CREATE TABLE agent_memory (
    session_id      VARCHAR(255) PRIMARY KEY,
    checkpoint      JSONB NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Message deduplication (prevents double-processing on Bridge retry)
CREATE TABLE processed_messages (
    message_id      VARCHAR(128) PRIMARY KEY,
    group_id        VARCHAR(64)  NOT NULL,
    processed_at    TIMESTAMPTZ  DEFAULT NOW()
);
-- Purge rows older than 24 h via a nightly cron / pg_cron job:
-- DELETE FROM processed_messages WHERE processed_at < NOW() - INTERVAL '24 hours';

-- Indexes
CREATE INDEX idx_defects_site_id   ON defects(site_id);
CREATE INDEX idx_defects_status    ON defects(status);
CREATE INDEX idx_defects_supplier  ON defects(supplier);
CREATE INDEX idx_sites_group_id    ON sites(group_id);
CREATE INDEX idx_processed_msgs_at ON processed_messages(processed_at);
```

### 4.3 Defect ID Concurrency Control

`defect_id` is site-scoped and auto-incremented in application code. Two concurrent requests for the same site could both read `max(defect_id) = N` and both try to insert `N+1`, causing a unique-constraint violation.

**Mitigation — advisory lock per site:**
```python
async def get_next_defect_id(session: AsyncSession, site_id: int) -> int:
    # Acquire a session-level advisory lock keyed on site_id.
    # Lock is released automatically when the transaction commits/rolls back.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": site_id},
    )
    result = await session.execute(
        select(func.max(Defect.defect_id)).where(Defect.site_id == site_id)
    )
    current_max = result.scalar() or 0
    return current_max + 1
```
The advisory lock is cheap (no row contention), process-safe, and released automatically when the enclosing transaction ends. All callers of `add_defect` must run this inside a single DB transaction.

---

### 4.4 Defect Filtering

All filter parameters are optional and combinable:
```python
def filter_defects(
    defects: list[Defect],
    status_filter: str = "",
    description_filter: str = "",
    supplier_filter: str = "",
    defect_id_filter: str = "",     # "77-90" or "5,7,12"
) -> list[Defect]:
    ...
```

---

## 5. Agent Architecture (LangGraph)

### 5.1 AgentState

```python
# app/agent/state.py
from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # Conversation
    messages: Annotated[list, add_messages]

    # WhatsApp context (set once per request, never modified)
    group_id: str
    sender: str
    session_id: str

    # Populated during pre-processing
    site: dict                        # Site metadata (name, context, logo_url, ...)
    chat_input: str                   # JSON string sent to AI
    tool_was_called: bool             # Set after agent runs

    # Media
    transcript: Optional[str]
    image_url: Optional[str]
    video_url: Optional[str]

    # Reaction handling
    is_reaction: bool
    is_close_reaction: bool
    original_message_text: Optional[str]
```

### 5.2 Graph Nodes

```
START
  │
  ▼
[preprocess]
  │ - Validate site exists + training phase
  │ - Route: reaction? → build_reaction_input
  │          audio/video? → transcribe
  │          image? → build_media_input
  │          text? → build_text_input
  │
  ▼
[transcribe]  (conditional — only for audio/video)
  │ - Poll Soniox until completed (max 60s)
  │ - Populate state.transcript
  │
  ▼
[build_input]
  │ - Construct chat_input JSON string
  │ - Set session_id
  │
  ▼
[agent]  ← LangGraph ReAct agent
  │ - GPT-4.1-mini
  │ - System prompt with site context injected
  │ - Up to 3 reasoning iterations
  │ - Has access to 6 tools
  │
  ▼
[post_process]
  │ - Detect if tool was called
  │ - If tool called → clear memory
  │
  ▼
[send_reply]
  │ - POST /send-message to WhatsApp Bridge
  │
  ▼
[confirm_processing]
  │ - POST /confirm-processing to WhatsApp Bridge
  │
  ▼
END
```

### 5.3 Memory Strategy

```python
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver.from_conn_string(settings.DATABASE_URL)

# Session key: one per WhatsApp group
config = {"configurable": {"thread_id": f"group_{group_id}"}}

# After any tool call: wipe the session
if state["tool_was_called"]:
    checkpointer.delete(config)
```

**Rationale:** Memory is per-group (not per-user) because construction site workers often continue each other's conversations. Clearing after tool calls prevents context bleed between unrelated defect operations.

---

## 6. System Prompt

```python
# app/agent/prompts.py

SYSTEM_PROMPT_TEMPLATE = """## System Role
You are a conversational assistant for site management.
**CRITICAL: Communicate with the user in Hebrew ONLY.** Current date/time: {current_datetime}

## Available Tools & Parameter Mapping
- **send_pdf_report**: Triggered by 'pdf', 'file', 'report', 'דוח'.
- **send_whatsapp_report**: Triggered by 'list', 'whatsapp', 'defects', 'ליקויים', or when
  the user requests filtered defects by ID, range, supplier, status, or description.
    - `status_filter`: Map to 'פתוח', 'בעבודה', or 'סגור'. Use "" if not mentioned.
    - `description_filter`: Free search text. Use "" if not mentioned.
    - `defect_id_filter`: Range ("77-90") or comma list ("77,78,79"). Use "" if not mentioned.
    - `supplier_filter`: Exact supplier name from the validated list. Use "" if not mentioned.
- **add_defect**: Use to log new site issues.
    - `description`: (Required) Exact description in Hebrew.
    - `image`: (Required if media provided) URL or "" if none.
    - `supplier`: From validated list or "".
    - `location`: From validated list or "".
- **update_defect**: Use to modify existing records.
    - `defect_id`: (Required) Extract from context (#N, ליקוי N, מספר תקלה N).
    - `status`, `description`, `location`, `supplier`, `image`: Use "" if not changing.
- **update_logo**: Use to change the site logo.
    - `image_url`: (Required) URL of uploaded image.
- **add_event**: Use when user asks for reminders, meetings, or scheduling.
    - `description`: Event details.
    - `time`: ISO 8601 datetime (e.g. 2026-02-19T18:00:00).

## Site Context
- **Locations**: {locations}
- **Suppliers**: {suppliers}

## Supplier & Location Validation
Before using a supplier or location in any tool call:
- **Exact match**: use it directly.
- **Close but imperfect match**: ask "התכוונת ל-[closest match]?" and wait for confirmation.
- **No match found**: list all available options in Hebrew. Do NOT call the tool until confirmed.

## Operational Constraints
- Response language: Hebrew ONLY.
- DO NOT call tools more than once per turn.
- Unsupported operations: politely decline in Hebrew.

## Update Logic
- If originalMessage contains a defect structure (#N | ...) → trigger update_defect for that ID.
- Explicit ID in message ("תעדכן ליקוי 5") → trigger update_defect.
- 👍 reaction with originalMessage → trigger update_defect(status='סגור').

## Logo Update Logic
- Trigger update_logo ONLY if user uploads image AND explicitly requests logo update.
- Image alone → ask what it is for.

## Event / Reminder Logic
- Relative durations ("עוד 5 דקות", "בעוד שעה") → calculate from now, never ask AM/PM.
- Ambiguous clock times ("9:00", "שש") → ask בוקר or ערב before executing.
- Convert confirmed times to ISO 8601: 2026-02-19T18:00:00.

## Interaction Flow
1. Greeting: Simple Hebrew greeting.
2. Immediate Execution:
   - Text describing a defect → add_defect immediately.
   - Image + text/transcript → add_defect immediately.
   - Event/reminder request → add_event immediately (unless ambiguous time).
3. Partial Data:
   - Image alone → confirm receipt, ask for description.
   - Ambiguous event time → ask for clarification.
4. Post-Action: Confirm success in Hebrew, offer further help.
"""

def build_system_prompt(site: dict) -> str:
    context = site.get("context", {})
    locations = ", ".join(context.get("locations", [])) or "לא הוגדרו"
    suppliers = ", ".join(context.get("suppliers", [])) or "לא הוגדרו"
    return SYSTEM_PROMPT_TEMPLATE.format(
        current_datetime=datetime.now().isoformat(),
        locations=locations,
        suppliers=suppliers,
    )
```

---

## 7. Tool Specifications

### 7.1 `add_defect`

```python
@tool
async def add_defect(
    description: str,
    group_id: str,          # injected from state, not from AI
    reporter: str,          # injected from state
    supplier: str = "",
    location: str = "",
    image: str = "",
) -> str:
    """Log a new site defect record."""
    site = await site_repo.get_by_group_id(group_id)
    next_id = await defect_repo.get_next_defect_id(site.id)

    defect = await defect_repo.create(
        site_id=site.id,
        defect_id=next_id,
        description=description,
        reporter=reporter,
        supplier=supplier,
        location=location,
        image_url=image,
        status="פתוח",
    )

    formatted = format_defect_row(defect)
    await bridge.send_message(group_id, f"*ליקוי התווסף בהצלחה*\n{formatted}")
    await send_whatsapp_report(group_id=group_id)  # show updated list

    return f"Defect #{next_id} added successfully."
```

### 7.2 `update_defect`

```python
@tool
async def update_defect(
    defect_id: int,
    group_id: str,          # injected
    reporter: str,          # injected
    description: str = "",
    supplier: str = "",
    location: str = "",
    image: str = "",
    status: str = "",
) -> str:
    """Update one or more fields of an existing defect."""
    site = await site_repo.get_by_group_id(group_id)
    updates = {}
    if description: updates["description"] = description
    if supplier:    updates["supplier"]    = supplier
    if location:    updates["location"]    = location
    if image:       updates["image_url"]   = image
    if status:      updates["status"]      = status

    await defect_repo.update(site.id, defect_id, updates)
    await bridge.send_message(group_id, "ליקוי עודכן בהצלחה")
    await send_whatsapp_report(group_id=group_id, defect_id_filter=str(defect_id))
    return f"Defect #{defect_id} updated."
```

### 7.3 `send_whatsapp_report`

```python
@tool
async def send_whatsapp_report(
    group_id: str,
    status_filter: str = "",
    description_filter: str = "",
    supplier_filter: str = "",
    defect_id_filter: str = "",
) -> str:
    """Send a filtered defect list as WhatsApp messages."""
    site = await site_repo.get_by_group_id(group_id)
    defects = await defect_repo.get_all(site.id)
    filtered = filter_defects(defects, status_filter, description_filter,
                               supplier_filter, defect_id_filter)

    if not filtered:
        await bridge.send_message(group_id, "לא נמצאו ליקויים התואמים לחיפוש.")
        return "No defects matched."

    lines = [format_defect_row(d) for d in filtered]
    # Chunk into batches of ~20 defects per message (WhatsApp message size limit)
    batches = [lines[i:i+20] for i in range(0, len(lines), 20)]
    messages = ["\n".join(batch) for batch in batches]
    await bridge.send_messages(group_id, messages)
    return f"Sent {len(filtered)} defects."
```

**Filter logic:**
```python
def filter_defects(defects, status_filter, description_filter,
                   supplier_filter, defect_id_filter):
    result = defects

    if status_filter:
        result = [d for d in result if d.status == status_filter]

    if description_filter:
        result = [d for d in result
                  if description_filter.lower() in d.description.lower()]

    if supplier_filter:
        result = [d for d in result if d.supplier == supplier_filter]

    if defect_id_filter:
        ids = parse_id_filter(defect_id_filter)   # handles "77-90" and "5,7,12"
        result = [d for d in result if d.defect_id in ids]

    return result

def parse_id_filter(filter_str: str) -> set[int]:
    if "-" in filter_str:
        parts = filter_str.split("-")
        return set(range(int(parts[0]), int(parts[1]) + 1))
    return {int(x.strip()) for x in filter_str.split(",")}
```

### 7.4 `send_pdf_report`

```python
@tool
async def send_pdf_report(
    group_id: str,
    status_filter: str = "",
    description_filter: str = "",
    supplier_filter: str = "",
) -> str:
    """Generate and send a PDF defect report."""
    site = await site_repo.get_by_group_id(group_id)
    defects = await defect_repo.get_all(site.id)
    filtered = filter_defects(defects, status_filter, description_filter, supplier_filter)

    pdf_url = await pdf_service.generate(
        template_data={
            "site_name": site.name,
            "logo_url": site.logo_url,
            "defects": [d.dict() for d in filtered],
            "generated_at": datetime.now().isoformat(),
        }
    )

    await bridge.send_document(
        group_id=group_id,
        document_url=pdf_url,
        filename=f"{site.name}_defects.pdf",
        caption="",
    )
    return f"PDF sent with {len(filtered)} defects."
```

### 7.5 `add_event`

```python
@tool
async def add_event(
    group_id: str,
    description: str,
    time: str,              # ISO 8601: "2026-02-19T18:00:00"
) -> str:
    """Schedule a reminder or event to be sent to the WhatsApp group."""
    await bridge.schedule_message(
        group_id=group_id,
        name=description,
        start_date=time,
    )
    return f"Event '{description}' scheduled for {time}."
```

### 7.6 `update_logo`

```python
@tool
async def update_logo(
    group_id: str,
    image_url: str,
) -> str:
    """Update the site logo used in PDF reports."""
    await site_repo.update_logo(group_id, image_url)
    return "Logo updated."
```

---

## 8. Soniox Transcription Service

```python
# app/services/soniox_service.py

import asyncio
import httpx
from app.config import settings

SONIOX_BASE = "https://api.soniox.com/v1"
MAX_POLL_SECONDS = 60
POLL_INTERVAL = 1.0

async def transcribe(file_id: str, site_context: dict) -> str:
    """Submit file for transcription, poll until done, return transcript text."""
    async with httpx.AsyncClient() as client:
        # Submit
        resp = await client.post(
            f"{SONIOX_BASE}/transcriptions",
            headers={"Authorization": f"Bearer {settings.SONIOX_API_KEY}"},
            json={
                "model": "stt-async-preview",
                "file_id": file_id,
                "language_hints": ["he", "en"],
                "context": {
                    "general": [
                        {"key": "domain", "value": "ניהול ליקויי בנייה"},
                        {"key": "topic", "value": "דיווח ליקויים באתר בנייה"},
                    ],
                    "terms": [
                        *CONSTRUCTION_TERMS,
                        *site_context.get("locations", []),
                        *site_context.get("suppliers", []),
                    ],
                },
            },
        )
        resp.raise_for_status()
        job_id = resp.json()["id"]

        # Poll
        elapsed = 0.0
        while elapsed < MAX_POLL_SECONDS:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            status_resp = await client.get(
                f"{SONIOX_BASE}/transcriptions/{job_id}",
                headers={"Authorization": f"Bearer {settings.SONIOX_API_KEY}"},
            )
            if status_resp.json().get("status") == "completed":
                break
        else:
            raise TimeoutError("Soniox transcription timed out")

        # Fetch transcript
        transcript_resp = await client.get(
            f"{SONIOX_BASE}/transcriptions/{job_id}/transcript",
            headers={"Authorization": f"Bearer {settings.SONIOX_API_KEY}"},
        )
        return transcript_resp.json().get("text", "")

CONSTRUCTION_TERMS = [
    "ליקוי", "ליקויים", "רטיבות", "סדק", "סדקים", "קילוף", "התנפחות",
    "טיח", "ריצוף", "אריחים", "איטום", "נזילה", "עובש", "בטון", "שלד",
    "תשתית", "ביסוס", "פיגום", "אינסטלציה", "חשמל", "גבס", "פרקט",
    "חלון", "דלת", "מסגרת", "קבלן", "קבלן משנה", "מפקח", "דירה",
    "קומה", "יחידה", "תיקון", "טיפול", "אחריות", "בדיקה", "פרוטוקול",
]
```

---

## 9. WhatsApp Bridge Client

The client uses a **singleton `httpx.AsyncClient`** created at application startup (via FastAPI lifespan). This reuses TCP connections and connection pool across all requests, avoiding per-call TLS handshake overhead.

```python
# app/services/bridge_service.py

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import settings

class BridgeClient:
    BASE = settings.BRIDGE_URL

    def __init__(self):
        # Initialized to None; populated in lifespan startup
        self._client: httpx.AsyncClient | None = None

    async def startup(self):
        self._client = httpx.AsyncClient(
            base_url=self.BASE,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def shutdown(self):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("BridgeClient not initialized — call startup() first")
        return self._client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def send_message(self, group_id: str, message: str):
        await self.client.post("/send-message",
                               json={"groupId": group_id, "message": message})

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def send_messages(self, group_id: str, messages: list[str]):
        await self.client.post("/send-messages",
                               json={"groupId": group_id, "messages": messages})

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def send_document(self, group_id: str, document_url: str,
                             filename: str, caption: str = ""):
        await self.client.post("/send-document",
                               json={"groupId": group_id, "documentUrl": document_url,
                                     "filename": filename, "caption": caption})

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def confirm_processing(self, message_id: str):
        # confirm_processing must always be called, even if other steps fail.
        # Do not let retries suppress the final exception — caller handles it.
        await self.client.post("/confirm-processing",
                               json={"messageId": message_id})

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def schedule_message(self, group_id: str, name: str, start_date: str):
        await self.client.post("/schedule-message",
                               json={"groupId": group_id, "name": name,
                                     "startDate": start_date})

# Module-level singleton — initialized in FastAPI lifespan
bridge = BridgeClient()
```

---

## 10. FastAPI Webhook Handler

The webhook handler uses a **lifespan** context manager to manage startup/shutdown of shared resources (HTTP client, Redis pool, DB engine). Messages are **enqueued to ARQ** (Redis-backed durable task queue) rather than processed in-process — this survives pod restarts.

```python
# app/main.py

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings
from app.models.webhook import WebhookPayload
from app.services.bridge_service import bridge
from app.db.database import init_db_engine
from app.middleware.auth import verify_webhook_secret
from app.middleware.rate_limit import check_rate_limit
from app.db.repositories.dedup_repo import is_already_processed, mark_as_processed
import structlog

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await bridge.startup()
    await init_db_engine()
    app.state.arq_pool = await create_pool(
        RedisSettings.from_dsn(settings.REDIS_URL)
    )
    logger.info("bob_agent_started")
    yield
    # Shutdown — drain in-flight work, then close connections
    await bridge.shutdown()
    await app.state.arq_pool.close()
    logger.info("bob_agent_stopped")

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/webhook/agent")
async def handle_message(
    request: Request,
    payload: WebhookPayload,
    x_webhook_secret: str = Header(None),
):
    # 1. Authenticate the request
    verify_webhook_secret(x_webhook_secret)

    body = payload.body

    # 2. Rate limit per group (Redis sliding window)
    await check_rate_limit(body.groupId)

    # 3. Deduplicate — return 200 immediately if already processed
    if await is_already_processed(body.messageId):
        logger.info("duplicate_message_skipped", message_id=body.messageId)
        return {"status": "duplicate"}

    # 4. Mark as in-progress (before enqueue to prevent race on rapid retry)
    await mark_as_processed(body.messageId, body.groupId)

    # 5. Enqueue durable task — processing happens in ARQ worker
    await request.app.state.arq_pool.enqueue_job(
        "process_message",
        body.model_dump(),
    )

    return {"status": "accepted"}
```

### ARQ Task Definition

```python
# app/tasks/process_message.py

from app.agent.graph import run_agent
from app.services.bridge_service import bridge
from app.models.webhook import MessageBody
import structlog

logger = structlog.get_logger()

async def process_message(ctx, body_dict: dict):
    body = MessageBody(**body_dict)
    request_id = body.messageId[:8]
    log = logger.bind(group_id=body.groupId, request_id=request_id)
    try:
        await run_agent(body)
        log.info("message_processed")
    except Exception as e:
        log.error("agent_error", error=str(e))
        await bridge.send_message(body.groupId, "אירעה שגיאה, אנא נסה שנית")
    finally:
        # Always confirm processing so the Bridge releases its queue slot
        await bridge.confirm_processing(body.messageId)

# ARQ worker settings
class WorkerSettings:
    functions = [process_message]
    redis_settings_from_dsn = True   # reads REDIS_URL from env
    max_jobs = 10                     # concurrent tasks per worker
    job_timeout = 120                 # seconds before a job is killed
    keep_result = 60                  # seconds to retain job result
```

---

## 11. Configuration

```python
# app/config.py

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str                   # postgresql+asyncpg://...
    DB_POOL_SIZE: int = 10              # SQLAlchemy async pool size
    DB_MAX_OVERFLOW: int = 20           # Additional connections above pool_size

    # Redis / Task Queue
    REDIS_URL: str = "redis://localhost:6379"

    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4.1-mini"

    # Soniox
    SONIOX_API_KEY: str

    # PDFMonkey
    PDFMONKEY_API_KEY: str
    PDFMONKEY_TEMPLATE_ID: str

    # WhatsApp Bridge
    BRIDGE_URL: str = "https://constructor-production.up.railway.app"
    WEBHOOK_SECRET: str                 # Shared secret between Bridge and Agent

    # Admin API
    ADMIN_API_KEY: str                  # Bearer token for /admin/* endpoints

    # Rate Limiting
    RATE_LIMIT_MAX_MESSAGES: int = 20   # Max messages per group per window
    RATE_LIMIT_WINDOW_SECONDS: int = 60 # Sliding window duration

    # Caching
    SITE_CACHE_TTL_SECONDS: int = 300   # Site context Redis cache (5 min)

    # Google Sheets (optional export layer)
    GOOGLE_SHEETS_CREDENTIALS_JSON: str = ""
    CENTRAL_REGISTRY_SHEET_ID: str = "1qNca0mVtydjhGTEv6H21BxXC8-ElzSCBuu2APZSMqhw"

    # Agent settings
    AGENT_MAX_ITERATIONS: int = 3
    STT_TIMEOUT_SECONDS: int = 60

    # Observability
    LANGCHAIN_TRACING_V2: bool = False  # Enable LangSmith tracing
    LANGCHAIN_PROJECT: str = "bob-agent-prod"
    SENTRY_DSN: str = ""                # Sentry error tracking (empty = disabled)
    LOG_LEVEL: str = "INFO"

    # Security
    MAX_REQUEST_BODY_BYTES: int = 1_048_576   # 1 MB webhook payload limit
    MAX_DESCRIPTION_LENGTH: int = 500          # Cap LLM input for defect descriptions

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 12. Key Python Dependencies

```txt
# requirements.txt

# Web framework
fastapi==0.115.0
uvicorn[standard]==0.30.0

# AI / Agent
langchain==0.3.0
langchain-openai==0.2.0
langgraph==0.2.0
langchain-community==0.3.0

# Database
sqlalchemy[asyncio]==2.0.35
asyncpg==0.29.0
alembic==1.13.0

# Task queue (durable background processing)
arq==0.25.0
redis[hiredis]==5.0.0

# HTTP client (singleton, connection-pooled)
httpx==0.27.0

# Fuzzy matching (supplier/location pre-validation)
rapidfuzz==3.9.0

# Rate limiting
slowapi==0.1.9

# Config
pydantic-settings==2.5.0
python-dotenv==1.0.0

# Google Sheets (optional export layer)
gspread==6.1.0
google-auth==2.34.0

# PDF (local alternative to PDFMonkey)
jinja2==3.1.4
weasyprint==62.0       # optional: local PDF generation

# Error tracking
sentry-sdk[fastapi]==2.14.0

# Utilities
python-dateutil==2.9.0
tenacity==9.0.0        # retry logic for external APIs
structlog==24.4.0      # structured logging
python-ulid==2.2.0     # ULID generation for request IDs
```

---

## 13. Deployment

### 13.1 Docker

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 13.2 docker-compose (local dev)

```yaml
version: "3.9"
services:
  bob-agent:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - db
    volumes:
      - ./app:/app/app   # hot reload in dev

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: bob
      POSTGRES_USER: bob
      POSTGRES_PASSWORD: bob
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### 13.3 Production (Railway / Fly.io / Cloud Run)

| Setting | Value |
|---|---|
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Worker command | `python -m arq app.tasks.worker.WorkerSettings` |
| Health check | `GET /health` |
| Min instances (API) | 1 (keep warm for WA latency) |
| Min instances (Worker) | 1 (scale to 3+ under load) |
| Memory | 512 MB minimum per instance |
| Environment | All secrets via Railway/Fly secrets, never in repo |

**Horizontal scaling design:**
- The FastAPI API service is **fully stateless** — any instance can handle any webhook request
- All shared state lives in PostgreSQL (sessions, defects, sites) and Redis (queue, cache, rate limits)
- Multiple API instances + multiple ARQ worker instances can run concurrently without coordination
- LangGraph `PostgresSaver` uses row-level locking internally — safe for concurrent multi-instance access
- The DB advisory lock on `get_next_defect_id` is session-scoped and works correctly across multiple app instances because locks are held in the DB, not in process memory
- Redis is the single coordination point for rate limiting and task queue; use Redis Cluster or Railway Redis HA for production

**Recommended instance counts:**

| Load | API replicas | Worker replicas |
|---|---|---|
| Dev / staging | 1 | 1 |
| < 10 active sites | 1 | 1 |
| 10–50 active sites | 2 | 2 |
| 50+ active sites | 3+ | 3+ (each handles 10 concurrent jobs) |

---

## 14. Error Handling & Resilience

| Failure | Handling |
|---|---|
| Site not in registry | Silently drop (or send "not registered" msg) |
| Soniox timeout (>60s) | Proceed with empty transcript, log warning |
| OpenAI API error | Retry 3× with exponential backoff (tenacity), then send Hebrew error |
| DB connection error | Retry 3×, then send Hebrew error |
| Bridge send failure | Retry 3× — if all fail, log but still confirm-processing |
| Unknown tool call | LangGraph catches, returns error to agent for retry |
| Agent max iterations hit | Return last agent output as-is |

---

## 15. Security Considerations

| Risk | Mitigation |
|---|---|
| Unauthorised webhook calls | `X-Webhook-Secret` header validated on every request; 401 if missing or wrong |
| Admin API abuse | `X-Admin-Key` bearer token required on all `/admin/*` routes; separate from webhook secret |
| Webhook flooding / DoS | Redis sliding-window rate limit: 20 messages/min per `groupId`; 429 on breach |
| Replay attacks | `processed_messages` table deduplicates by `messageId`; 24 h retention window |
| Oversized payloads | `MAX_REQUEST_BODY_BYTES = 1 MB` enforced via FastAPI middleware; 413 on breach |
| IP spoofing | Allowlist Railway egress IP ranges in firewall rules (Cloud Run / Fly allow ingress controls) |
| Prompt injection via user messages | System prompt is never user-controlled; tool parameters are strictly typed Pydantic models |
| Prompt injection via defect descriptions | `description` field truncated to `MAX_DESCRIPTION_LENGTH` (500 chars) before LLM sees it |
| Sensitive data in logs | WhatsApp JIDs are hashed (last 6 chars only) in log output; `messageText` never logged |
| PII retention | `processed_messages` purged after 24 h; `agent_memory` cleared after every tool call; `messageText` never persisted |
| API key exposure | All secrets in env vars via Railway/Fly secrets; `.env` in `.gitignore`; pre-commit hook blocks accidental commits |
| SQL injection | SQLAlchemy parameterised queries only; no raw SQL string interpolation |
| Unvalidated supplier/location | Fuzzy pre-validation layer rejects or flags unrecognised values before they reach the LLM |
| Access control between users | Any group member can act on any defect — by design; document explicitly so clients understand the model |
| Secrets rotation | Use short-lived API keys where possible; `WEBHOOK_SECRET` rotatable without downtime (validate both old + new during rotation window) |

---

## 16. Observability

**Structured Logging (`structlog`):**
Every log line includes:
```
group_id, message_id (truncated), request_id, tool_called, duration_ms, error (if any)
```
- `messageText` and full JIDs are **never** logged
- Log level configurable via `LOG_LEVEL` env var
- JSON output in production; pretty-printed in dev

**Request ID propagation:**
- Each webhook call generates a ULID `request_id` at entry
- `request_id` is propagated into: structlog context, ARQ job metadata, LangSmith run name
- Allows tracing a single message end-to-end across API → worker → LLM → tools → Bridge

**Metrics (Prometheus `/metrics`):**

| Metric | Type | Labels |
|---|---|---|
| `bob_requests_total` | Counter | `status` (accepted/duplicate/rate_limited/error) |
| `bob_tool_calls_total` | Counter | `tool_name` |
| `bob_agent_duration_seconds` | Histogram | — |
| `bob_soniox_duration_seconds` | Histogram | — |
| `bob_soniox_timeouts_total` | Counter | — |
| `bob_agent_iterations` | Histogram | — |
| `bob_queue_depth` | Gauge | — (ARQ queue length) |

**Tracing:**
- LangSmith for LangGraph traces (`LANGCHAIN_TRACING_V2=true`)
- Separate LangSmith projects per environment: `bob-agent-dev`, `bob-agent-prod`

**Error Tracking:**
- Sentry (`sentry-sdk[fastapi]`) captures all unhandled exceptions with `group_id` and `request_id` as tags

**Alerts (configure in Grafana / Railway alerts):**

| Alert | Threshold |
|---|---|
| Error rate | > 5% over 5 min |
| Soniox timeout rate | > 10% over 10 min |
| Agent max-iterations hit | > 20% over 10 min |
| Queue depth | > 50 jobs (worker falling behind) |
| p95 agent duration | > 20 s |

---

## 17. Migration Path from n8n

| Phase | Action |
|---|---|
| 1 | Deploy Python agent alongside n8n (dual-run) |
| 2 | Route `Bob Test Chat V1.3` groups to Python agent, keep n8n for `Bob Prod Chat` |
| 3 | Migrate Google Sheets data to PostgreSQL (keep Sheets as read replica) |
| 4 | Decommission n8n workflows once Python agent is stable in production |
| 5 | Optionally keep Google Sheets as an export/reporting layer via sync job |

---

## 18. Durable Task Queue (ARQ + Redis)

**Problem:** FastAPI `BackgroundTasks` is in-process. If the pod restarts, crashes, or is redeployed mid-task, the message is silently lost. The WhatsApp Bridge has already called `/confirm-processing` (or will timeout waiting), resulting in a dropped message with no user feedback.

**Solution:** ARQ (async job queue backed by Redis). The API pod's only job is to validate, deduplicate, and enqueue. All processing happens in a separate ARQ worker process that can retry on failure.

```
API Pod                         ARQ Worker Pod(s)
─────────────────────────────   ──────────────────────────────────
POST /webhook/agent
  │ validate + dedup
  │ enqueue_job("process_message", body)  ──→  process_message()
  └─ return {"status": "accepted"}              │ run_agent()
                                                │ bridge.send_message()
                                                └─ bridge.confirm_processing()
```

**Failure recovery:**
- If a worker pod crashes mid-job, ARQ automatically re-queues the job (configurable retry count)
- `processed_messages` dedup table prevents duplicate execution on re-queue
- Set `job_timeout=120` — jobs running longer than 120 s are killed and retried

**Scaling workers:**
- Each worker process handles `max_jobs=10` concurrent async tasks
- Add worker replicas horizontally; all share the same Redis queue

---

## 19. Rate Limiting

**Problem:** A single WhatsApp group could flood the system (buggy client, manual spam, or a misconfigured test script), consuming LLM credits and DB connections.

**Implementation:** Redis sliding-window rate limiter, keyed per `groupId`.

```python
# app/middleware/rate_limit.py

import time
import redis.asyncio as aioredis
from app.config import settings

redis_client: aioredis.Redis = None  # initialized in lifespan

async def check_rate_limit(group_id: str):
    key = f"rate:{group_id}"
    now = time.time()
    window_start = now - settings.RATE_LIMIT_WINDOW_SECONDS

    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)       # Remove old entries
    pipe.zadd(key, {str(now): now})                   # Add current request
    pipe.zcard(key)                                    # Count in window
    pipe.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS + 1)
    results = await pipe.execute()

    count = results[2]
    if count > settings.RATE_LIMIT_MAX_MESSAGES:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
```

**Defaults:** 20 messages per group per 60 seconds. Configurable via env vars without redeploy.

---

## 20. Fuzzy Pre-validation (Supplier & Location)

**Problem:** The current design delegates supplier/location validation entirely to the LLM via prompt instructions. This is non-deterministic — the LLM may occasionally accept a misspelling or miss a close match, producing dirty data in the DB.

**Solution:** A deterministic pre-validation layer using `rapidfuzz` runs *before* the tool is called. This is invoked inside each relevant tool function, not in the LLM layer.

```python
# app/services/fuzzy_service.py

from rapidfuzz import process, fuzz

MATCH_THRESHOLD = 85   # 0–100 score; tune based on Hebrew phonetics

def validate_field(value: str, valid_options: list[str]) -> dict:
    """
    Returns:
      {"status": "exact",   "value": matched_value}
      {"status": "fuzzy",   "value": best_match, "score": score}
      {"status": "no_match"}
    """
    if not value:
        return {"status": "exact", "value": ""}   # empty is always valid

    # Exact match (case-insensitive)
    normalized = {v.strip().lower(): v for v in valid_options}
    if value.strip().lower() in normalized:
        return {"status": "exact", "value": normalized[value.strip().lower()]}

    # Fuzzy match
    result = process.extractOne(
        value, valid_options, scorer=fuzz.token_sort_ratio
    )
    if result and result[1] >= MATCH_THRESHOLD:
        return {"status": "fuzzy", "value": result[0], "score": result[1]}

    return {"status": "no_match"}
```

**Integration in tools:**
```python
# Inside add_defect tool, before DB write:
supplier_result = validate_field(supplier, site.context.get("suppliers", []))
if supplier_result["status"] == "fuzzy":
    # Return a message asking for confirmation — do NOT write to DB yet
    return f"התכוונת ל-{supplier_result['value']}?"
if supplier_result["status"] == "no_match":
    options = ", ".join(site.context.get("suppliers", []))
    return f"הספק '{supplier}' לא נמצא. הספקים הזמינים: {options}"
# Proceed with supplier_result["value"] (canonical form)
```

This makes validation deterministic, testable, and independent of LLM behaviour.

---

## 21. Site Context Caching (Redis)

**Problem:** Every incoming message triggers a DB query to look up the site row (by `groupId`). Under load this is unnecessary latency and DB pressure for data that rarely changes.

**Solution:** Cache the site context in Redis with a 5-minute TTL. Invalidate on any admin update to the site.

```python
# app/cache/site_cache.py

import json
import redis.asyncio as aioredis
from app.config import settings

async def get_site_cached(redis: aioredis.Redis, group_id: str) -> dict | None:
    key = f"site:{group_id}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    return None

async def set_site_cached(redis: aioredis.Redis, group_id: str, site: dict):
    key = f"site:{group_id}"
    await redis.setex(key, settings.SITE_CACHE_TTL_SECONDS, json.dumps(site))

async def invalidate_site_cache(redis: aioredis.Redis, group_id: str):
    await redis.delete(f"site:{group_id}")
```

**Cache invalidation triggers:**
- Admin API updates `PATCH /admin/sites/{group_id}` → calls `invalidate_site_cache`
- TTL-based expiry (5 min) acts as a safety net for any missed invalidation

---

## 22. Admin API

No interface currently exists to add or update sites programmatically. Site managers must edit the Google Sheets registry manually, which breaks once the system migrates to PostgreSQL.

```python
# app/admin/router.py

from fastapi import APIRouter, Header, HTTPException, Depends
from app.admin.schemas import SiteCreate, SiteUpdate, SiteResponse
from app.db.repositories.site_repo import site_repo
from app.cache.site_cache import invalidate_site_cache
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])

def require_admin_key(x_admin_key: str = Header(None)):
    if x_admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")

@router.post("/sites", response_model=SiteResponse, dependencies=[Depends(require_admin_key)])
async def create_site(payload: SiteCreate):
    """Register a new WhatsApp group / construction site."""
    return await site_repo.create(payload)

@router.patch("/sites/{group_id}", response_model=SiteResponse, dependencies=[Depends(require_admin_key)])
async def update_site(group_id: str, payload: SiteUpdate):
    """Update site metadata — locations, suppliers, training phase, logo."""
    site = await site_repo.update(group_id, payload)
    await invalidate_site_cache(group_id)
    return site

@router.get("/sites", response_model=list[SiteResponse], dependencies=[Depends(require_admin_key)])
async def list_sites():
    return await site_repo.get_all()

@router.delete("/sites/{group_id}", dependencies=[Depends(require_admin_key)])
async def delete_site(group_id: str):
    """Soft-delete: set training_phase = 'Disabled' rather than hard delete."""
    await site_repo.disable(group_id)
    await invalidate_site_cache(group_id)
    return {"status": "disabled"}
```

**Admin API schemas:**
```python
# app/admin/schemas.py

class SiteCreate(BaseModel):
    group_id: str
    name: str
    training_phase: str = ""
    context: dict = {}          # {"locations": [...], "suppliers": [...]}
    document_url: str = ""
    sheet_name: str = ""

class SiteUpdate(BaseModel):
    name: str | None = None
    training_phase: str | None = None
    context: dict | None = None
    logo_url: str | None = None
```

---

## 23. Graceful Shutdown

FastAPI's lifespan context handles shutdown, but the ARQ worker also needs graceful shutdown to avoid killing in-flight jobs.

**API pod (uvicorn):**
- On SIGTERM, uvicorn finishes in-flight HTTP requests (up to `--timeout-graceful-shutdown` seconds)
- Lifespan `shutdown` block closes `bridge` HTTP client and ARQ pool

**ARQ worker pod:**
- On SIGTERM, ARQ stops accepting new jobs and waits for running jobs to complete (up to `job_timeout`)
- Set `shutdown_timeout = 60` in `WorkerSettings`

```python
class WorkerSettings:
    functions = [process_message]
    max_jobs = 10
    job_timeout = 120
    shutdown_timeout = 60       # wait up to 60s for running jobs before killing
    keep_result = 60
    retry_jobs = True           # re-queue failed jobs
    max_tries = 3               # max retry attempts per job
```

**Docker STOPSIGNAL:**
```dockerfile
STOPSIGNAL SIGTERM
# Ensure Railway/Fly sends SIGTERM, not SIGKILL immediately
```

---

## 24. Testing Strategy

### 24.1 Unit Tests

Each tool and service tested in isolation with mocked dependencies.

```python
# tests/unit/test_tools.py

import pytest
from unittest.mock import AsyncMock, patch
from app.agent.tools.add_defect import add_defect

@pytest.mark.asyncio
async def test_add_defect_success():
    mock_site = {"id": 1, "name": "Test Site", "context": {"suppliers": ["דיאב"], "locations": ["קומה 1"]}}
    mock_defect = {"defect_id": 42, "description": "סדק בתקרה", "supplier": "דיאב", ...}

    with patch("app.agent.tools.add_defect.site_repo.get_by_group_id", return_value=mock_site), \
         patch("app.agent.tools.add_defect.defect_repo.get_next_defect_id", return_value=42), \
         patch("app.agent.tools.add_defect.defect_repo.create", return_value=mock_defect), \
         patch("app.agent.tools.add_defect.bridge.send_message", new_callable=AsyncMock):
        result = await add_defect(description="סדק בתקרה", group_id="123@g.us",
                                  reporter="972501234567@s.whatsapp.net",
                                  supplier="דיאב", location="קומה 1")
    assert "42" in result

@pytest.mark.asyncio
async def test_add_defect_fuzzy_supplier_rejected():
    # When fuzzy pre-validation detects a close-but-not-exact match,
    # tool should return a clarification string, not write to DB.
    ...
```

### 24.2 Integration Tests

Run against a real PostgreSQL + Redis (via `docker-compose.test.yml`), with the LLM mocked.

```python
# tests/integration/test_webhook.py

@pytest.mark.asyncio
async def test_full_defect_add_flow(test_client, test_db, mock_llm):
    """POST webhook → ARQ task → DB row inserted → bridge.send_message called."""
    payload = {...}  # realistic webhook payload
    response = test_client.post("/webhook/agent", json=payload,
                                headers={"X-Webhook-Secret": "test-secret"})
    assert response.status_code == 200

    # Process the queued ARQ job synchronously in tests
    await drain_arq_queue()

    defect = await test_db.execute(select(Defect).where(...))
    assert defect.description == "סדק בתקרה"

@pytest.mark.asyncio
async def test_duplicate_message_ignored(test_client, test_db):
    payload = {...}
    r1 = test_client.post("/webhook/agent", json=payload, headers=...)
    r2 = test_client.post("/webhook/agent", json=payload, headers=...)
    assert r1.json() == {"status": "accepted"}
    assert r2.json() == {"status": "duplicate"}
    # Only one defect should exist
```

### 24.3 Test Infrastructure

```yaml
# docker-compose.test.yml
services:
  test-db:
    image: postgres:16
    environment: {POSTGRES_DB: bob_test, POSTGRES_USER: bob, POSTGRES_PASSWORD: bob}
  test-redis:
    image: redis:7-alpine
```

```python
# tests/conftest.py

@pytest.fixture(scope="session")
def anyio_backend(): return "asyncio"

@pytest.fixture
async def test_db():
    # Create all tables, yield session, drop all tables
    ...

@pytest.fixture
def mock_llm(monkeypatch):
    # Replace the LangGraph agent's LLM with a deterministic stub
    # Returns a pre-configured tool call for each test scenario
    ...

@pytest.fixture
def test_client(mock_llm):
    with TestClient(app) as c:
        yield c
```

### 24.4 Code Quality

```
# requirements-dev.txt
ruff==0.6.0            # linting + formatting (replaces flake8, black, isort)
mypy==1.11.0           # static type checking
pytest==8.3.0
pytest-asyncio==0.24.0
pytest-cov==5.0.0      # coverage reporting
httpx==0.27.0          # TestClient transport
```

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 25. CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on: [pull_request]

jobs:
  lint-and-typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements-dev.txt
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy app/

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: {POSTGRES_DB: bob_test, POSTGRES_USER: bob, POSTGRES_PASSWORD: bob}
        options: --health-cmd pg_isready
      redis:
        image: redis:7-alpine
        options: --health-cmd "redis-cli ping"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/ --cov=app --cov-report=xml --cov-fail-under=80
      - uses: codecov/codecov-action@v4
```

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build and push Docker image
        run: |
          docker build -t $IMAGE_TAG .
          docker push $IMAGE_TAG
      - name: Deploy to Railway
        run: railway up --service bob-agent
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
```

**Pre-commit hooks (`.pre-commit-config.yaml`):**
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: detect-private-key
      - id: check-added-large-files
      - id: no-commit-to-branch
        args: [--branch, main]
```

---

## 26. Input Validation & Security Hardening

### 26.1 Request Body Size Limit

```python
# app/main.py — add to lifespan or as middleware

from starlette.middleware.trustedhost import TrustedHostMiddleware

@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    if request.headers.get("content-length"):
        content_length = int(request.headers["content-length"])
        if content_length > settings.MAX_REQUEST_BODY_BYTES:
            return Response(status_code=413, content="Payload too large")
    return await call_next(request)
```

### 26.2 Description Length Cap

Applied in `add_defect` and `update_defect` before the value is stored or passed to the LLM:
```python
description = description[:settings.MAX_DESCRIPTION_LENGTH]
```

### 26.3 Webhook Secret Validation

```python
# app/middleware/auth.py

import hmac
from fastapi import HTTPException
from app.config import settings

def verify_webhook_secret(x_webhook_secret: str | None):
    if not x_webhook_secret:
        raise HTTPException(status_code=401, detail="Missing webhook secret")
    if not hmac.compare_digest(x_webhook_secret, settings.WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
```

Note: `hmac.compare_digest` prevents timing attacks.

### 26.4 Secrets Management Best Practices

| Practice | Detail |
|---|---|
| No secrets in code | All credentials via env vars; `.env` in `.gitignore` |
| Pre-commit detection | `detect-private-key` hook blocks accidental commits |
| Separate secrets per env | Dev, staging, prod use different API keys and DB credentials |
| Rotation procedure | For `WEBHOOK_SECRET` rotation: deploy new secret to both Bridge and Agent simultaneously; both accept old+new during a 5-minute overlap window, then drop the old |
| Minimal permissions | OpenAI key scoped to the model only; Google Sheets OAuth scoped to specific spreadsheets |
| Audit log | Admin API writes a log entry for every site create/update/delete with caller IP |

---

## 27. Database Backup & Recovery

| Concern | Strategy |
|---|---|
| Automated backups | Daily full backup via Railway/Fly/RDS managed backup (retain 7 days) |
| Point-in-time recovery | Enable WAL archiving (Railway Postgres supports PITR) |
| Recovery time objective | < 1 hour for full restore |
| Recovery point objective | < 24 hours data loss maximum |
| Backup testing | Monthly restore drill to staging environment |
| Export layer | Google Sheets sync job (see §17) acts as a human-readable secondary record |

---

## 28. docker-compose (Updated — includes Redis and ARQ Worker)

```yaml
# docker-compose.yml (local dev — complete)
version: "3.9"
services:
  bob-agent:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./app:/app/app          # hot reload in dev
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  bob-worker:
    build: .
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: python -m arq app.tasks.worker.WorkerSettings

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: bob
      POSTGRES_USER: bob
      POSTGRES_PASSWORD: bob
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "bob"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

---

## 29. Infrastructure Recommendation

### 29.1 Guiding Principles

The bottleneck for user-perceived latency is **AI processing time** (Soniox STT + OpenAI), not server geography. A 50 ms difference in server location is invisible next to a 2–4 s LLM call. Therefore the infrastructure decision is driven by **operational simplicity and cost**, not raw performance.

AWS / Azure / GCP are the right answer at enterprise scale (500+ sites, formal SLA requirements, or Israeli data residency law). At current and near-term scale they add significant ops overhead with no meaningful benefit.

**Recommendation: best-of-breed managed services across vendors, not a single cloud.**

---

### 29.2 Recommended Stack

```
┌─────────────────────────────────────────────────────────┐
│  Cloudflare (free)                                      │
│  DDoS protection · SSL · IP allowlist rules             │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Railway                                                │
│  ├── bob-agent      (FastAPI, Python)                   │
│  ├── bob-worker     (ARQ, Python)                       │
│  └── whatsapp-bridge (Node.js, Baileys) ← already here  │
└────────┬───────────────────────────┬────────────────────┘
         │                           │
┌────────▼──────────┐     ┌──────────▼──────────┐
│  Neon             │     │  Upstash             │
│  PostgreSQL       │     │  Redis               │
│  Serverless       │     │  Serverless          │
│  (primary data +  │     │  (queue · cache ·    │
│   LangGraph mem)  │     │   rate limits)       │
└───────────────────┘     └─────────────────────┘

Observability (all free tiers):
  Grafana Cloud · LangSmith · Sentry

Secrets:
  Doppler  (syncs to Railway + CI automatically)
```

---

### 29.3 Service-by-Service Rationale

#### Compute — Railway
The WhatsApp Bridge already runs on Railway. Adding the Python API and Worker as additional Railway services gives unified billing, shared environment variable management, and one-command deployment. No new vendor to learn.

- `bob-agent` — FastAPI, 512 MB, min 1 instance (keep warm)
- `bob-worker` — ARQ, 512 MB, scale 1 → 3 replicas under load

**Alternative:** Fly.io — marginally more control over VM size and regions, Amsterdam (`ams`) region is ~50 ms to Israel. Worthwhile if Railway's pricing becomes a concern at scale.

---

#### PostgreSQL — Neon (not Railway Postgres)

Railway Postgres works but Neon is strictly better for this use case:

| Feature | Railway Postgres | Neon |
|---|---|---|
| Database branching (dev/staging/prod) | No | Yes |
| Autoscale compute to zero | No | Yes (dev/staging) |
| Built-in PgBouncer connection pooling | No | Yes |
| Point-in-time restore | Manual only | Built-in |
| Price at low usage | ~$5–15/month | Free tier covers dev; $19/month Pro |

The branching feature alone pays for itself — dev and staging get isolated databases from the same project, without running separate DB instances.

Neon's connection string is `postgresql+asyncpg://...` — zero code change from the spec.

---

#### Redis — Upstash (not Railway Redis)

Upstash is serverless Redis: pay per 100k commands, not for an always-on instance.

| | Railway Redis | Upstash |
|---|---|---|
| Pricing | Always-on VM (~$10–20/month) | Per 100k commands (~$0.20) |
| At 50 sites / ~5k messages/day | ~$15/month | < $3/month |
| REST API (no open port needed) | No | Yes |
| Multi-region replication | No | Yes (paid) |

For the ARQ queue + rate limiter + site cache, Upstash is significantly cheaper at this scale.

---

#### CDN & DDoS Protection — Cloudflare (free)

Put Cloudflare in front of the Railway public domain:
- Absorbs DDoS before it reaches Railway
- SSL termination at edge
- IP allowlist rule: only pass `/webhook/agent` traffic from the Railway-internal Bridge IP, block everything else at Cloudflare — zero cost, eliminates a whole class of abuse

---

#### Observability — Grafana Cloud + LangSmith + Sentry

| Tool | Purpose | Cost |
|---|---|---|
| Grafana Cloud | Prometheus metrics + Loki logs + dashboards | Free up to 10k series / 50 GB logs |
| LangSmith | LangGraph agent traces | Free developer tier |
| Sentry | Exception tracking with `group_id` + `request_id` tags | Free (5k errors/month) |

Railway forwards logs automatically to Loki. This gives the full observability stack from §16 at zero cost.

---

#### Secrets — Doppler

Instead of managing `.env` files per environment, Doppler acts as a central secrets store:
- Syncs secrets directly to Railway environment variables
- Syncs to GitHub Actions as CI secrets
- Secrets rotation in one place — propagates everywhere
- Audit log of all secret reads/writes
- Free tier covers the full project

This solves the secrets rotation procedure from §26.4 cleanly.

---

### 29.4 Estimated Monthly Cost

| Service | Phase 1 (< 10 sites) | Phase 2 (10–50 sites) |
|---|---|---|
| Railway (API + Worker + Bridge) | ~$20 | ~$40 |
| Neon PostgreSQL | $0 (free tier) | $19 (Pro) |
| Upstash Redis | $0–1 | $2–5 |
| Cloudflare | $0 | $0 |
| Grafana Cloud | $0 | $0 |
| LangSmith | $0 | $0 |
| Sentry | $0 | $0 |
| Doppler | $0 | $0 |
| **Total** | **~$20–25/month** | **~$60–65/month** |

External API costs (OpenAI, Soniox, PDFMonkey) are separate and usage-based.

---

### 29.5 Migration Path to AWS (When Needed)

Trigger conditions for migrating to AWS `il-central-1` (Tel Aviv):
- > 200 active sites with concurrent peak load
- Enterprise clients requiring formal SLA (99.9%+ uptime guarantee)
- Israeli data residency requirements under regulation
- > 500 concurrent messages/minute sustained

The application code requires zero changes — swap the connection strings:

| Current | AWS equivalent |
|---|---|
| Railway (API + Worker) | ECS Fargate or App Runner |
| Neon PostgreSQL | RDS PostgreSQL Multi-AZ |
| Upstash Redis | ElastiCache (Redis OSS) |
| Cloudflare | Keep Cloudflare (works in front of any origin) |
| Grafana Cloud | Keep or move to Amazon Managed Grafana |
