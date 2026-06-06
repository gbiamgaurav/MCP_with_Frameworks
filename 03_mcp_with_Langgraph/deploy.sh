#!/usr/bin/env bash
# ============================================================
# Deploy LangGraph MCP Server to Google Cloud Run
# ============================================================
# Prerequisites:
#   1. gcloud CLI installed and authenticated:
#        brew install google-cloud-sdk && gcloud auth login
#   2. Fill in GOOGLE_CLOUD_PROJECT_ID (and optionally other vars) in .env
#      OR export them before running this script.
# ============================================================

set -euo pipefail

# ── Load .env from the same directory ────────────────────────────────────────
ENV_FILE="$(dirname "$0")/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a && source "$ENV_FILE" && set +a
fi

# ── Config (override via env vars) ───────────────────────────────────────────
PROJECT_ID="${GOOGLE_CLOUD_PROJECT_ID:?Set GOOGLE_CLOUD_PROJECT_ID in .env or export it}"
REGION="${GOOGLE_CLOUD_REGION:-us-central1}"
SERVICE_NAME="langgraph-mcp-server"
AR_REPO="${AR_REPO:-langgraph-mcp}"

echo "=================================================="
echo "  LangGraph MCP Server — Cloud Run Deployment"
echo "=================================================="
echo "  Project  : ${PROJECT_ID}"
echo "  Region   : ${REGION}"
echo "  Service  : ${SERVICE_NAME}"
echo "  AR repo  : ${AR_REPO}"
echo ""

# ── Step 1: Enable required GCP APIs ─────────────────────────────────────────
echo "==> [1/4] Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project="${PROJECT_ID}"

# ── Step 2: Create Artifact Registry repo (idempotent) ───────────────────────
echo "==> [2/4] Creating Artifact Registry repository '${AR_REPO}'..."
gcloud artifacts repositories create "${AR_REPO}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="LangGraph MCP Server images" \
  --project="${PROJECT_ID}" \
  2>/dev/null || echo "  (repo already exists, skipping)"

# ── Step 3: Deploy to Cloud Run (source-based build) ─────────────────────────
echo "==> [3/4] Building and deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --platform=managed \
  --port=8080 \
  --set-env-vars="MCP_TRANSPORT=http" \
  --allow-unauthenticated \
  --min-instances=1 \
  --max-instances=5 \
  --memory=1Gi \
  --cpu=1 \
  --timeout=300

# ── Step 4: Print deployed URL ────────────────────────────────────────────────
echo ""
echo "==> [4/4] Fetching service URL..."
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")

echo ""
echo "=================================================="
echo "  Deployment complete!"
echo "=================================================="
echo ""
echo "  Cloud Run URL : ${SERVICE_URL}"
echo "  MCP endpoint  : ${SERVICE_URL}/mcp    (use this for claude.ai web / mcp-remote)"
echo "  SSE endpoint  : ${SERVICE_URL}/sse    (legacy Claude Desktop remote)"
echo ""
echo "  Update .env:"
echo "    SERVICE_URL=${SERVICE_URL}"
echo ""
echo "  Verify (should return SSE with protocolVersion):"
echo "    curl -X POST ${SERVICE_URL}/mcp \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -H 'Accept: application/json, text/event-stream' \\"
echo "      -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"1.0\"}}}'"
echo ""
echo "  Claude Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):"
echo "    {"
echo "      \"mcpServers\": {"
echo "        \"langgraph-mcp\": {"
echo "          \"command\": \"npx\","
echo "          \"args\": [\"-y\", \"mcp-remote@latest\", \"${SERVICE_URL}/mcp\"]"
echo "        }"
echo "      }"
echo "    }"
echo ""
echo "  Claude.ai Web:  Settings → Integrations → Add custom integration"
echo "                  URL: ${SERVICE_URL}/mcp"
