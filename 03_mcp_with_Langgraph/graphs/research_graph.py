"""
Research Pipeline — LangGraph StateGraph
Nodes: plan → fetch_wiki → extract_facts → [fetch_related (loop up to 2x)] → compile
Conditional routing: depth=="deep" triggers up to 2 related-topic fetches.
Uses the Wikipedia REST API v1 (no auth required).
"""

import httpx
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, START, END

_USER_AGENT = "LangGraph-MCP-Server/1.0 (Educational)"
_WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"


class ResearchState(TypedDict):
    topic: str
    depth: str
    search_title: str
    sub_questions: List[str]
    wikipedia_summary: str
    additional_summaries: List[str]
    key_facts: List[str]
    sources: List[str]
    report: str
    status: str
    iteration: int
    error: Optional[str]


async def plan_research(state: ResearchState) -> dict:
    topic = state["topic"]
    depth = state.get("depth", "standard")

    questions = [
        f"What is {topic} and how is it defined?",
        f"What are the key components or characteristics of {topic}?",
    ]
    if depth in ("standard", "deep"):
        questions += [
            f"What is the historical background of {topic}?",
            f"What are practical applications of {topic}?",
        ]
    if depth == "deep":
        questions += [
            f"What are the challenges or limitations of {topic}?",
            f"What is the current state and future of {topic}?",
        ]

    return {
        "sub_questions": questions,
        "search_title": topic.replace(" ", "_"),
        "status": "planned",
        "iteration": 0,
        "additional_summaries": [],
        "sources": [],
        "key_facts": [],
    }


async def fetch_wikipedia(state: ResearchState) -> dict:
    search_title = state.get("search_title") or state["topic"].replace(" ", "_")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Direct title lookup
        try:
            r = await client.get(
                _WIKI_SUMMARY.format(title=search_title),
                headers={"User-Agent": _USER_AGENT},
            )
            if r.status_code == 200:
                data = r.json()
                extract = data.get("extract", "")
                source = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                return {
                    "wikipedia_summary": extract,
                    "sources": [source] if source else [],
                    "status": "fetched",
                    "search_title": data.get("title", search_title).replace(" ", "_"),
                }
        except Exception:
            pass

        # Fallback: OpenSearch to find closest match
        try:
            sr = await client.get(
                _WIKI_SEARCH,
                params={"action": "opensearch", "search": state["topic"], "limit": "3", "format": "json"},
                headers={"User-Agent": _USER_AGENT},
            )
            if sr.status_code == 200:
                results = sr.json()
                titles = results[1] if len(results) > 1 else []
                urls = results[3] if len(results) > 3 else []
                if titles:
                    best = titles[0].replace(" ", "_")
                    r2 = await client.get(
                        _WIKI_SUMMARY.format(title=best),
                        headers={"User-Agent": _USER_AGENT},
                    )
                    if r2.status_code == 200:
                        data = r2.json()
                        return {
                            "wikipedia_summary": data.get("extract", ""),
                            "sources": [urls[0]] if urls else [],
                            "status": "fetched",
                            "search_title": best,
                        }
        except Exception as e:
            return {
                "wikipedia_summary": "",
                "sources": [],
                "status": "error",
                "error": str(e),
            }

    return {"wikipedia_summary": "", "sources": [], "status": "not_found"}


def extract_key_facts(state: ResearchState) -> dict:
    summary = state.get("wikipedia_summary", "")
    sentences = [s.strip() + "." for s in summary.split(".") if len(s.strip()) > 40]
    return {"key_facts": sentences[:8], "status": "extracted"}


def should_fetch_more(state: ResearchState) -> str:
    if state.get("depth") == "deep" and state.get("iteration", 0) < 2 and state.get("status") != "error":
        return "fetch_related"
    return "compile"


async def fetch_related_topics(state: ResearchState) -> dict:
    topic = state["topic"]
    iteration = state.get("iteration", 0)
    additional = list(state.get("additional_summaries", []))
    sources = list(state.get("sources", []))

    queries = [f"History of {topic}", f"Applications of {topic}", f"{topic} examples"]
    query = queries[iteration % len(queries)]

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(
                _WIKI_SUMMARY.format(title=query.replace(" ", "_")),
                headers={"User-Agent": _USER_AGENT},
            )
            if r.status_code == 200:
                data = r.json()
                extract = data.get("extract", "")
                source = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                if extract:
                    additional.append(f"**{query}**: {extract[:500]}")
                if source:
                    sources.append(source)
        except Exception:
            pass

    return {
        "additional_summaries": additional,
        "sources": sources,
        "iteration": iteration + 1,
        "status": "related_fetched",
    }


def compile_report(state: ResearchState) -> dict:
    topic = state["topic"]
    depth = state.get("depth", "standard")
    summary = state.get("wikipedia_summary") or "No data found for this topic."
    key_facts = state.get("key_facts", [])
    additional = state.get("additional_summaries", [])
    sub_questions = state.get("sub_questions", [])
    sources = state.get("sources", [])

    lines = [
        f"# Research Report: {topic}",
        f"*Depth: {depth}  |  Facts extracted: {len(key_facts)}  |  Sources: {len(sources)}*",
        "",
        "## Overview",
        summary[:800] + ("..." if len(summary) > 800 else ""),
        "",
        "## Key Facts",
    ]
    for i, fact in enumerate(key_facts, 1):
        lines.append(f"{i}. {fact}")

    if additional:
        lines += ["", "## Additional Context"]
        for a in additional:
            lines += ["", a[:500]]

    lines += ["", "## Research Questions Addressed"]
    for q in sub_questions:
        lines.append(f"- {q}")

    if sources:
        lines += ["", "## Sources"]
        for s in set(sources):
            lines.append(f"- {s}")

    return {"report": "\n".join(lines), "status": "complete"}


def _build():
    g = StateGraph(ResearchState)
    g.add_node("plan", plan_research)
    g.add_node("fetch_wiki", fetch_wikipedia)
    g.add_node("extract_facts", extract_key_facts)
    g.add_node("fetch_related", fetch_related_topics)
    g.add_node("compile", compile_report)

    g.add_edge(START, "plan")
    g.add_edge("plan", "fetch_wiki")
    g.add_edge("fetch_wiki", "extract_facts")
    g.add_conditional_edges(
        "extract_facts",
        should_fetch_more,
        {"fetch_related": "fetch_related", "compile": "compile"},
    )
    # Loop: fetch_related can route back to itself (capped by iteration counter)
    g.add_conditional_edges(
        "fetch_related",
        should_fetch_more,
        {"fetch_related": "fetch_related", "compile": "compile"},
    )
    g.add_edge("compile", END)
    return g.compile()


compiled = _build()
