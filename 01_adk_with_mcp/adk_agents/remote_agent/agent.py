"""
Remote MCP agent — connects to the MCP server deployed on GCP Cloud Run.

After running deploy.sh, set MCP_SERVER_URL in your .env:
    MCP_SERVER_URL=https://learning-mcp-server-xxxx-uc.a.run.app/sse

Run with:
    cd 01_adk_with_mcp/adk_agents
    adk web remote_agent
    adk run remote_agent

This is identical to single_agent but uses SseServerParams instead of
StdioServerParameters — the only difference between local and remote MCP.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams

load_dotenv(Path(__file__).parent.parent.parent / ".env")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080/sse")

root_agent = LlmAgent(
    name="remote_mcp_assistant",
    model="gemini-2.5-flash",
    description="Assistant backed by a remote MCP server on GCP Cloud Run.",
    instruction="""You are a helpful assistant with access to remote MCP tools.

Available capabilities (served from GCP Cloud Run):
- get_weather(city)           → current weather conditions
- calculate(expression)       → safe math evaluation
- get_stock_price(ticker)     → stock prices (AAPL, GOOGL, TSLA, NVDA …)
- get_current_datetime()      → current UTC date and time

Always use tools for data lookups. Be concise and helpful.
""",
    tools=[
        MCPToolset(
            connection_params=SseServerParams(
                url=MCP_SERVER_URL,
                # headers={"Authorization": "Bearer YOUR_TOKEN"},  # add auth for prod
            )
        )
    ],
)
