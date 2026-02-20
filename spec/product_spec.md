# Product Spec: Bob — WhatsApp AI Site Management Assistant
**Source:** n8n workflow `Bob Test Chat V1.3` (ID: `pe1r6O18liU8aQeN`)
**Last Updated:** 2026-02-19
**Instance:** noambrezis.app.n8n.cloud

---

## 1. Product Overview

Bob is a **Hebrew-language AI assistant** that operates inside WhatsApp groups, one group per construction site. Workers on the site interact with Bob via natural language (text, voice notes, images, videos) to log defects, query reports, update existing records, schedule events/reminders, and manage site configuration — all without leaving WhatsApp.

The backend stores all data in **per-site Google Sheets**, one spreadsheet per site. A central registry sheet maps each WhatsApp group to its corresponding spreadsheet and site configuration.

---

## 2. Architecture Overview

```
WhatsApp Group
      │
      ▼
WhatsApp Bridge (Node.js / Railway)
  constructor-production.up.railway.app
      │  POST /webhook/test  (Bob Test)
      │
      ▼
n8n Cloud: Bob Test Chat V1.3
      │
      ├─── Google Sheets (Central Registry: Customers, Sites)
      │         └── Sites sheet: groupId → Document URL, Sheet name, Context (JSON)
      │
      ├─── Soniox STT API  (audio/video transcription)
      │
      ├─── OpenAI GPT-4.1-mini  (AI Agent / reasoning)
      │
      └─── Sub-workflows (tools called by AI Agent):
            ├── Add new defect         (→ Google Sheets append)
            ├── Update Defect          (→ Google Sheets update)
            ├── Send Whatsapp Report   (→ WhatsApp send-messages)
            ├── Send PDF Report        (→ PDFMonkey → WhatsApp send-document)
            ├── Add new event          (→ WhatsApp schedule-message)
            └── Update Logo            (→ Google Sheets update)
```

---

## 3. Data Model

### 3.1 Central Registry — Google Sheets

**Spreadsheet:** `Constructor - Customers, Sites` (ID: `1qNca0mVtydjhGTEv6H21BxXC8-ElzSCBuu2APZSMqhw`)
**Sheet:** `Sites`

| Column | Type | Description |
|---|---|---|
| `Whatsapp Group ID` | string | WhatsApp JID of the group (e.g. `120363XXXXX@g.us`) |
| `Document` | string | URL of this site's Google Sheets defect spreadsheet |
| `Sheet` | string | Sheet name within the document (e.g. `Defects`) |
| `Training Phase` | string | `""` or `"Finished"` — only `Finished` sites are active |
| `Context` | JSON string | `{ "locations": ["קומה 1", "לובי",...], "suppliers": ["דיאב", "עמית",...] }` |

### 3.2 Per-Site Defect Sheet

Each site has its own Google Sheets document. Columns:

| Column | Type | Description |
|---|---|---|
| `defect_id` | integer | Auto-incremented ID (max existing + 1) |
| `description` | string | Hebrew description of the defect |
| `reporter` | string | WhatsApp JID of sender |
| `supplier` | string | Contractor/supplier name (from validated list) |
| `location` | string | Floor, room, area (from validated list) |
| `image` | string | URL of image or video attachment |
| `status` | string | `פתוח` / `בעבודה` / `סגור` |
| `timestamp` | datetime | ISO timestamp when record was created |

### 3.3 Defect Row Display Format

When shown in WhatsApp reports, each defect row is formatted as:
```
#<id> | <supplier> | <description> | <location> | <date> | <status>
```

---

## 4. Main Workflow: Bob Test Chat V1.3

### 4.1 Trigger

- **Type:** HTTP Webhook (POST)
- **URL path:** `/webhook/test`
- **Payload source:** WhatsApp Bridge sends structured JSON on every incoming message/reaction

**Incoming webhook payload structure:**
```json
{
  "body": {
    "body": {
      "messageId":        "string",
      "groupId":          "string (WhatsApp JID)",
      "sender":           "string (WhatsApp JID)",
      "reactor":          "string (JID, only for reactions)",
      "messageText":      "string",
      "type":             "message | reaction",
      "emoji":            "string (e.g. 👍)",
      "mediaUrl":         "string | null",
      "mediaType":        "image | video | audio | null",
      "mediaPlaybackUrl": "string | null (for video HLS)",
      "sonioxFileId":     "string | null (pre-uploaded to Soniox)",
      "originalMessage":  { "text": "string" } | null
    }
  }
}
```

