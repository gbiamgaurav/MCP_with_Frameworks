# LangGraph MCP Server — Google Cloud Run Deployment Guide

A complex MCP server powered by five multi-step **LangGraph StateGraph** pipelines.
All tools run without any external API key — they use Python stdlib and the free Wikipedia REST API.

## What's inside

| Tool | Pipeline | Nodes | Description |
|---|---|---|---|
| `research_topic` | Research Pipeline | 5 nodes + loop | Wikipedia-backed multi-depth research reports |
| `review_code` | Code Review Pipeline | 6 nodes | AST static analysis with quality scoring |
| `analyze_document` | Document Pipeline | 6 nodes | NLP analysis: readability, entities, action items |
| `analyze_data` | Data Analysis Pipeline | 5 nodes | Statistical profiling, anomalies, correlations |
| `plan_task` | Task Planner Pipeline | 6 nodes | Goal-to-plan with phase templates and risk register |

## Project Structure

```
03_mcp_with_Langgraph/
├── server.py               # FastMCP server — all 5 tool definitions
├── graphs/
│   ├── __init__.py         # Re-exports compiled graph instances
│   ├── research_graph.py   # Research pipeline (Wikipedia API)
│   ├── code_review_graph.py# Code review pipeline (Python AST)
│   ├── document_graph.py   # Document analysis pipeline
│   ├── data_analysis_graph.py  # Statistical data pipeline
│   └── task_planner_graph.py   # Task planning pipeline
├── requirements.txt
├── Dockerfile
├── deploy.sh               # One-command deploy script
├── .env.example            # Template — copy to .env
└── deployment-steps.md     # This file
```

---

## Local Development

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in GOOGLE_CLOUD_PROJECT_ID at minimum
```

### 2. Install dependencies

```bash
# From repo root (shared venv)
uv pip install -r 03_mcp_with_Langgraph/requirements.txt

# Or inside 03_mcp_with_Langgraph/
uv pip install -r requirements.txt
```

### 3. Run locally (stdio transport)

```bash
cd 03_mcp_with_Langgraph
python server.py
```

### 4. Run locally as HTTP server

```bash
cd 03_mcp_with_Langgraph
MCP_TRANSPORT=http PORT=8080 python server.py --http
```

### 5. Test with MCP Inspector

```bash
npx @modelcontextprotocol/inspector python server.py
```

The Inspector will list all 5 tools and let you invoke them interactively.

---

## Deploy to Google Cloud Run

### Prerequisites

- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed
- GCP project with billing enabled
- `GOOGLE_CLOUD_PROJECT_ID` set in `.env` (or exported)

---

### Step 1 — Authenticate and set project

```bash
export $(grep -v '^#' .env | xargs)
gcloud auth login
gcloud config set project $GOOGLE_CLOUD_PROJECT_ID
```

Fix Application Default Credentials quota project warning (one-time):

```bash
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT_ID
```

---

### Step 2 — Enable required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project=$GOOGLE_CLOUD_PROJECT_ID
```

---

### Step 3 — One-time IAM permissions

These must be granted once per new GCP project. They cover every service account in the
build → push → deploy → serve pipeline.

```bash
PROJECT_NUMBER=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT_ID \
  --format="value(projectNumber)")

# ── Cloud Build service account ───────────────────────────────────────────────
# Push built images to Artifact Registry
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# Write build logs to Cloud Logging
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# Read/write build source from Cloud Storage
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# ── Compute Engine default service account (runs the build steps) ─────────────
# Push images to Artifact Registry (this SA actually executes the Docker push)
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# Write runtime logs
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# Read/write build artifacts
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# ── Cloud Run service agent (pulls the image at deploy time) ─────────────────
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:service-${PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"
```

> **Why the Compute SA?** `gcloud run deploy --source` runs Cloud Build jobs that execute as
> the **Compute Engine default SA**, not the Cloud Build SA. Granting only the Cloud Build SA
> is a common mistake that causes `Permission 'artifactregistry.repositories.uploadArtifacts' denied`.

---

### Step 4 — Deploy (one command)

```bash
cd 03_mcp_with_Langgraph
./deploy.sh
```

The script:
1. Enables required GCP APIs
2. Creates an Artifact Registry Docker repo named `langgraph-mcp` (idempotent)
3. Builds from source (`gcloud run deploy --source`) — no local Docker needed
4. Deploys to Cloud Run with Streamable HTTP transport, `--min-instances=1`
5. Prints the service URL, endpoint, and connection snippets

