# Module 01 — ADK + MCP on GCP

Learn Google's **Agent Development Kit (ADK)** with **Model Context Protocol (MCP)**,
from local development to production on **GCP Cloud Run**.

---

## What You'll Learn

| Concept | File |
|---|---|
| FastMCP server with tools | `mcp_server/server.py` |
| Single LlmAgent + local MCP (stdio) | `adk_agents/single_agent/agent.py` |
| Multi-agent pipeline (SequentialAgent) | `adk_agents/multi_agent/agent.py` |
| Remote MCP agent (SSE / Cloud Run) | `adk_agents/remote_agent/agent.py` |
| Programmatic runner (no CLI) | `adk_agents/main.py` |
| Deploy MCP server to Cloud Run | `mcp_server/deploy.sh` |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        ADK Agent                            │
│                                                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐  │
│  │  researcher │──▶│   analyst   │──▶│    reporter     │  │
│  │  (LlmAgent) │   │  (LlmAgent) │   │   (LlmAgent)    │  │
│  └──────┬──────┘   └─────────────┘   └─────────────────┘  │
│         │ MCPToolset                                         │
└─────────┼───────────────────────────────────────────────────┘
          │
    ┌─────▼──────────────────────────────┐
    │          MCP Server                │
    │  (FastMCP — stdio or SSE)          │
    │                                    │
    │  • get_weather(city)               │
    │  • calculate(expression)           │
    │  • get_stock_price(ticker)         │
    │  • get_current_datetime()          │
    └────────────────────────────────────┘

Local:  ADK ──stdio──▶ MCP subprocess
Remote: ADK ──SSE───▶ MCP on Cloud Run
```

---

## Quick Start

### 1. Install dependencies

```bash
cd 01_adk_with_mcp
uv venv
source .venv/bin/activate   # macOS/Linux
uv pip install -r requirements.txt
```

### 2. Set your API key

```bash
cp .env.example .env
# Edit .env — add your GOOGLE_API_KEY from https://aistudio.google.com/apikey
```

### 3. Run the single agent (browser UI)

```bash
cd adk_agents
adk web single_agent
# Opens http://localhost:8000 — try: "What's the weather in Tokyo?"
```

### 4. Run the multi-agent pipeline

```bash
cd adk_agents
adk web multi_agent
# Try: "Research weather in London, New York, Tokyo and write a comparison report"
```

### 5. Run programmatically (no browser)

```bash
cd 01_adk_with_mcp
python adk_agents/main.py single "What's the AAPL stock price and weather in NYC?"
python adk_agents/main.py multi  "Research weather in Paris and Tokyo, then write a report."
```

---

## Deploy MCP Server to GCP Cloud Run

### Prerequisites

```bash
brew install google-cloud-sdk   # macOS
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### Deploy in one command

```bash
export GCP_PROJECT_ID=your-project-id
cd 01_adk_with_mcp/mcp_server
chmod +x deploy.sh
./deploy.sh
```

The script will:
1. Enable Cloud Run + Artifact Registry APIs
2. Build a Docker image from `Dockerfile`
3. Deploy to Cloud Run with SSE transport
4. Print the public URL

### Connect the remote agent

After deployment, copy the SSE URL into `.env`:

```bash
MCP_SERVER_URL=https://learning-mcp-server-xxxx-uc.a.run.app/sse
```

Then run:

```bash
cd adk_agents
adk web remote_agent
```

---

## Connecting to Other Agentic Frameworks

Once your MCP server is on Cloud Run, ANY MCP-compatible framework can connect to it.

### LangChain

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient({
    "learning-tools": {
        "url": "https://your-server.run.app/sse",
        "transport": "sse",
    }
}) as client:
    tools = client.get_tools()
    # use tools with any LangChain agent
```

### LangGraph

```python
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient({"tools": {"url": MCP_URL, "transport": "sse"}}) as client:
    agent = create_react_agent(model, client.get_tools())
    result = await agent.ainvoke({"messages": [{"role": "user", "content": query}]})
```

### Claude (Anthropic SDK)

```python
import anthropic

client = anthropic.Anthropic()
# Claude Desktop: add to claude_desktop_config.json
# {
#   "mcpServers": {
#     "learning-tools": {
#       "url": "https://your-server.run.app/sse",
#       "transport": "sse"
#     }
#   }
# }
```

### OpenAI Agents SDK

```python
from agents import Agent
from agents.mcp import MCPServerSse

server = MCPServerSse(params={"url": "https://your-server.run.app/sse"})
agent = Agent(name="assistant", mcp_servers=[server])
```

---

## Key Concepts

| Term | What it means |
|---|---|
| **MCP** | Model Context Protocol — standard for tools/resources exposed to LLMs |
| **FastMCP** | Python library to build MCP servers easily |
| **stdio transport** | MCP server runs as a local subprocess (pipe-based) |
| **SSE transport** | MCP server runs remotely over HTTP (Server-Sent Events) |
| **MCPToolset** | ADK class that connects an agent to an MCP server |
| **StdioServerParameters** | Config for local subprocess MCP connection |
| **SseServerParams** | Config for remote HTTP/SSE MCP connection |
| **LlmAgent** | ADK agent powered by a language model |
| **SequentialAgent** | ADK orchestrator: runs sub-agents one after another |
| **output_key** | Saves an agent's output to session state for the next agent |

---

## Next Modules (coming soon)

- `02_langchain_with_mcp/` — LangChain + MCP client
- `03_langgraph_with_mcp/` — LangGraph stateful agents + MCP
- `04_azure_deployment/` — Deploy MCP server to Azure Container Apps
- `05_aws_deployment/` — Deploy MCP server to AWS Lambda + API Gateway