### 4.2 Step-by-Step Flow

#### Step 1 — Site Lookup
- Query `Sites` sheet by `Whatsapp Group ID = groupId`
- **Gate:** Site must exist AND (`Training Phase` is empty OR `Training Phase == "Finished"`)
- If site not found → workflow halts (a disabled "No Site Message" node exists as a future stub)

#### Step 2 — Media Detection
- **If `mediaUrl` is not empty** → has media, go to Step 3
- **If no media** → go to Step 5 (reaction check)

#### Step 3 — Media Type Routing
- **If `mediaType == "video"` OR `mediaType == "audio"`** → go to Step 4 (transcription)
- **Otherwise (image)** → go directly to Step 6 (build chatInput)

#### Step 4 — Audio/Video Transcription via Soniox
1. **Soniox Transcript:** POST to `https://api.soniox.com/v1/transcriptions`
   - Model: `stt-async-preview`
   - File ID: pre-uploaded `sonioxFileId`
   - Language hints: `["he", "en"]`
   - Domain context: construction defects (ניהול ליקויי בנייה)
   - Custom terms: ~30 Hebrew construction terms + all site locations + all site suppliers
2. **Poll status** (`GET /v1/transcriptions/{id}`) every 1 second until `status == "completed"`
3. **Read transcript** (`GET /v1/transcriptions/{id}/transcript`) → `text` field
4. → Proceed to Step 6 (build chatInput, with transcript populated)

#### Step 5 — Reaction Handling
- **If `type == "reaction"` AND `emoji == "👍"`**:
  - Build a special `chatInput` with `message: "close"` and the original replied-to message
  - Session ID: `uuid<groupId-part>-<sender-part>` (unique per user per group)
  - → Go to Step 7 (AI Agent) — AI will call `update_defect_record` to close the defect
- **Otherwise** (no reaction): → Step 6

#### Step 6 — Build Chat Input
Constructs a JSON string passed to the AI:
```json
{
  "message":         "<messageText>",
  "sender":          "<sender JID>",
  "originalMessage": "<replied-to message text or ''>",
  "transcript":      "<Soniox transcript text or ''>",
  "video":           "<mediaPlaybackUrl if video, else ''>",
  "image":           "<mediaUrl if image, else ''>"
}
```
- `sessionId`: `uuid<groupId>` — one memory session per WhatsApp group

#### Step 7 — AI Agent (GPT-4.1-mini)
- Model: `gpt-4.1-mini` (OpenAI)
- Max iterations: 3
- Memory: `memoryBufferWindow` (sliding window, per sessionId)
- Returns intermediate steps (tool call trace)
- **System prompt** (see Section 5)

#### Step 8 — Post-Agent Routing
- **If no tool was called** (`intermediateSteps[0].action.tool` is empty):
  - Pass through to merge → send reply to WhatsApp
- **If a tool was called:**
  - Pass `sessionId` to `Chat Memory Manager`
  - Delete all memory for this session (`mode: delete, deleteMode: all`)
  - Merge → send reply to WhatsApp

#### Step 9 — Send Reply
- POST to `https://constructor-production.up.railway.app/send-message`
  - `groupId`: original group
  - `message`: AI Agent `output` text

#### Step 10 — Confirm Processing
- POST to `https://constructor-production.up.railway.app/confirm-processing`
  - `messageId`: original message ID
  - Tells the WhatsApp Bridge the message was fully handled (releases any held queue slot)

---

## 5. AI Agent System Prompt

The agent is instructed to operate **in Hebrew only** and given these behavioral rules:

### 5.1 Available Tools
| Tool name | Trigger keywords |
|---|---|
| `send_pdf_report` | "pdf", "file", "report", "דוח" |
| `send_whatsapp_report` | "list", "whatsapp", "defects", "ליקויים", or filtered queries by ID/range/supplier/status/description |
| `Add_defect_record` | Any text describing a defect/issue; or image+transcript |
| `update_defect_record` | Message contains defect ID or replying to a defect message |
| `update_logo_image` | Image upload + explicit logo update text |
| `send_whatsapp_event` | Reminder / meeting / event scheduling requests |

