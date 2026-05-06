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