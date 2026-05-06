# ROS Process AI Backend Files

## File: `main.py`

```python
"""
ROS Process AI — FastAPI Backend
Databricks Genie Edition
Sprout Solutions

Run locally:
    uvicorn main:app --reload --port 8000

Deploy to Render:
    Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import os
import time
import httpx
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ros-process-ai")

DATABRICKS_HOST  = os.getenv("DATABRICKS_HOST", "").rstrip("/")
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")
GENIE_SPACE_ID   = os.getenv("GENIE_SPACE_ID", "")

GENIE_BASE = f"https://{DATABRICKS_HOST}/api/2.0/genie/spaces/{GENIE_SPACE_ID}"

POLL_INTERVAL = 3
POLL_TIMEOUT  = 120
DONE_STATES   = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_TIMEOUT"}

app = FastAPI(
    title="ROS Process AI API",
    description="ROS Process AI powered by Databricks Genie | Sprout Solutions",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.hubspot.com",
        "chrome-extension://*",
        "http://localhost:*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ─────────────────────────────────────────────────────────────────
class CrmContext(BaseModel):
    type:   Optional[str] = None
    id:     Optional[str] = None
    name:   Optional[str] = None
    stage:  Optional[str] = None
    amount: Optional[str] = None


class AskRequest(BaseModel):
    question:        str
    conversation_id: Optional[str] = None
    crm_context:     Optional[CrmContext] = None


class AskResponse(BaseModel):
    answer:          str
    conversation_id: str


# ── Helpers ────────────────────────────────────────────────────────────────
def headers():
    return {
        "Authorization": f"Bearer {DATABRICKS_TOKEN}",
        "Content-Type":  "application/json",
    }


def build_prompt(question: str, crm: Optional[CrmContext]) -> str:
    if not crm or not crm.type:
        return question

    parts = []

    if crm.type:
        parts.append(f"Record Type: {crm.type}")

    if crm.id:
        parts.append(f"Record ID: {crm.id}")

    if crm.name:
        parts.append(f"Name: {crm.name}")

    if crm.stage:
        parts.append(f"Stage: {crm.stage}")

    if crm.amount:
        parts.append(f"Amount: {crm.amount}")

    return f"Context:\n{chr(10).join(parts)}\n\nQuestion:\n{question}"


def extract_answer(msg: dict) -> str:

    status = (msg.get("status") or "").upper()

    if status == "FAILED":
        return f"Sorry, ROS Process AI could not process that. {msg.get('error', 'Please try again.')}"

    if status in ("CANCELLED", "QUERY_RESULT_TIMEOUT"):
        return "The request timed out. Please try a simpler question."

    text_content = None
    query_result = None
    query_desc = None

    for att in (msg.get("attachments") or []):

        text = att.get("text", {})

        if isinstance(text, dict):
            c = text.get("content", "")
        else:
            c = str(text) if text else ""

        if c and c.strip():
            text_content = c.strip()

        qr = att.get("query_result", {}) or att.get("result", {})

        if isinstance(qr, dict) and qr:
            rows = qr.get("data_typed_array") or qr.get("rows") or []
            cols = qr.get("columns") or []

            if rows and cols:
                col_names = [c.get("name", f"col{i}") for i, c in enumerate(cols)]
                lines = [" | ".join(col_names)]
                lines.append("-" * len(lines[0]))

                for row in rows[:20]:
                    vals = row.get("values", [])
                    lines.append(" | ".join(str(v.get("str", "")) for v in vals))

                query_result = "\n".join(lines)

        query = att.get("query", {})

        if isinstance(query, dict):
            desc = query.get("description", "")

            if desc and desc.strip():
                query_desc = desc.strip()

    if text_content:
        return text_content

    if query_result:
        return query_result

    if query_desc:
        return query_desc

    content = msg.get("content") or msg.get("message") or ""

    if content and content.strip():
        return content.strip()

    return "Query completed but no summary returned. Try rephrasing your question."


# ── Genie API calls ────────────────────────────────────────────────────────
def start_conversation(content: str) -> tuple[str, str]:

    url = f"{GENIE_BASE}/start-conversation"

    with httpx.Client(timeout=30) as c:
        r = c.post(url, headers=headers(), json={"content": content})

    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Genie error {r.status_code}: {r.text[:300]}"
        )

    d = r.json()

    conv_id = d.get("conversation_id") or d.get("id") or (d.get("conversation") or {}).get("id")

    msg = d.get("message") or {}

    msg_id = msg.get("id") or d.get("message_id")

    if not conv_id or not msg_id:
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected Genie response: {d}"
        )

    return conv_id, msg_id


def send_message(conv_id: str, content: str) -> str:

    url = f"{GENIE_BASE}/conversations/{conv_id}/messages"

    with httpx.Client(timeout=30) as c:
        r = c.post(url, headers=headers(), json={"content": content})

    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Genie error {r.status_code}: {r.text[:300]}"
        )

    d = r.json()

    msg_id = d.get("id") or d.get("message_id")

    if not msg_id:
        raise HTTPException(
            status_code=502,
            detail=f"No message_id in response: {d}"
        )

    return msg_id


def poll(conv_id: str, msg_id: str) -> dict:

    url = f"{GENIE_BASE}/conversations/{conv_id}/messages/{msg_id}"

    elapsed = 0

    with httpx.Client(timeout=30) as c:

        while elapsed < POLL_TIMEOUT:

            r = c.get(url, headers=headers())

            if r.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Poll error {r.status_code}"
                )

            d = r.json()

            status = (d.get("status") or "").upper()

            if status in DONE_STATES:
                return d

            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

    raise HTTPException(
        status_code=504,
        detail="Genie timed out. Please try again."
    )


# ── Endpoints ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "ROS Process AI API",
        "version": "1.0.0"
    }


@app.get("/health")
def health():

    missing = [k for k, v in {
        "DATABRICKS_HOST": DATABRICKS_HOST,
        "DATABRICKS_TOKEN": DATABRICKS_TOKEN,
        "GENIE_SPACE_ID": GENIE_SPACE_ID,
    }.items() if not v]

    if missing:
        return {
            "status": "degraded",
            "missing": missing
        }

    return {
        "status": "healthy",
        "genie_space": GENIE_SPACE_ID
    }


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):

    question = req.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    if not all([
        DATABRICKS_HOST,
        DATABRICKS_TOKEN,
        GENIE_SPACE_ID
    ]):
        raise HTTPException(
            status_code=503,
            detail="ROS Process AI not fully configured."
        )

    prompt = build_prompt(question, req.crm_context)

    if req.conversation_id:

        try:
            msg_id = send_message(req.conversation_id, prompt)
            conv_id = req.conversation_id

        except HTTPException:
            conv_id, msg_id = start_conversation(prompt)

    else:
        conv_id, msg_id = start_conversation(prompt)

    message = poll(conv_id, msg_id)

    answer = extract_answer(message)

    return AskResponse(
        answer=answer,
        conversation_id=conv_id
    )
```