### 5.2 Site Context Injection (Dynamic)
The system prompt dynamically injects:
- **Locations:** from `Context.locations[]` in site registry
- **Suppliers:** from `Context.suppliers[]` in site registry

### 5.3 Supplier & Location Validation Rules
- **Exact match** → use directly
- **Close match** (typo/abbreviation) → ask "התכוונת ל-[match]?" and wait for confirmation
- **No match** → list available options in Hebrew, wait for selection
- Never call a tool with an unconfirmed supplier or location

### 5.4 Defect Update Logic
- If `originalMessage` contains a defect row structure (`#1 | supplier | desc...`) → trigger `update_defect_record` for that defect
- If the current message contains a defect ID reference → also triggers update
- 👍 reaction on a message → triggers `update_defect_record` with status `סגור`

### 5.5 Event / Reminder Logic
- Convert relative times ("מחר ב-10", "ביום ראשון") → ISO 8601 using current datetime
- Relative durations ("עוד 5 דקות") → calculate directly, never ask for AM/PM
- Ambiguous times ("9:00", "שש") → ask for AM/PM clarification in Hebrew

### 5.6 Media Logic
- Text alone describing a defect → immediately create defect record
- Image + text/transcript → immediately create defect record (image=URL, description=text)
- Image alone → acknowledge in Hebrew, ask for description, wait for reply, then create
- Video + transcript → treat transcript as description, video URL as image field
- Image + "update logo" text → immediately update logo

### 5.7 Operational Constraints
- Language: **Hebrew only**
- Max 1 tool call per turn
- Max 3 reasoning iterations
- Unsupported operations → politely decline in Hebrew

---

## 6. Sub-Workflows (Tools)

### 6.1 Add New Defect (`9g1VGYdInAZ6mtGh`)

**Trigger:** Called by AI Agent with inputs: `groupId`, `description`, `reporter`, `supplier`, `location`, `image`

**Steps:**
1. Get site metadata from central registry (by `groupId`) → get `Document` URL and `Sheet` name
2. Read all existing defects from the site sheet
3. `Summarize` to find max `defect_id` → new ID = max + 1
4. Append new row to the site sheet:
   - `defect_id` = auto-incremented
   - `description`, `supplier`, `location`, `image` from inputs
   - `reporter` = sender JID
   - `status` = `פתוח` (open, default)
   - `timestamp` = now
5. Format confirmation string: `#<id> | <supplier> | <description> | <location> | <date> | <status>`
6. Send WhatsApp confirmation: `*ליקוי התווסף בהצלחה*\n<formatted defect>`
7. Call `Send Whatsapp Report` (sub-workflow `O84EVWFwCTb1woFu`) to send updated list

**Inputs:**
| Field | Required | Description |
|---|---|---|
| `groupId` | Yes | WhatsApp group JID |
| `description` | Yes | Defect description in Hebrew |
| `reporter` | Yes | Sender JID |
| `supplier` | No | Contractor name (use `""` if absent) |
| `location` | No | Floor/room/area (use `""` if absent) |
| `image` | No | Image/video URL (use `""` if absent) |

---

### 6.2 Update Defect (`apfZglX4GKP00lYu`)

**Trigger:** Called by AI Agent with inputs: `groupId`, `defect_id`, and any of: `description`, `supplier`, `location`, `image`, `status`

**Steps:**
1. Get site metadata from central registry
2. For each provided (non-empty) field → conditionally update that column in the site sheet (matched by `defect_id`)
   - `description` → update if non-empty
   - `supplier` → update if non-empty
   - `image` → update if non-empty
   - `location` → update if non-empty
   - `status` → update if non-empty (valid values: `פתוח`, `בעבודה`, `סגור`)
3. Send WhatsApp confirmation: `"ליקוי עודכן בהצלחה"`
4. Call `Send Whatsapp Report` (sub-workflow `O84EVWFwCTb1woFu`) to send updated record

**Inputs:**
| Field | Required | Description |
|---|---|---|
| `groupId` | Yes | WhatsApp group JID |
| `defect_id` | Yes | The numeric defect ID |
| `description` | No | New description |
| `supplier` | No | New supplier |
| `location` | No | New location |
| `image` | No | New image URL |
| `status` | No | `פתוח` / `בעבודה` / `סגור` |
| `reporter` | Auto | Set from sender JID |

