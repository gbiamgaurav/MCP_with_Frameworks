"""
Multi-Agent Orchestration with LangGraph + Gemini
===================================================

Five specialized agents collaborate to produce a blog post:

  supervisor  ->  researcher  ->  writer  ->  editor  ->  publisher
                    ^_____________^  (rewrite loop, max 2x)

Key LangGraph concepts illustrated
-----------------------------------
  1. TypedDict state     -- shared "message bus" every agent reads/writes
  2. StateGraph nodes    -- each agent is a plain Python function
  3. Conditional edges   -- supervisor routes based on current stage
  4. Looping             -- editor can send work back to writer
  5. END termination     -- publisher writes final output, graph stops
  6. Real LLM calls      -- every agent uses Gemini via google-genai SDK
  7. Tool calling        -- researcher uses Gemini function-calling to decide
                           when/how to invoke web_search

Run:
  python 04_multiagent_orchestration/multiagent_workflow.py
  python 04_multiagent_orchestration/multiagent_workflow.py "machine learning"
"""

import os
import sys
import textwrap
from contextvars import ContextVar
from typing import Annotated, Callable, Literal

from dotenv import load_dotenv
from duckduckgo_search import DDGS
from typing_extensions import TypedDict

from google import genai
from google.genai import types
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

load_dotenv()

# ── Gemini client ─────────────────────────────────────────────────────────────
_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = "gemini-2.5-flash"


# ── Event system ──────────────────────────────────────────────────────────────
# Any code can register a hook (e.g. the streaming API endpoint) to receive
# events in real time.  The terminal always prints them regardless.

_event_hook: ContextVar[Callable[[dict], None] | None] = ContextVar(
    "_event_hook", default=None
)


def _emit(event: dict) -> None:
    """Print the event to stdout and forward it to any registered hook."""
    _print_event(event)
    hook = _event_hook.get()
    if hook:
        hook(event)


def _print_event(event: dict) -> None:
    t = event.get("type", "")
    if t == "agent_start":
        print(f"\n[{event['agent'].upper()}] starting", flush=True)
    elif t == "tool_call":
        print(f"  --> web_search(query={event['query']!r})", flush=True)
    elif t == "tool_result":
        preview = event.get("preview", "").replace("\n", " ")[:150]
        print(f"  <-- {preview}...", flush=True)
    elif t == "agent_done":
        print(f"  done: {event.get('summary', '')}", flush=True)
    elif t == "supervisor_route":
        print(f"\n[SUPERVISOR] {event['from']!r} --> {event['to']!r}", flush=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _call_gemini(prompt: str) -> str:
    response = _client.models.generate_content(model=MODEL, contents=prompt)
    return response.text.strip()


def _web_search(query: str, max_results: int = 5) -> str:
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    if not results:
        return "No web results found."
    lines = [
        f"- {r['title']}\n  {r['body']}\n  Source: {r['href']}"
        for r in results
    ]
    return "\n\n".join(lines)


# ── Tool definition Gemini understands ───────────────────────────────────────
_WEB_SEARCH_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="web_search",
            description=(
                "Search the web for current information about a topic. "
                "Call this whenever you need up-to-date facts, statistics, or news."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="The search query string",
                    ),
                    "max_results": types.Schema(
                        type=types.Type.INTEGER,
                        description="Max number of results to return (default 5)",
                    ),
                },
                required=["query"],
            ),
        )
    ]
)


