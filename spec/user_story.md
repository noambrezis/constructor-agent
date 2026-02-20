# User Story: Bob — WhatsApp AI Site Management Assistant

---

## Who Is This For?

### Primary Users
- **Site workers & foremen** — people physically on the construction site who discover defects during the workday
- **Site managers / supervisors** — people who need visibility into all open defects, track progress, and manage suppliers
- **Project owners / clients** — occasional users who want a high-level status report without opening any software

### Context
Construction sites in Israel. Workers communicate exclusively in **Hebrew**. They already use WhatsApp groups for site coordination. The entire team is in one WhatsApp group per site. Nobody wants to log into a separate app, learn a new UI, or type into a form.

---

## The Problem Being Solved

Construction defect tracking today is painful:
- Workers photograph defects on their phone, then have to manually fill out a form or spreadsheet — which almost never happens in the field
- Managers rely on voice calls or WhatsApp messages to learn about issues — no structured record exists
- Defect status is tracked in spreadsheets that are always out of date
- Generating a report means manually compiling data, formatting it, and sending it — often skipped entirely
- Contractors deny responsibility because there's no timestamped, attributed record of when a defect was reported

---

## The Solution: Bob

Bob is a WhatsApp-native AI assistant that lives **inside the existing site WhatsApp group**. Workers interact with Bob exactly as they would with a human colleague — in natural Hebrew, using voice notes, photos, or plain text. Bob understands what they mean, takes the right action, and confirms it.

No new app. No login. No form. Just WhatsApp.

---

## Core User Stories

---

### Story 1: Log a Defect by Text

**As a** site worker
**I want to** describe a problem I found in plain Hebrew
**So that** it is permanently recorded with my name, the time, and the relevant contractor

**Scenario — Simple text:**
```
Worker: "יש סדק בגבס בתקרה של דירה 4 קומה 2 ספק עמית"
Bob:    ✅ ליקוי התווסף בהצלחה
        #47 | עמית | סדק בגבס בתקרה | דירה 4 קומה 2 | 19/2/2026 | פתוח
```

**Scenario — Minimal text (no supplier or location):**
```
Worker: "הצנרת דולפת ליד הכניסה"
Bob:    ✅ ליקוי התווסף בהצלחה
        #48 |  | הצנרת דולפת ליד הכניסה |  | 19/2/2026 | פתוח
```

**Acceptance criteria:**
- Any message that describes a problem is immediately recorded — Bob never asks "are you sure?"
- The worker's WhatsApp number is stored as `reporter`
- The defect gets an auto-incremented ID
- Default status is `פתוח` (open)
- Bob confirms with the full formatted defect row

---

### Story 2: Log a Defect by Voice Note

**As a** site worker with dirty hands or who prefers speaking
**I want to** send a voice note describing what I found
**So that** I don't have to stop and type

**Scenario:**
```
Worker: [sends 15-second voice note in Hebrew describing water damage in the lobby]
Bob:    [transcribes voice note automatically]
        ✅ ליקוי התווסף בהצלחה
        #49 |  | רטיבות בלובי ליד דלת הכניסה |  | 19/2/2026 | פתוח
```

**Acceptance criteria:**
- Voice notes are automatically transcribed using Hebrew speech-to-text (Soniox)
- The transcription understands construction terminology (סדק, ריצוף, איטום, etc.)
- The transcription is aware of this site's specific supplier and location names for better accuracy
- No extra steps required from the worker — same flow as text

---

### Story 3: Log a Defect with a Photo

**As a** site worker
**I want to** photograph a defect and describe it
**So that** the record includes visual evidence

**Scenario — Photo with caption:**
```
Worker: [sends photo of cracked tile] + "רצפה שבורה בחדר מדרגות קומה 1"
Bob:    ✅ ליקוי התווסף בהצלחה
        #50 |  | רצפה שבורה | חדר מדרגות קומה 1 | 19/2/2026 | פתוח
        [image URL saved to record]
```