---

### 6.3 Send WhatsApp Report (`TDwr8X7FWgHiLiFs` — TEST variant)

**Trigger:** Called by AI Agent with inputs: `groupId`, `status_filter`, `description_filter`, `supplier_filter`, `defect_id_filter`

**Steps:**
1. Get site metadata from central registry
2. Read all defects from the site sheet
3. Apply all filters in a single JavaScript code node:
   - `status_filter`: exact match on `status` column
   - `description_filter`: substring match on `description` column
   - `supplier_filter`: exact match on `supplier` column
   - `defect_id_filter`: range (`"77-90"`) or comma list (`"77,78,79"`) match on `defect_id`
4. Format each defect as: `#<id> | <supplier> | <description> | <location> | <date> | <status>`
5. Aggregate all formatted lines into a `messages` array (chunked for WhatsApp limits)
6. POST to `https://constructor-production.up.railway.app/send-messages`:
   - `groupId`
   - `messages: ["batch1", "batch2", ...]`

**Filter Inputs:**
| Field | Format | Example |
|---|---|---|
| `status_filter` | `"פתוח"` / `"בעבודה"` / `"סגור"` / `""` | `"פתוח"` |
| `description_filter` | free text / `""` | `"רטיבות"` |
| `supplier_filter` | exact supplier name / `""` | `"דיאב"` |
| `defect_id_filter` | range or CSV / `""` | `"77-90"` or `"5,7,12"` |

---

### 6.4 Send PDF Report (`aszeexnxhgDrrVhO`)

**Trigger:** Called by AI Agent with inputs: `groupId`, `status_filter`, `description_filter`, `supplier_filter`

**Steps:**
1. Get site metadata from central registry → `Document` URL, `Sheet` name
2. Read all defects from the site sheet
3. Apply filters sequentially (each filter is conditional — skip if empty):
   - Filter by `status`
   - Filter by `description` (substring)
   - Filter by `supplier`
4. If no filters provided → pass all records through
5. Sort defects (default sort)
6. Format all defects into a structured JSON payload (JavaScript code node)
7. Call **PDFMonkey API** to render a PDF from the template + data → returns `document_card.download_url`
8. POST to `https://constructor-production.up.railway.app/send-document`:
   ```json
   {
     "groupId": "<group>",
     "documentUrl": "<pdfmonkey_download_url>",
     "filename": "<Sheet name>.pdf",
     "caption": ""
   }
   ```

**Filter Inputs:** same as WhatsApp Report, except no `defect_id_filter`

---

### 6.5 Add New Event (`h8WgcIfejMrkAWTU`)

**Trigger:** Called by AI Agent with inputs: `groupId`, `description`, `time`

**Steps:**
1. POST to `https://constructor-production.up.railway.app/schedule-message`:
   ```json
   {
     "groupId":   "<group>",
     "name":      "<description>",
     "startDate": "<ISO 8601 datetime, e.g. 2026-02-19T18:00:00>"
   }
   ```
   The WhatsApp Bridge handles the scheduling and delivery at the specified time.

**Inputs:**
| Field | Required | Description |
|---|---|---|
| `groupId` | Yes | WhatsApp group JID |
| `description` | Yes | Event title / reminder text |
| `time` | Yes | ISO 8601 datetime (agent converts from Hebrew natural language) |

---

### 6.6 Update Logo (`l2oUUWRMJ4-i6O7abi31_`)

**Trigger:** Called by AI Agent with inputs: `groupId`, `image_url`

**Steps:**
1. Find the row in the central `Sites` sheet where `Whatsapp Group ID == groupId`
2. Update the logo/image column with `image_url`

**Inputs:**
| Field | Required | Description |
|---|---|---|
| `groupId` | Yes | WhatsApp group JID |
| `image_url` | Yes | URL of the new logo image |

---

## 7. WhatsApp Bridge API (External Service)

Base URL: `https://constructor-production.up.railway.app`

