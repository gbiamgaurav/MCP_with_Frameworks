# Visual Code MCP Server

An MCP server that fetches source code from GitHub URLs and returns the raw content. Built with [FastMCP](https://github.com/modelcontextprotocol/python-sdk).

## Tool

**`visualize_code(url: str)`** — Fetches raw source code from a GitHub file URL (blob or raw).

## Project Structure

```
02_custom_mcp_server/
├── visual.py          # MCP server
├── requirements.txt   # Python dependencies
├── Dockerfile         # Container definition for Cloud Run
├── .env               # Local secrets (gitignored)
├── .env.example       # Template — copy to .env and fill in values
└── README.md
```

---

## Local Development

### 1. Configure environment

```bash
cp .env.example .env
# .env is already in .gitignore — safe to store real values there
```

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT_ID` | — | GCP project used for Cloud Run deployments |
| `GOOGLE_CLOUD_REGION` | `us-central1` | Region for Artifact Registry and Cloud Run |
| `AR_REPO` | `visual-mcp` | Artifact Registry repository name |
| `IMAGE` | — | Full Artifact Registry image path |
| `SERVICE_URL` | — | Cloud Run service URL (set after first deploy) |
| `MCP_TRANSPORT` | `stdio` | `stdio` for local, `http` for Cloud Run |
| `PORT` | `8080` | Port the server listens on |

### 2. Install dependencies

```bash
uv pip install -r requirements.txt
```

### 3. Run locally (stdio)

```bash
python visual.py
```

### 4. Test with MCP Inspector

```bash
npx @modelcontextprotocol/inspector python visual.py
```

---

## Deploy to Google Cloud Run

### Prerequisites

- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated
- A Google Cloud project with billing enabled

---

### Step 1 — Authenticate and set project

```bash
export $(grep -v '^#' .env | xargs)
gcloud auth login
gcloud config set project $GOOGLE_CLOUD_PROJECT_ID
```

Fix the Application Default Credentials quota project warning:

```bash
gcloud auth application-default set-quota-project $GOOGLE_CLOUD_PROJECT_ID
```

---

### Step 2 — Enable required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com
```

---

### Step 3 — Create Artifact Registry repository (one-time)

```bash
gcloud artifacts repositories create $AR_REPO \
  --repository-format=docker \
  --location=$GOOGLE_CLOUD_REGION \
  --project=$GOOGLE_CLOUD_PROJECT_ID
```

---

### Step 4 — Grant all required IAM permissions (one-time)

These cover every service account involved across the full build → push → deploy → serve pipeline.

```bash
PROJECT_NUMBER=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT_ID --format="value(projectNumber)")

# ── Cloud Build SA ──────────────────────────────────────────────────────────
# Push images to Artifact Registry
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

# ── Compute Engine default SA (used at build runtime) ───────────────────────
# Push images to Artifact Registry
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# Write runtime logs to Cloud Logging
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# Read/write build artifacts from Cloud Storage
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# ── Cloud Run service agent ──────────────────────────────────────────────────
# Pull container image from Artifact Registry at deploy time
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:service-${PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"
```

---

### Step 5 — Build and deploy

```bash
gcloud builds submit --tag $IMAGE . && \
gcloud run deploy visual-mcp-server \
  --image $IMAGE \
  --platform managed \
  --region $GOOGLE_CLOUD_REGION \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars MCP_TRANSPORT=http
```

---

### Step 6 — Get the service URL

```bash
gcloud run services describe visual-mcp-server \
  --region $GOOGLE_CLOUD_REGION \
  --format "value(status.url)"
```

Save it back to `.env`:

```
SERVICE_URL=https://visual-mcp-server-xxxx-uc.a.run.app
```

The MCP endpoint will be at:

```
https://visual-mcp-server-xxxx-uc.a.run.app/mcp
```

---

## Add to Claude Desktop

Config file location:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

### Option A — Local (stdio)

```json
{
  "mcpServers": {
    "visual_code_server": {
      "command": "python",
      "args": ["/absolute/path/to/02_custom_mcp_server/visual.py"]
    }
  }
}
```

### Option B — Remote via Cloud Run

```json
{
  "mcpServers": {
    "visual_code_server": {
      "url": "https://visual-mcp-server-xxxx-uc.a.run.app/sse"
    }
  }
}
```

Restart Claude Desktop after editing the config. The `visualize_code` tool will appear automatically.

---

## Add to Claude.ai Web

1. Go to **claude.ai** → profile icon → **Settings** → **Integrations**
2. Click **Add integration**
3. Enter:
   - **Name:** `visual_code_server`
   - **URL:** `https://visual-mcp-server-xxxx-uc.a.run.app/mcp`
4. Click **Save**

> Requires Claude Pro or Team plan. Uses streamable HTTP transport (`/mcp` endpoint).

---

## Transport Reference

| Transport | Flag | Endpoint | Use case |
|---|---|---|---|
| `stdio` | _(none)_ | — | Local / Claude Desktop subprocess |
| `sse` | `--sse` | `/sse` | Claude Desktop remote |
| `http` | `--http` | `/mcp` | Cloud Run / Claude.ai web |

---

## Destroy / Teardown

Run these to remove all GCP resources created during deployment. Load env vars first:

```bash
export $(grep -v '^#' .env | xargs)
PROJECT_NUMBER=$(gcloud projects describe $GOOGLE_CLOUD_PROJECT_ID --format="value(projectNumber)")
```

### 1. Delete the Cloud Run service

```bash
gcloud run services delete visual-mcp-server \
  --region $GOOGLE_CLOUD_REGION \
  --project $GOOGLE_CLOUD_PROJECT_ID \
  --quiet
```

### 2. Delete all images in Artifact Registry

```bash
gcloud artifacts docker images delete \
  $IMAGE \
  --delete-tags \
  --quiet
```

### 3. Delete the Artifact Registry repository

```bash
gcloud artifacts repositories delete $AR_REPO \
  --location $GOOGLE_CLOUD_REGION \
  --project $GOOGLE_CLOUD_PROJECT_ID \
  --quiet
```

### 4. Delete Cloud Build artifacts from Cloud Storage

```bash
gcloud storage rm -r gs://${GOOGLE_CLOUD_PROJECT_ID}_cloudbuild/
```

### 5. Revoke IAM permissions (optional)

Only needed if you want a clean IAM state.

```bash
# Cloud Build SA
gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/logging.logWriter"

gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# Compute Engine default SA
gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/logging.logWriter"

gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# Cloud Run service agent
gcloud projects remove-iam-policy-binding $GOOGLE_CLOUD_PROJECT_ID \
  --member="serviceAccount:service-${PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"
```

> To nuke everything including the project itself: `gcloud projects delete $GOOGLE_CLOUD_PROJECT_ID`

---

## Security Note

`--allow-unauthenticated` makes the endpoint public. For production, remove that flag and pass a token:

```json
{
  "mcpServers": {
    "visual_code_server": {
      "url": "https://visual-mcp-server-xxxx-uc.a.run.app/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN"
      }
    }
  }
}
```
