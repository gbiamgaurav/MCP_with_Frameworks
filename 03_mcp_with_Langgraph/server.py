"""
LangGraph MCP Server
Exposes five complex tools, each backed by a multi-step LangGraph StateGraph pipeline.

Tools
─────
  research_topic    — Wikipedia research pipeline (5 nodes + optional loop)
  review_code       — AST-based code review pipeline (6 nodes)
  analyze_document  — NLP document analysis pipeline (6 nodes)
  analyze_data      — Statistical data analysis pipeline (5 nodes)
  plan_task         — Goal-to-plan pipeline with type-conditional routing (6 nodes)

Transport
─────────
  stdio  — default (used by ADK, Claude Desktop subprocess)
  http   — Streamable HTTP on /mcp (for Cloud Run / claude.ai web)
  sse    — Legacy SSE on /sse (for older Claude Desktop remote config)
"""

import os
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from graphs.research_graph import compiled as research_graph
from graphs.code_review_graph import compiled as code_review_graph
from graphs.document_graph import compiled as document_graph
from graphs.data_analysis_graph import compiled as data_analysis_graph
from graphs.task_planner_graph import compiled as task_planner_graph

load_dotenv()

_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
mcp = FastMCP("langgraph-mcp-server", transport_security=_security)


# ── Tool 1: Research Pipeline ──────────────────────────────────────────────────

@mcp.tool()
async def research_topic(topic: str, depth: str = "standard") -> str:
    """
    Research any topic using a multi-step LangGraph pipeline backed by Wikipedia.

    Pipeline: plan_research → fetch_wikipedia → extract_key_facts
              → [fetch_related_topics (loops ≤2×, deep only)] → compile_report

    Args:
        topic: The subject to research (e.g. "quantum computing", "the Roman Empire").
        depth: "brief" — 2 focused questions, single Wikipedia fetch.
               "standard" — 4 questions, overview + key facts.
               "deep" — 6 questions + up to 2 additional related-topic searches.

    Returns:
        Structured markdown report with overview, key facts, sources, and research questions.
    """
    result = await research_graph.ainvoke({
        "topic": topic,
        "depth": depth,
        "search_title": topic.replace(" ", "_"),
        "sub_questions": [],
        "wikipedia_summary": "",
        "additional_summaries": [],
        "key_facts": [],
        "sources": [],
        "report": "",
        "status": "init",
        "iteration": 0,
        "error": None,
    })
    return result["report"]


# ── Tool 2: Code Review Pipeline ───────────────────────────────────────────────

@mcp.tool()
async def review_code(code: str, language: str = "python") -> str:
    """
    Perform a comprehensive static code review using a multi-step LangGraph pipeline.

    Pipeline: parse_ast → analyze_metrics → detect_issues
              → score_code → generate_suggestions → format_report

    For Python: full AST-based analysis (complexity, nesting, security, style, docstrings,
    mutable defaults, eval/exec detection).
    For other languages: text-based analysis (line length, hardcoded secrets, TODO markers).

    Args:
        code: Source code string to review.
        language: Programming language — "python" gets deep AST analysis; others get text analysis.

    Returns:
        Detailed markdown report with quality score (0–10), grade (A–F), metrics,
        categorised issues, and prioritised improvement suggestions.
    """
    result = await code_review_graph.ainvoke({
        "code": code,
        "language": language,
        "ast_tree": None,
        "parse_error": None,
        "metrics": {},
        "issues": [],
        "suggestions": [],
        "score": 10.0,
        "report": "",
    })
    return result["report"]


# ── Tool 3: Document Analysis Pipeline ────────────────────────────────────────

@mcp.tool()
async def analyze_document(text: str) -> str:
    """
    Perform deep NLP-style document analysis using a multi-step LangGraph pipeline.

    Pipeline: segment_text → extract_entities → score_sentences
              → analyze_readability → extract_action_items → compile_analysis

    Args:
        text: The full text of the document to analyse. Supports any length — articles,
              meeting notes, emails, reports, README files, etc.

    Returns:
        Structured markdown report containing:
          • Statistics (word count, sentence count, avg words/sentence)
          • Flesch Reading Ease score and grade level
          • Auto-generated extractive summary
          • Key sentences ranked by TF-based importance
          • Named entities, key phrases, numbers, emails, URLs
          • Extracted action items (sentences containing obligation language)
    """
    result = await document_graph.ainvoke({
        "text": text,
        "sentences": [],
        "word_count": 0,
        "word_frequency": {},
        "entities": {},
        "sentence_scores": [],
        "key_sentences": [],
        "readability_score": 0.0,
        "readability_level": "Unknown",
        "action_items": [],
        "summary": "",
        "analysis": "",
    })
    return result["analysis"]