---

### Step 5 — Verify the endpoint

**Initialize the MCP session** (returns a `mcp-session-id` header):

```bash
SERVICE_URL=$(gcloud run services describe langgraph-mcp-server \
  --region=us-central1 \
  --project=$GOOGLE_CLOUD_PROJECT_ID \
  --format="value(status.url)")

# Run initialize and capture the session ID from response headers
curl -i -s -X POST "${SERVICE_URL}/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-11-25",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    }
  }' | grep -i "mcp-session-id"
```

Expected output: `mcp-session-id: <SESSION_ID>`

> **Why session ID?** MCP Streamable HTTP requires the server-side session ID on all
> subsequent POST requests after initialization.

**List available tools** (replace `<SESSION_ID>` with the value from above):

```bash
curl -s -X POST "${SERVICE_URL}/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

Expected: five tools listed — `research_topic`, `review_code`, `analyze_document`,
`analyze_data`, `plan_task`.

**Test an actual tool call:**

```bash
curl -s -X POST "${SERVICE_URL}/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <SESSION_ID>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "research_topic",
      "arguments": {"topic": "Machine Learning", "depth": "brief"}
    }
  }'
```

Expected: A markdown research report with overview, key facts, and Wikipedia source.

---

## Connect to Claude Desktop

Config file location:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

### Option A — Local (stdio, no Cloud Run needed)

```json
{
  "mcpServers": {
    "langgraph-mcp": {
      "command": "python",
      "args": ["/absolute/path/to/03_mcp_with_Langgraph/server.py"]
    }
  }
}
```

### Option B — Remote via Cloud Run (Streamable HTTP)

```json
{
  "mcpServers": {
    "langgraph-mcp": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "https://<YOUR_SERVICE_URL>/mcp"]
    }
  }
}
```

Restart Claude Desktop after editing. Look for the hammer icon — all 5 tools will appear.

**Why `mcp-remote`?** Claude Desktop uses stdio natively. `mcp-remote` bridges stdio to the
remote Streamable HTTP endpoint.

---

## Connect to Claude Code

Add the remote MCP server from your terminal:

```bash
claude mcp add langgraph-mcp https://<YOUR_SERVICE_URL>/mcp
```

Start a new Claude Code session — the 5 tools (`research_topic`, `review_code`,
`analyze_document`, `analyze_data`, `plan_task`) will be available for invocation.

To remove later:
```bash
claude mcp remove langgraph-mcp
```

---

## Connect to Claude.ai Web

1. Open **claude.ai** → profile → **Settings** → **Integrations**
2. Click **Add custom integration**
3. Enter:
   - **Name:** `langgraph-mcp`
   - **URL:** `https://<YOUR_SERVICE_URL>/mcp`
4. Click **Save** and start a new chat.

Requires a Pro or Team plan. The Cloud Run service must be publicly accessible
(`--allow-unauthenticated` in `deploy.sh` satisfies this).

---

## Transport Reference

| Transport | Flag | Endpoint | When to use |
|---|---|---|---|
| `stdio` | _(none)_ | — | Local dev; Claude Desktop subprocess |
| `http` | `--http` | `/mcp` | **Cloud Run** / Claude.ai web (recommended) |
| `sse` | `--sse` | `/sse` | Legacy Claude Desktop remote config |

> **Why Streamable HTTP instead of SSE?**
> Cloud Run returns HTTP 421 on SSE connections due to HTTP/2 host header validation.
> Streamable HTTP (POST to `/mcp`) works cleanly on Cloud Run.

---

## Instance sizing

`deploy.sh` uses `--min-instances=1` and `--memory=1Gi`.

| Setting | Recommended value | Reason |
|---|---|---|
| `--min-instances` | `1` | Avoids ~5–10 s Python cold starts |
| `--memory` | `1Gi` | LangGraph + httpx import takes ~150 MB; 1Gi gives headroom for concurrent requests |
| `--cpu` | `1` | Adequate for pure-Python pipelines; increase to `2` for heavy concurrent load |
| `--max-instances` | `5` | Caps cost for a learning project |
| `--timeout` | `300` | Deep research with multiple Wikipedia fetches can take 10–20 s |

For cost savings: set `--min-instances=0` (accept cold starts) and `--max-instances=2`.

---

## Teardown

Load environment variables first:

```bash
export $(grep -v '^#' .env | xargs)
PROJECT_NUMBER=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT_ID \
  --format="value(projectNumber)")
```

