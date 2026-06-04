#!/usr/bin/env bash
# ============================================================
# Deploy MCP Server to Google Cloud Run
# ============================================================
# Prerequisites:
#   1. gcloud CLI installed and authenticated
#      brew install google-cloud-sdk && gcloud auth login
#   2. Set GCP_PROJECT_ID in your .env or export it:
#      export GCP_PROJECT_ID=my-project-123
# ============================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Auto-load .env from parent directory
# ---------------------------------------------------------------------------
ENV_FILE="$(dirname "$0")/../.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a && source "$ENV_FILE" && set +a
fi

# ---------------------------------------------------------------------------
# Config — override via environment variables
# ---------------------------------------------------------------------------
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID in .env or export it}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="learning-mcp-server"
REPO_NAME="mcp-servers"
IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"

echo "==> Project : ${PROJECT_ID}"
echo "==> Region  : ${REGION}"
echo "==> Service : ${SERVICE_NAME}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Enable required GCP APIs
# ---------------------------------------------------------------------------
echo "==> Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# Step 2: Create Artifact Registry repo (idempotent)
# ---------------------------------------------------------------------------
echo "==> Creating Artifact Registry repository '${REPO_NAME}'..."
gcloud artifacts repositories create "${REPO_NAME}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="MCP Servers for learning" \
  --project="${PROJECT_ID}" \
  2>/dev/null || echo "  (repository already exists, skipping)"

# ---------------------------------------------------------------------------
# Step 3: Deploy to Cloud Run (builds from source automatically)
# ---------------------------------------------------------------------------
echo "==> Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --platform=managed \
  --port=8080 \
  --set-env-vars="MCP_TRANSPORT=http" \
  --allow-unauthenticated \
  --min-instances=1 \
  --max-instances=3 \
  --memory=512Mi \
  --cpu=1

# ---------------------------------------------------------------------------
# Step 4: Print the deployed URL
# ---------------------------------------------------------------------------
echo ""
echo "==> Deployment complete!"
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")

echo ""
echo "  Cloud Run URL  : ${SERVICE_URL}"
echo "  MCP endpoint   : ${SERVICE_URL}/mcp"
echo "  SSE endpoint   : ${SERVICE_URL}/sse  (legacy, prefer /mcp)"
echo ""
echo "  To use this in your ADK agent, set in .env:"
echo "    MCP_SERVER_URL=${SERVICE_URL}/mcp"
echo ""
echo "  Or update adk_agents/remote_agent/agent.py:"
echo "    SseServerParams(url=\"${SERVICE_URL}/sse\")"
echo ""
echo "  For Claude Desktop (claude_desktop_config.json):"
echo "    mcp-remote url: ${SERVICE_URL}/mcp"