**Scenario — Photo alone (no caption):**
```
Worker: [sends photo with no text]
Bob:    "קיבלתי את התמונה 📸 — במה מדובר?"
Worker: "קילוף טיח בחדר 12"
Bob:    ✅ ליקוי התווסף בהצלחה
        #51 |  | קילוף טיח | חדר 12 | 19/2/2026 | פתוח
```

**Acceptance criteria:**
- Image URL is stored in the defect record
- If image arrives without context, Bob holds state and waits for description
- Video + voice note is treated identically to photo + text (video transcribed, URL stored)

---

### Story 4: Update a Defect by Replying to It

**As a** site manager or worker
**I want to** reply to a previous defect message in WhatsApp and add information
**So that** I can update a record without remembering the defect number

**Scenario — Add supplier by replying:**
```
[existing message in chat]: "#47 | | סדק בגבס בתקרה | דירה 4 קומה 2 | 19/2/2026 | פתוח"
Manager: [replies to that message] "הספק הוא עמית"
Bob:     ✅ ליקוי עודכן בהצלחה
         [shows updated record with supplier=עמית]
```

**Scenario — Change status by replying:**
```
Manager: [replies to defect message] "תסגור את זה, טופל"
Bob:     ✅ ליקוי עודכן בהצלחה
```

**Acceptance criteria:**
- Replying to any structured defect message (`#N | ...`) triggers an update on that defect
- Only the fields mentioned in the reply are updated — others remain unchanged
- Bob can update any combination of: description, supplier, location, image, status

---

### Story 5: Close a Defect with a 👍 Reaction

**As a** site manager
**I want to** quickly close a defect by reacting with 👍
**So that** I can process defects one-handed while walking the site

**Scenario:**
```
[Bob's previous message]: "#47 | עמית | סדק בגבס | דירה 4 קומה 2 | פתוח"
Manager: [reacts with 👍 to that message]
Bob:     ✅ ליקוי עודכן בהצלחה
         [defect #47 status → סגור]
```

**Acceptance criteria:**
- 👍 reaction on any message that contains a defect → closes that defect (status = `סגור`)
- The reactor's WhatsApp number is recorded as the updater
- No typing required

---

### Story 6: Update a Defect by ID (Direct Command)

**As a** site manager
**I want to** type a command referencing a defect number
**So that** I can update any defect even without finding the original message

**Scenario:**
```
Manager: "תעדכן את ליקוי 47 שהסתיים"
Bob:     ✅ ליקוי עודכן בהצלחה

Manager: "ליקוי 47 — ספק עמית, מיקום קומה 3"
Bob:     ✅ ליקוי עודכן בהצלחה
```

**Acceptance criteria:**
- Bob recognises defect IDs mentioned as `#47`, `ליקוי 47`, `מספר תקלה 47`
- Updates only the fields explicitly mentioned

---

### Story 7: Request a WhatsApp Defect Report

**As a** site manager
**I want to** ask Bob for a filtered list of defects in the chat
**So that** I can see the current status without leaving WhatsApp

**Scenario — All open defects:**
```
Manager: "תראה לי את כל הליקויים הפתוחים"
Bob:     [sends list of all open defects, formatted, in chunks]
         #1 | דיאב | סדק בגבס | קומה 1 | 1/2/2026 | פתוח
         #3 | עמית | רטיבות | לובי | 3/2/2026 | פתוח
         ...
```

**Scenario — Filtered by supplier:**
```
Manager: "מה יש פתוח אצל דיאב?"
Bob:     [sends only defects where supplier=דיאב and status=פתוח]
```

**Scenario — Filtered by ID range:**
```
Manager: "תן לי ליקויים 50 עד 70"
Bob:     [sends defects with defect_id between 50 and 70]
```

**Scenario — Filtered by keyword:**
```
Manager: "תן לי כל הליקויים של רטיבות"
Bob:     [sends all defects where description contains "רטיבות"]
```

**Acceptance criteria:**
- Filters can be combined (e.g. supplier + status + description)
- List is sent as formatted WhatsApp text messages
- Long lists are split into multiple messages (batching)
- Hebrew filter keywords are understood naturally

---

### Story 8: Request a PDF Report