### Level 1 — Delete Cloud Run service only

```bash
gcloud run services delete langgraph-mcp-server \
  --region=$GOOGLE_CLOUD_REGION \
  --project=$GOOGLE_CLOUD_PROJECT_ID \
  --quiet
```

### Level 2 — Delete Cloud Run + Artifact Registry + GCS

> **Note:** `gcloud run deploy --source` auto-creates an Artifact Registry repo named
> `cloud-run-source-deploy` in addition to the `langgraph-mcp` repo created by `deploy.sh`.
> You must delete **both** repos to fully clean up.

Check which repos exist:

```bash
gcloud artifacts repositories list \
  --location=$GOOGLE_CLOUD_REGION \
  --project=$GOOGLE_CLOUD_PROJECT_ID
```

Delete both repos:

```bash
# Repo created by deploy.sh manually:
gcloud artifacts repositories delete $AR_REPO \
  --location=$GOOGLE_CLOUD_REGION \
  --project=$GOOGLE_CLOUD_PROJECT_ID \
  --quiet

# Repo auto-created by --source builds:
gcloud artifacts repositories delete cloud-run-source-deploy \
  --location=$GOOGLE_CLOUD_REGION \
  --project=$GOOGLE_CLOUD_PROJECT_ID \
  --quiet
```

Delete Cloud Build artifacts from GCS:

```bash
gcloud storage rm -r gs://${GOOGLE_CLOUD_PROJECT_ID}_cloudbuild/
```

> **Do not delete** the `gs://run-sources-<PROJECT_ID>-<REGION>/` bucket — it is
> system-managed by Cloud Run and may be reused by other services.

### Level 3 — Revoke IAM permissions (optional cleanup)

```bash
# Cloud Build SA
for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectAdmin; do
  gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
    --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
    --role="$role"
done

# Compute Engine default SA
for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectAdmin; do
  gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="$role"
done

# Cloud Run service agent
gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:service-${PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"
```

### Level 4 — Delete entire GCP project (nuclear)

```bash
gcloud projects delete $GOOGLE_CLOUD_PROJECT_ID
```

Removes everything. Reversible within 30 days:

```bash
gcloud projects undelete $GOOGLE_CLOUD_PROJECT_ID
```

### Clean up Claude Desktop

Remove the `langgraph-mcp` entry from `claude_desktop_config.json`, then restart Claude Desktop.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Error 403: storage.objects.get denied` | Compute SA missing GCS read | Grant `roles/storage.objectAdmin` to Compute SA (Step 3 above) |
| Build SUCCESS but `uploadArtifacts denied` | Compute SA missing AR write | Grant `roles/artifactregistry.writer` to Compute SA (Step 3 above) |
| `Missing session ID` (`Bad Request`) | Streamable HTTP requires session ID after init | Extract `mcp-session-id` from the `initialize` response headers, then pass `-H "mcp-session-id: <ID>"` on all subsequent requests |
| `sse` transport hangs on Cloud Run | HTTP/2 rejects SSE connections | Use `http` transport (`--http`, endpoint `/mcp`) instead of `--sse` |
| `Not Acceptable: Client must accept…` | Missing `Accept` header | Add `-H "Accept: application/json, text/event-stream"` to curl calls |
| `ModuleNotFoundError: No module named 'langgraph'` | Missing dependency | Run `pip install -r requirements.txt` |
| `research_topic` returns "No data found" | Wikipedia title mismatch | Try a more common spelling; the tool has an OpenSearch fallback but some topics are not on Wikipedia |
| Container OOMKilled | 512 Mi not enough for LangGraph | Increase to `--memory=1Gi` (already the default in `deploy.sh`) |
| Slow first response | Cold start (min-instances=0) | Set `--min-instances=1` and redeploy |
| Tool invocation times out | Deep research with slow Wikipedia | Increase `--timeout=300` in `deploy.sh` (already set) |
| Claude uses built-in tools instead of MCP | Claude prefers built-in overlaps | Name the tool explicitly: "use the `research_topic` tool from langgraph-mcp" |

---

## Security Note

`--allow-unauthenticated` makes the `/mcp` endpoint public. For production use, remove that
flag and add an Authorization header in your client config:

```json
{
  "mcpServers": {
    "langgraph-mcp": {
      "url": "https://<YOUR_SERVICE_URL>/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```

On the server side, add middleware to validate the token before requests reach the MCP handler.
