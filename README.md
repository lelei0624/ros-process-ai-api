# ROS Process AI API — Databricks Genie Edition

## Setup

Add these environment variables in Render:

```env
DATABRICKS_HOST=adb-xxxxxxxxxxxxxxxx.x.azuredatabricks.net
DATABRICKS_TOKEN=dapi_xxxxxxxxxxxxxxxxxxxxx
GENIE_SPACE_ID=your-process-ai-genie-space-id
```

## Build Command

```bash
pip install -r requirements.txt
```

## Start Command

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Test

```text
GET /health
POST /ask
```

Example POST body:

```json
{
  "question": "What are the requirements before Contract Signed?"
}
```