| Endpoint | Method | Description | Key Body Fields |
|---|---|---|---|
| `/send-message` | POST | Send a single text message | `groupId`, `message` |
| `/send-messages` | POST | Send multiple messages (batched) | `groupId`, `messages: string[]` |
| `/send-document` | POST | Send a file/PDF | `groupId`, `documentUrl`, `filename`, `caption` |
| `/confirm-processing` | POST | Signal message fully processed | `messageId` |
| `/schedule-message` | POST | Schedule a WhatsApp event/reminder | `groupId`, `name`, `startDate` |

The Bridge is built with Node.js (Baileys library) and deployed on Railway.

---

## 8. External Services & Credentials

| Service | Purpose | Auth |
|---|---|---|
| OpenAI GPT-4.1-mini | AI reasoning / NLP | API Key |
| Soniox | Audio/video → Hebrew transcription | Bearer token |
| Google Sheets | Central registry + per-site defect storage | OAuth2 |
| PDFMonkey | PDF generation from HTML template | API Key |
| n8n Cloud | Workflow orchestration | JWT API Key |
| Railway | WhatsApp Bridge hosting | N/A |

---

## 9. Session & Memory Management

- **Session ID:** `uuid<groupId>` — one chat session per WhatsApp group (all members share context)
- **Memory type:** `memoryBufferWindow` (sliding window, stored in n8n)
- **Memory reset:** After any successful tool call (add/update/report/event/logo), the session memory is **fully cleared** (`delete all`)
- **Rationale:** Tool calls indicate task completion — fresh context for next interaction

---

## 10. User Interaction Flows

### 10.1 Log a Defect (Text)
```
User: "יש סדק בתקרה בקומה 3 ספק דיאב"
Bob:  [calls Add_defect_record immediately]
      "*ליקוי התווסף בהצלחה*
       #47 | דיאב | סדק בתקרה | קומה 3 | 19/2/2026 | פתוח"
```

### 10.2 Log a Defect (Voice Note)
```
User: [sends voice note describing the defect]
Bot:  [Soniox transcribes → Hebrew text]
      [AI reads transcript, calls Add_defect_record]
      "*ליקוי התווסף בהצלחה*
       #48 | ... | ..."
```

### 10.3 Log a Defect (Image + Caption)
```
User: [sends image with caption "רטיבות בדלת כניסה"]
Bot:  [calls Add_defect_record with image URL + caption]
      "*ליקוי התווסף בהצלחה* ..."
```

### 10.4 Image Alone
```
User: [sends image with no text]
Bot:  "קיבלתי את התמונה. אנא תאר את הליקוי."
User: "רצפה שבורה בקומה 1"
Bot:  [calls Add_defect_record]
```

### 10.5 Close a Defect (👍 Reaction)
```
User: [reacts with 👍 to a defect message like "#12 | דיאב | ..."]
Bot:  [detects reaction → calls update_defect_record(defect_id=12, status="סגור")]
      "ליקוי עודכן בהצלחה"
```

### 10.6 Update a Defect (Reply)
```
User: [replies to "#12 | דיאב | סדק בתקרה | קומה 3 | פתוח"]:
      "הספק הוא עמית"
Bot:  [sees originalMessage with #12 → calls update_defect_record(defect_id=12, supplier="עמית")]
      "ליקוי עודכן בהצלחה"
```

### 10.7 Request WhatsApp Report
```
User: "תן לי רשימה של כל הליקויים הפתוחים של דיאב"
Bot:  [calls send_whatsapp_report(status_filter="פתוח", supplier_filter="דיאב")]
      [sends batched list of matching defects]
```

### 10.8 Request PDF Report
```
User: "שלח לי קובץ PDF"
Bot:  [calls send_pdf_report()]
      [PDF generated and sent as document]
```

### 10.9 Set Reminder / Event
```
User: "תזכיר לי על פגישה מחר בשעה 10 בבוקר"
Bot:  [calls send_whatsapp_event(description="פגישה", time="2026-02-20T10:00:00")]
      "הפגישה נוצרה בהצלחה..."
```

### 10.10 Update Logo
```
User: [sends new logo image + "עדכן לוגו"]
Bot:  [calls update_logo_image(image_url="...")]
      "הלוגו עודכן בהצלחה"
```

---

## 11. Multi-Tenancy Model