**As a** project owner or manager
**I want to** receive a professionally formatted PDF report
**So that** I can share it with stakeholders or print it for meetings

**Scenario:**
```
Manager: "שלח לי דוח PDF של כל הליקויים הפתוחים"
Bob:     [sends PDF document to the WhatsApp group]
         Filename: Defects.pdf
```

**Acceptance criteria:**
- PDF is generated from the live data (not a snapshot)
- Same filters apply as the WhatsApp report (status, supplier, description)
- PDF is professionally formatted with the site logo
- Delivered directly as a WhatsApp document — no link to click

---

### Story 9: Schedule a Reminder or Meeting

**As a** site manager
**I want to** ask Bob to remind the group about something at a specific time
**So that** important events don't get missed in the flow of chat messages

**Scenario — Relative time:**
```
Manager: "תזכיר לי בעוד שעה לבדוק את הביסוס"
Bob:     ✅ תזכורת נוצרה לשעה 15:30
```

**Scenario — Specific time:**
```
Manager: "תוסיף פגישה עם הקבלן ביום ראשון ב-9 בבוקר — לסקור ליקויים"
Bob:     ✅ פגישה נוצרה ליום ראשון ב-09:00
```

**Scenario — Ambiguous time:**
```
Manager: "תזכיר לי בשעה 9"
Bob:     "בוקר או ערב?"
Manager: "בוקר"
Bob:     ✅ תזכורת נוצרה לשעה 09:00
```

**Acceptance criteria:**
- Relative times ("עוד 5 דקות", "בעוד שעה") are resolved immediately without asking
- Ambiguous clock times prompt a clarification question before creating the event
- Events/reminders are delivered to the WhatsApp group at the scheduled time

---

### Story 10: Update the Site Logo

**As a** site manager or administrator
**I want to** update the logo used in PDF reports
**So that** reports show the correct branding

**Scenario:**
```
Manager: [sends image of new logo] + "עדכן לוגו"
Bob:     ✅ הלוגו עודכן בהצלחה
```

**Acceptance criteria:**
- Bob only updates the logo when the user **explicitly asks** ("עדכן לוגו" or similar)
- Sending an image alone without text does **not** trigger a logo update — Bob asks what the image is for
- The new logo URL is stored in the central site registry

---

### Story 11: Supplier & Location Validation

**As a** site manager
**I want** Bob to validate supplier and location names before saving them
**So that** the data is clean and consistent for filtering and reporting

**Scenario — Typo correction:**
```
Worker: "ספק דיאבב קומה 3"
Bob:    "התכוונת ל-דיאב?"
Worker: "כן"
Bob:    ✅ ליקוי התווסף בהצלחה
        #52 | דיאב | ... | קומה 3 | ...
```

**Scenario — Unknown supplier:**
```
Worker: "ספק כהן בניה"
Bob:    "הספק 'כהן בניה' לא נמצא ברשימה. הספקים הזמינים: דיאב, עמית, שלום חשמל. לאיזה להשתמש?"
```

**Acceptance criteria:**
- Exact match → used directly, no interruption
- Close match (fuzzy) → Bob asks for confirmation before proceeding
- No match → Bob lists all valid options and waits for selection
- Bob **never saves an unconfirmed supplier or location**

---

## What Bob Does NOT Do

- Bob does **not** send messages proactively (except scheduled events)
- Bob does **not** respond to general chat messages unrelated to site management
- Bob does **not** support multi-step conversations beyond simple clarifications
- Bob does **not** manage user accounts or permissions — access is controlled at the WhatsApp group level
- Bob does **not** delete defect records (only status changes to `סגור`)
- Bob **only** speaks Hebrew — English input may be partially understood but responses are always Hebrew

---

## Success Metrics

| Metric | Target |
|---|---|
| Time to log a defect | < 10 seconds (voice note end-to-end) |
| Defect capture rate | > 90% of site defects logged (vs. 0% with manual forms) |
| Report generation time | < 30 seconds for PDF |
| Worker adoption | Zero training required — works like texting |
| Data accuracy | 100% of defects have timestamp + reporter |