---

## File: `requirements.txt`

```txt
fastapi>=0.110.0
uvicorn>=0.29.0
httpx>=0.27.0
python-dotenv>=1.0.0
pydantic>=2.0.0
```

---

## File: `.env`

```env
DATABRICKS_HOST=adb-xxxxxxxxxxxxxxxx.x.azuredatabricks.net
DATABRICKS_TOKEN=dapi_xxxxxxxxxxxxxxxxxxxxx
GENIE_SPACE_ID=your-process-ai-genie-space-id
```

---

## File: `README.md`

```md
# ROS Process AI API — Databricks Genie Edition

## Architecture

HubSpot Chrome Extension
        ↓ POST /ask
ROS Process AI API (Render.com)
        ↓ start-conversation / send-message
Databricks Genie API
        ↓ polling until COMPLETED
        ↑ business-friendly answer
HubSpot Chrome Extension

---

# Setup

## 1. Get your Genie Space ID

Go to:
Databricks → Genie Spaces → ROS Process AI

Copy from URL:

https://your-workspace.azuredatabricks.net/genie/spaces/YOUR_SPACE_ID

---

## 2. Fill in .env

DATABRICKS_HOST=adb-xxxxxxxxxxxxxxxx.x.azuredatabricks.net
DATABRICKS_TOKEN=dapi_xxxxxxxxxxxxxxxxxxxxx
GENIE_SPACE_ID=your-space-id

---

## 3. Install dependencies

pip install -r requirements.txt

---

## 4. Run locally

uvicorn main:app --reload --port 8000

---

## 5. Test API

GET:
http://localhost:8000/health

POST:
http://localhost:8000/ask

Example body:

{
  "question": "What are the requirements before Contract Signed?"
}

---

## 6. Deploy to Render

### Environment Variables

DATABRICKS_HOST
DATABRICKS_TOKEN
GENIE_SPACE_ID

### Start Command

uvicorn main:app --host 0.0.0.0 --port $PORT
```
