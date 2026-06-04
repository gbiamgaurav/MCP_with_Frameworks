"""
Single LlmAgent connected to the local MCP server via stdio.

Run with:
    cd 01_adk_with_mcp/adk_agents
    adk web single_agent          # opens browser UI
    adk run single_agent          # interactive CLI

The agent gets weather, stock, calculator, and datetime tools from
the MCP server subprocess. ADK manages the subprocess lifecycle.
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

# Absolute path so the agent works regardless of CWD
MCP_SERVER_PATH = Path(__file__).parent.parent.parent / "mcp_server" / "server.py"

root_agent = LlmAgent(
    name="mcp_assistant",
    model="gemini-2.5-flash",
    description="A general-purpose assistant backed by MCP tools for weather, math, stocks, and time.",
    instruction="""You are a helpful assistant with access to real-time tools via MCP.

Available capabilities:
- get_weather(city)           → current weather conditions
- calculate(expression)       → safe math evaluation (supports sqrt, sin, cos, pi, e …)
- get_stock_price(ticker)     → live-ish stock prices (AAPL, GOOGL, TSLA, NVDA …)
- get_current_datetime()      → current UTC date and time

Guidelines:
1. Always use a tool when the user asks for data you can look up.
2. Show tool results in a clean, readable format.
3. If asked for multiple things, call all relevant tools before answering.
4. For math, show the expression and result clearly.
""",
    tools=[
        MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=sys.executable,
                    args=[str(MCP_SERVER_PATH)],
                )
            )
        )
    ],
)