def _run_with_tools(prompt: str) -> tuple[str, list[str]]:
    """Gemini agentic loop: model decides when to call web_search.

    Emits events for every tool call and result so callers can observe
    the reasoning in real time (terminal prints + optional SSE hook).

    Returns (final_text, list_of_raw_search_results).
    """
    contents: list = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    ]
    searches_collected: list[str] = []

    while True:
        response = _client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(tools=[_WEB_SEARCH_TOOL]),
        )

        candidate = response.candidates[0]
        parts = candidate.content.parts or []
        fn_calls = [p for p in parts if p.function_call is not None]

        if not fn_calls:
            text_parts = [p.text for p in parts if getattr(p, "text", None)]
            text = "\n".join(text_parts).strip() or getattr(response, "text", "") or ""
            return text, searches_collected

        contents.append(candidate.content)

        result_parts: list[types.Part] = []
        for p in fn_calls:
            fc = p.function_call
            if fc.name == "web_search":
                query = fc.args.get("query", "")
                max_r = int(fc.args.get("max_results", 5))

                _emit({"type": "tool_call", "tool": "web_search", "query": query})
                result = _web_search(query, max_results=max_r)
                _emit({
                    "type": "tool_result",
                    "tool": "web_search",
                    "query": query,
                    "preview": result[:300],
                })

                searches_collected.append(f"[query: {query!r}]\n{result}")
                result_parts.append(
                    types.Part.from_function_response(
                        name="web_search",
                        response={"result": result},
                    )
                )

        contents.append(types.Content(role="user", parts=result_parts))


# ── 1. SHARED STATE ───────────────────────────────────────────────────────────

class BlogState(TypedDict):
    topic: str
    stage: str
    search_results: str
    outline: str
    draft: str
    editor_verdict: str
    editor_notes: str
    quality_score: int
    rewrite_count: int
    final_post: str
    log: Annotated[list[str], add_messages]


# ── 2. AGENT NODES ────────────────────────────────────────────────────────────

def supervisor(state: BlogState) -> dict:
    current = state["stage"]
    stage_map = {
        "start":         "researching",
        "researched":    "writing",
        "drafted":       "editing",
        "approved":      "publishing",
        "needs_rewrite": "writing" if state["rewrite_count"] < 2 else "publishing",
    }
    next_stage = stage_map.get(current, "publishing")
    _emit({"type": "supervisor_route", "from": current, "to": next_stage})
    return {
        "stage": next_stage,
        "log": [f"[supervisor] {current!r} -> {next_stage!r}"],
    }


def researcher(state: BlogState) -> dict:
    topic = state["topic"]
    _emit({"type": "agent_start", "agent": "researcher"})

    prompt = f"""You are a research analyst. Your job is to create a structured outline \
for a blog post about "{topic}".

You have access to the web_search tool. Use it to gather current, real-world information \
before writing. Make 2-3 targeted searches to cover the topic well.

After searching, respond with ONLY a numbered list of 6-7 section headings (no extra text).
Each heading must be specific and grounded in what you found.

Example format:
1. Introduction: Why [topic] is reshaping industries
2. Core principles of [topic]
...
"""
    outline, searches = _run_with_tools(prompt)
    combined = "\n\n---\n\n".join(searches) if searches else "No web search performed."

    _emit({"type": "agent_done", "agent": "researcher",
           "summary": f"{len(searches)} search(es), outline ready"})
    return {
        "search_results": combined,
        "outline": outline,
        "stage": "researched",
        "log": [f"[researcher] {len(searches)} web search(es), outline ready for: {topic!r}"],
    }


def writer(state: BlogState) -> dict:
    topic = state["topic"]
    _emit({"type": "agent_start", "agent": "writer"})

    rewrite = state["rewrite_count"]
    rewrite_instruction = ""
    if rewrite > 0 and state["editor_notes"]:
        rewrite_instruction = (
            f"\n\nThis is revision #{rewrite}. "
            f"Editor feedback to address:\n{state['editor_notes']}"
        )

    prompt = f"""You are a professional blog writer. Write a complete, engaging blog post \
about "{topic}".

Use this outline as your structure:
{state['outline']}
{rewrite_instruction}

Guidelines:
- Write full paragraphs for each section (not placeholders)
- Use markdown headings (# for title, ## for sections)
- Keep it informative, clear, and engaging
- Aim for 400-600 words total
"""
    draft = _call_gemini(prompt)
    _emit({"type": "agent_done", "agent": "writer",
           "summary": f"draft written — {len(draft)} chars"})
    return {
        "draft": draft,
        "stage": "drafted",
        "rewrite_count": rewrite + (1 if rewrite > 0 else 0),
        "log": [f"[writer] draft written (revision {rewrite}), {len(draft)} chars"],
    }