# ── Tool 4: Data Analysis Pipeline ────────────────────────────────────────────

@mcp.tool()
async def analyze_data(raw_data: str, data_format: str = "auto") -> str:
    """
    Perform statistical analysis on tabular data using a multi-step LangGraph pipeline.

    Pipeline: parse_data → compute_statistics → detect_anomalies
              → find_trends → generate_insights

    Args:
        raw_data: Data as a CSV string (with a header row) or a JSON array of objects.
            CSV example:
                name,age,score
                Alice,30,85
                Bob,25,92
                Carol,35,78
            JSON example:
                [{"name":"Alice","age":30,"score":85},{"name":"Bob","age":25,"score":92}]
        data_format: "csv" | "json" | "auto" (default — detects from content).

    Returns:
        Comprehensive markdown report with:
          • Per-column profiles: type, count, missing, unique, min/max/mean/median/stdev/IQR
          • Anomaly detection: z-score outliers (|z|>3) and IQR fence outliers (1.5×IQR)
          • Trend analysis: first-half vs second-half change, volatility (CV), Pearson correlations
          • Plain-English summary insights
    """
    result = await data_analysis_graph.ainvoke({
        "raw_data": raw_data,
        "data_format": data_format,
        "records": [],
        "columns": [],
        "column_stats": [],
        "anomalies": [],
        "trends": [],
        "insights": "",
        "report": "",
        "error": None,
    })
    return result["report"]


# ── Tool 5: Task Planner Pipeline ─────────────────────────────────────────────

@mcp.tool()
async def plan_task(goal: str, task_type: str = "auto") -> str:
    """
    Generate a structured, phase-by-phase task plan using a multi-step LangGraph pipeline.

    Pipeline: classify_goal → define_phases → generate_tasks
              → estimate_timeline → identify_risks → finalize_plan

    The pipeline auto-selects a phase template appropriate to the goal type and
    scales task complexity to the goal's length/ambiguity.

    Args:
        goal: What you want to achieve. Be as specific as possible.
            Examples:
              "Build a REST API for user authentication with JWT tokens"
              "Learn Rust from scratch to intermediate level"
              "Resolve the production database connection pool exhaustion issue"
              "Research the environmental impact of large language models"
        task_type: Override the auto-classification.
            "project"         — software / business / creative projects
            "learning"        — skill acquisition, courses, self-study
            "problem_solving" — bugs, incidents, process failures
            "research"        — academic / technical / market research
            "auto"            — keyword-based detection (default)

    Returns:
        Full markdown plan with:
          • Classified goal type
          • Phase breakdown with estimated days and key deliverable
          • Task list per phase with priority (🔴/🟡/🟢) and effort estimate
          • Day-by-day milestone chart
          • Effort summary (total days, hours, recommended daily pace)
          • Risk register with mitigations
          • Success criteria checklist
    """
    result = await task_planner_graph.ainvoke({
        "goal": goal,
        "task_type": task_type,
        "classified_type": "",
        "phases": [],
        "all_tasks": [],
        "timeline": {},
        "risks": [],
        "success_criteria": [],
        "final_plan": "",
    })
    return result["final_plan"]


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if "--http" in sys.argv:
        transport = "http"
    elif "--sse" in sys.argv:
        transport = "sse"

    port = int(os.getenv("PORT", "8080"))

    if transport == "http":
        import uvicorn
        print(f"Starting LangGraph MCP server (Streamable HTTP) on port {port}", flush=True)
        uvicorn.run(
            mcp.streamable_http_app(),
            host="0.0.0.0",
            port=port,
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
    elif transport == "sse":
        import uvicorn
        print(f"Starting LangGraph MCP server (SSE) on port {port}", flush=True)
        uvicorn.run(
            mcp.sse_app(),
            host="0.0.0.0",
            port=port,
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
    else:
        mcp.run()
