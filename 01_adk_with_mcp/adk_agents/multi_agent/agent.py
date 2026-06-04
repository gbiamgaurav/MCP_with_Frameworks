"""
Multi-agent system using ADK's SequentialAgent.

Pipeline:  researcher → analyst → reporter

1. researcher  — fetches raw data using MCP tools
2. analyst     — identifies patterns & insights from research
3. reporter    — writes the final structured markdown report

The three agents share a single session; each writes its output to
session state via `output_key` so the next agent can build on it.

Run with:
    cd 01_adk_with_mcp/adk_agents
    adk web multi_agent
    adk run multi_agent

Example prompt:
    "Research weather in London, New York, and Tokyo. Compare them and write a report."
"""

import sys
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

MCP_SERVER_PATH = Path(__file__).parent.parent.parent / "mcp_server" / "server.py"


def _mcp_toolset() -> MCPToolset:
    """Create a fresh MCPToolset instance pointing at the local server."""
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[str(MCP_SERVER_PATH)],
            )
        )
    )


# ---------------------------------------------------------------------------
# Agent 1: Researcher
# Gathers raw data using MCP tools and stores it in session state.
# ---------------------------------------------------------------------------

researcher = LlmAgent(
    name="researcher",
    model="gemini-2.5-flash",
    description="Gathers raw data using MCP tools based on the user's request.",
    instruction="""You are a research agent. Your job is to collect factual data.

- Use get_weather() for any city mentioned.
- Use get_stock_price() for any tickers mentioned.
- Use calculate() for any numbers that need computing.
- Use get_current_datetime() if time context is needed.

Call ALL relevant tools before writing your output.
Format your output as structured JSON-like data so the analyst can work with it.
Be thorough — gather everything the user asked for.
""",
    tools=[_mcp_toolset()],
    output_key="research_data",
)


# ---------------------------------------------------------------------------
# Agent 2: Analyst
# Reads research_data from state and produces analytical insights.
# ---------------------------------------------------------------------------

analyst = LlmAgent(
    name="analyst",
    model="gemini-2.5-flash",
    description="Analyzes raw research data and extracts insights and patterns.",
    instruction="""You are a data analyst. The previous research agent has collected data.

Review the research data available in the conversation and:
1. Identify key patterns, trends, and comparisons.
2. Highlight notable differences or similarities.
3. Point out anything surprising or significant.
4. Calculate derived metrics if useful (e.g. temp difference, % change).

Be analytical and precise. Format as bullet points and short paragraphs.
""",
    output_key="analysis",
)


# ---------------------------------------------------------------------------
# Agent 3: Reporter
# Combines research + analysis into a final markdown report.
# ---------------------------------------------------------------------------

reporter = LlmAgent(
    name="reporter",
    model="gemini-2.5-flash",
    description="Creates a final, well-structured markdown report from research and analysis.",
    instruction="""You are a professional report writer.

The conversation history contains:
- Raw research data (from the researcher agent)
- Analytical insights (from the analyst agent)

Write a clean, well-structured markdown report that includes:
1. **Executive Summary** (2–3 sentences)
2. **Data Overview** (present the raw data in a readable table or list)
3. **Key Insights** (from the analyst's findings)
4. **Conclusion** (actionable takeaways or next steps)

Use proper markdown: headings, bold, tables, bullet lists.
Make it polished enough to share with a non-technical audience.
""",
    output_key="final_report",
)


# ---------------------------------------------------------------------------
# Root agent: SequentialAgent orchestrates researcher → analyst → reporter
# ---------------------------------------------------------------------------

root_agent = SequentialAgent(
    name="research_pipeline",
    description="Multi-agent pipeline: researcher gathers data → analyst finds insights → reporter writes the final report.",
    sub_agents=[researcher, analyst, reporter],
)