def editor(state: BlogState) -> dict:
    _emit({"type": "agent_start", "agent": "editor"})

    prompt = f"""You are a senior editor. Review this blog post draft and respond in \
EXACTLY this format:

SCORE: [number 1-10]
VERDICT: [approved OR needs_rewrite]
NOTES: [one sentence of specific feedback, or "None" if approved]

Criteria:
- Score 7+ -> approved (good structure, depth, clarity, engaging tone)
- Score below 7 -> needs_rewrite (explain what to fix in NOTES)

Draft to review:
---
{state['draft']}
---
"""
    response = _call_gemini(prompt)

    score, verdict, notes = 7, "approved", "None"
    for line in response.splitlines():
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                score = int(line.split(":", 1)[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
        elif line.startswith("VERDICT:"):
            raw = line.split(":", 1)[1].strip().lower()
            verdict = "approved" if "approved" in raw else "needs_rewrite"
        elif line.startswith("NOTES:"):
            notes = line.split(":", 1)[1].strip()

    _emit({"type": "agent_done", "agent": "editor",
           "summary": f"score={score}/10, verdict={verdict!r}"})
    return {
        "quality_score": score,
        "editor_verdict": verdict,
        "editor_notes": notes,
        "stage": verdict,
        "log": [f"[editor] score={score}/10, verdict={verdict!r}, notes={notes!r}"],
    }


def publisher(state: BlogState) -> dict:
    topic = state["topic"]
    _emit({"type": "agent_start", "agent": "publisher"})

    final = textwrap.dedent(f"""
    +----------------------------------------------------------+
    |  PUBLISHED POST                                          |
    +----------------------------------------------------------+
    |  Topic    : {topic:<44} |
    |  Quality  : {state['quality_score']}/10{' ' * 42}|
    |  Rewrites : {state['rewrite_count']:<44} |
    +----------------------------------------------------------+

    {state['draft']}
    """).strip()

    _emit({"type": "agent_done", "agent": "publisher", "summary": "post published"})
    return {
        "final_post": final,
        "stage": "published",
        "log": [f"[publisher] post published — topic: {topic!r}"],
    }


# ── 3. ROUTING ────────────────────────────────────────────────────────────────

def route_after_supervisor(state: BlogState) -> Literal[
    "researcher", "writer", "editor", "publisher"
]:
    return {
        "researching": "researcher",
        "writing":     "writer",
        "editing":     "editor",
        "publishing":  "publisher",
    }[state["stage"]]


# ── 4. GRAPH ASSEMBLY ─────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(BlogState)
    g.add_node("supervisor", supervisor)
    g.add_node("researcher", researcher)
    g.add_node("writer",     writer)
    g.add_node("editor",     editor)
    g.add_node("publisher",  publisher)

    g.set_entry_point("supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"researcher": "researcher", "writer": "writer",
         "editor": "editor", "publisher": "publisher"},
    )
    g.add_edge("researcher", "supervisor")
    g.add_edge("writer",     "supervisor")
    g.add_edge("editor",     "supervisor")
    g.add_edge("publisher",  END)
    return g.compile()


# ── 5. MAIN ───────────────────────────────────────────────────────────────────

def run(topic: str = "artificial intelligence") -> None:
    print(f"\n{'='*60}")
    print(f"  Multi-Agent Orchestration  |  topic: {topic!r}")
    print(f"{'='*60}")

    graph = build_graph()
    initial_state: BlogState = {
        "topic":          topic,
        "stage":          "start",
        "search_results": "",
        "outline":        "",
        "draft":          "",
        "editor_verdict": "",
        "editor_notes":   "",
        "quality_score":  0,
        "rewrite_count":  0,
        "final_post":     "",
        "log":            [],
    }

    final_state = None
    for step in graph.stream(initial_state, stream_mode="values"):
        final_state = step

    print(f"\n{'='*60}\nFINAL OUTPUT\n{'='*60}\n")
    print(final_state["final_post"])
    print(f"\n[Pipeline complete — {len(final_state['log'])} agent steps]\n")


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "artificial intelligence"
    run(topic)