The system is **multi-tenant by WhatsApp group**:
- Each construction site = 1 WhatsApp group = 1 row in central registry = 1 Google Sheets document
- The `groupId` is the tenant key — all operations are scoped to it
- Site context (locations, suppliers) is per-tenant and injected dynamically into the AI prompt
- Session memory is per-`groupId`

---

## 12. Training / Onboarding Phase

- New sites have `Training Phase = ""` (empty) and are still active
- `Training Phase = "Finished"` also grants full access
- Other values in `Training Phase` block the workflow (site treated as not ready)
- This allows a staged rollout / training period before going live

---

## 13. Recommended Production Stack (Python/LangGraph)

When rebuilding this system in Python, the recommended stack is:

### Framework
- **LangGraph** — for the stateful agentic loop (replaces n8n AI Agent + memory)
- **LangChain** — tool definitions, OpenAI integration, memory

### Components Map

| n8n Component | Python Equivalent |
|---|---|
| n8n Webhook | FastAPI POST endpoint |
| WhatsApp Bridge (Baileys) | Keep as-is (Node.js), or replace with WhatsApp Business API |
| AI Agent (GPT-4.1-mini) | LangGraph `create_react_agent` with `gpt-4.1-mini` |
| memoryBufferWindow | LangChain `ConversationBufferWindowMemory` or LangGraph `MemorySaver` |
| Google Sheets nodes | `gspread` Python library |
| Soniox transcription | `httpx` async calls to Soniox REST API |
| PDFMonkey PDF gen | `httpx` call to PDFMonkey API, or `weasyprint`/`jinja2` locally |
| Sub-workflow tools | Python `@tool` decorated async functions |
| Railway deployment | Keep Railway, or use Cloud Run / Fly.io |
| Per-session memory clear | Delete LangGraph checkpoint after tool execution |

### Suggested Architecture

```
FastAPI app
  POST /webhook/test  ← receives from WhatsApp Bridge
    │
    ├─ Lookup site (gspread)
    ├─ Transcribe if audio/video (Soniox async polling)
    ├─ Build chatInput dict
    ├─ Invoke LangGraph agent
    │     ├─ GPT-4.1-mini LLM
    │     ├─ Tool: add_defect(groupId, description, reporter, supplier, location, image)
    │     ├─ Tool: update_defect(groupId, defect_id, **fields)
    │     ├─ Tool: send_whatsapp_report(groupId, status_filter, description_filter, supplier_filter, defect_id_filter)
    │     ├─ Tool: send_pdf_report(groupId, status_filter, description_filter, supplier_filter)
    │     ├─ Tool: add_event(groupId, description, time)
    │     └─ Tool: update_logo(groupId, image_url)
    ├─ Clear memory if tool was used
    ├─ POST /send-message (WhatsApp Bridge)
    └─ POST /confirm-processing (WhatsApp Bridge)
```

### Database Migration Option
Replace Google Sheets with **PostgreSQL** (via SQLAlchemy) for production-grade reliability, indexing, and concurrent writes. Keep the Google Sheets integration as an optional read/export layer.

---

## 14. Key Design Decisions & Notes

1. **Memory is cleared after every tool call** — prevents the AI from confusing context across separate defect operations in the same group
2. **Session is per-group, not per-user** — all group members share context (simplifies UX for construction sites where team members often continue each other's conversations)
3. **Supplier/Location validation is strict** — the AI must not guess or accept ambiguous values; this ensures clean data in the sheet
4. **👍 reaction as "close defect" shortcut** — clever UX pattern that avoids typing; the reactor's JID is logged as the updater
5. **Soniox is used asynchronously** — polls every 1 second with no hard timeout (relies on n8n wait node); production version should add a max timeout
6. **PDFMonkey template** — the HTML template is stored in the `constructor` project (see `/home/ubuntu/code/constructor/pdf_template/defects-report-template.html`)
7. **WhatsApp Bridge pre-uploads audio** — the `sonioxFileId` in the webhook payload means the Bridge has already uploaded the file to Soniox before hitting n8n, reducing total latency
8. **Filters in PDF report are sequential** (chained IF nodes) vs. WhatsApp report uses a **single JS code node** for all filters — the JS approach is cleaner and should be preferred in production
9. **No authentication between users** — any WhatsApp group member can perform any action; access control is only at the group level
10. **The `Send Whatsapp Report` called after add/update** — ensures the user sees the live updated list as immediate feedback
