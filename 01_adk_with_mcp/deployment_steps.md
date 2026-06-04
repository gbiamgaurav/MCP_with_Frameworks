# MCP Server — Cloud Run Deployment Steps

## Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- GCP project created and set as `GCP_PROJECT_ID` in `.env`
- Python virtualenv activated

## One-time IAM fixes (new GCP project)

New projects often lack the right IAM bindings for Cloud Run source deploys.
Run these once; they are idempotent.

### 1. Grant Cloud Build permission to read uploaded source from GCS

```bash
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

**Why:** `gcloud run deploy --source` uploads source to a GCS bucket, then Cloud Build
reads it back using the Compute service account. Without this the build fails with:
`Error 403: does not have storage.objects.get access`.

### 2. Grant the Compute service account permission to push images to Artifact Registry

```bash
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

**Why:** `gcloud run deploy --source` and `gcloud builds submit` both execute Cloud Build
jobs that run as the **Compute service account** (`PROJECT_NUMBER-compute@...`), not the
Cloud Build builder account. This account must have `artifactregistry.writer` to push the
built image. Without it, the Docker build step shows SUCCESS but the overall build is FAILURE
with `Permission 'artifactregistry.repositories.uploadArtifacts' denied`.

> **Note:** Granting `artifactregistry.writer` to `PROJECT_NUMBER@cloudbuild.gserviceaccount.com`
> or `service-PROJECT_NUMBER@gcp-sa-cloudbuild.iam.gserviceaccount.com` has no effect here —
> those accounts are not the ones running the build.

---

## Finding your PROJECT_NUMBER

```bash
gcloud projects describe <PROJECT_ID> --format="value(projectNumber)"
```

---

## Deploy

```bash
cd 01_adk_with_mcp/mcp_server
./deploy.sh
```

The script:
1. Enables required GCP APIs (`run`, `artifactregistry`, `cloudbuild`)
2. Creates an Artifact Registry Docker repo named `mcp-servers` (idempotent)
3. Builds the container from source and deploys to Cloud Run with **Streamable HTTP** transport
4. Prints the service URL and MCP endpoint

---

## Transport: Streamable HTTP (not SSE)

The server uses the **Streamable HTTP** transport (the modern MCP standard) instead of the
legacy SSE transport. Key details:

- Endpoint: `/mcp` (POST)
- Required headers: `Content-Type: application/json` + `Accept: application/json, text/event-stream`
- DNS rebinding protection is disabled via `TransportSecuritySettings(enable_dns_rebinding_protection=False)`
  — safe on Cloud Run since TLS handles security at the infrastructure level.

**Why not SSE?** Cloud Run returns HTTP 421 on SSE connections due to HTTP/2 host validation
mismatches. Streamable HTTP works cleanly via POST.

### Verify the endpoint

```bash
curl -X POST https://<YOUR_CLOUD_RUN_URL>/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

Expected response: SSE event with `protocolVersion` in the JSON payload.

---

## After deployment

Set the server URL in `.env`:

```
MCP_SERVER_URL=https://<YOUR_CLOUD_RUN_URL>/mcp
```

For ADK remote agent (`adk_agents/remote_agent/agent.py`), SSE is still supported on `/sse`:

```python
SseServerParams(url="https://<YOUR_CLOUD_RUN_URL>/sse")
```

---

## Connecting to Claude Desktop

1. Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "learn-mcp-server": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "https://<YOUR_CLOUD_RUN_URL>/mcp"]
    }
  }
}
```

2. Restart Claude Desktop (Cmd+Q, then reopen).
3. Look for the hammer icon in the chat input — your tools will be listed there.

**Why `mcp-remote`?** Claude Desktop only supports stdio natively. `mcp-remote` acts as a
bridge that connects stdio (Claude Desktop) to the remote Streamable HTTP server.

---

## Connecting to Claude Web (claude.ai)

1. Go to **Settings → Integrations → Add custom integration**
2. Enter URL: `https://<YOUR_CLOUD_RUN_URL>/mcp`
3. Save and start a new chat.

Requires a Pro/Team plan. The server must be publicly accessible (Cloud Run with
`--allow-unauthenticated` satisfies this).

---

## Cold start & instance settings

`deploy.sh` uses `--min-instances=1` to keep one instance warm at all times, avoiding
cold start delays (~5-10s for a Python container). For cost savings on a learning project,
set back to `--min-instances=0` — cold starts are acceptable for infrequent use.

---

## Deleting everything

### Level 1 — Delete just the Cloud Run service
```bash
gcloud run services delete learning-mcp-server \
  --region=us-central1 \
  --project=<YOUR_PROJECT_ID>
```

### Level 2 — Delete Cloud Run + container images

First check which Artifact Registry repo was actually created (it may be `cloud-run-source-deploy`, not `mcp-servers`):
```bash
gcloud artifacts repositories list \
  --location=us-central1 \
  --project=<YOUR_PROJECT_ID>
```

Then delete the correct repo:
```bash
gcloud artifacts repositories delete cloud-run-source-deploy \
  --location=us-central1 \
  --project=<YOUR_PROJECT_ID>
```

> **Note:** `gcloud run deploy --source` always stores images in `cloud-run-source-deploy`, not the `mcp-servers` repo created by the script.

### Level 3 — Delete the entire GCP project (nuclear)
```bash
gcloud projects delete <YOUR_PROJECT_ID>
```
Removes everything — Cloud Run, Artifact Registry, billing. **Irreversible after 30 days.**
Can be undone within the grace period with:
```bash
gcloud projects undelete <YOUR_PROJECT_ID>
```

### Clean up Claude Desktop
Remove the `learn-mcp-server` entry from `~/Library/Application Support/Claude/claude_desktop_config.json`, then restart Claude Desktop.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Error 403: storage.objects.get denied` | Compute SA missing GCS read | Grant `roles/storage.objectViewer` to Compute SA (step 1 above) |
| Build step SUCCESS but overall FAILURE with `uploadArtifacts denied` | Compute SA missing Artifact Registry write | Grant `roles/artifactregistry.writer` to Compute SA (step 2 above) |
| `Invalid Host header` (curl returns 400/421) | FastMCP DNS rebinding protection rejecting Cloud Run host | Set `TransportSecuritySettings(enable_dns_rebinding_protection=False)` in `server.py` |
| SSE error 421 from `mcp-remote` | Cloud Run HTTP/2 rejects SSE host validation | Switch to Streamable HTTP transport (`/mcp`) instead of SSE (`/sse`) |
| `Not Acceptable: Client must accept both application/json and text/event-stream` | Missing `Accept` header | Add `-H "Accept: application/json, text/event-stream"` to curl / client request |
| `TypeError: FastMCP.run() got an unexpected keyword argument 'host'` | mcp v1.x API change | Set `mcp.settings.host` and `mcp.settings.port` before calling `mcp.run()` |
| Container starts then crashes | Server startup error | Check `gcloud run services logs read learning-mcp-server --region=us-central1` |
| Slow first response in Claude Desktop/web | Cold start (min-instances=0) | Set `--min-instances=1` in `deploy.sh` and redeploy |
| Claude uses built-in tools instead of MCP tools | Claude prefers built-in tools when overlap exists | Explicitly name the MCP tool: "use the get_weather tool from learn-mcp-server" |
