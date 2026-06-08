"""
FastAPI endpoint for Multi-Agent Orchestration with LangGraph + Gemini
======================================================================

Endpoints:
  POST /run          -- run workflow, wait for full result
  GET  /stream?topic -- stream every agent event as Server-Sent Events (SSE)
  GET  /search?q     -- direct web-search test
  GET  /health

Run with:
  uvicorn api:app --reload
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from multiagent_workflow import BlogState, build_graph, _web_search, _event_hook

app = FastAPI(title="Multi-Agent Orchestration API", version="1.0.0")


# ── shared helpers ────────────────────────────────────────────────────────────

def _make_initial_state(topic: str) -> BlogState:
    return {
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


def _extract_log(final_state: dict) -> list[str]:
    return [
        msg.content if hasattr(msg, "content") else str(msg)
        for msg in final_state["log"]
    ]


# ── request / response models ─────────────────────────────────────────────────

class TopicRequest(BaseModel):
    topic: str


class WorkflowResponse(BaseModel):
    final_post: str
    search_results: str
    log: list[str]
    state: dict[str, Any]


# ── POST /run  (blocking, returns full result) ────────────────────────────────

@app.post("/run", response_model=WorkflowResponse)
async def run_workflow(request: TopicRequest):
    if not request.topic.strip():
        raise HTTPException(status_code=400, detail="Topic cannot be empty")
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set")

    graph = build_graph()
    final_state = None
    try:
        for step in graph.stream(_make_initial_state(request.topic), stream_mode="values"):
            final_state = step
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow failed: {e}") from e

    if final_state is None:
        raise HTTPException(status_code=500, detail="No final state produced")

    log_strings = _extract_log(final_state)
    return WorkflowResponse(
        final_post=final_state["final_post"],
        search_results=final_state.get("search_results", ""),
        log=log_strings,
        state={**final_state, "log": log_strings},
    )


# ── GET /stream  (SSE — one event per agent action) ───────────────────────────

@app.get("/stream")
async def stream_workflow(topic: str):
    """
    Stream the workflow as Server-Sent Events so you can watch every step live.

    Each SSE event is a JSON object with a "type" field:
      agent_start     -- an agent begins work
      tool_call       -- Gemini decides to call web_search
      tool_result     -- web_search result preview
      agent_done      -- an agent finishes
      supervisor_route-- supervisor picks the next agent
      workflow_done   -- final result (contains final_post)
      error           -- something went wrong

    Test with:
      curl -N "http://localhost:8000/stream?topic=quantum+computing"
    """
    if not topic.strip():
        raise HTTPException(status_code=400, detail="topic cannot be empty")
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set")

    # asyncio queue bridges the sync graph thread -> async generator
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def hook(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def generator() -> AsyncGenerator[str, None]:
        def _run_sync():
            token = _event_hook.set(hook)
            try:
                graph = build_graph()
                final_state = None
                for step in graph.stream(_make_initial_state(topic), stream_mode="values"):
                    final_state = step
                # signal completion
                if final_state:
                    log_strings = _extract_log(final_state)
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {
                            "type": "workflow_done",
                            "final_post": final_state["final_post"],
                            "search_results": final_state.get("search_results", ""),
                            "log": log_strings,
                        },
                    )
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "message": str(exc)}
                )
            finally:
                _event_hook.reset(token)
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        asyncio.get_event_loop().run_in_executor(None, _run_sync)

        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


# ── GET /search  (quick search test) ─────────────────────────────────────────

@app.get("/search")
async def search(q: str, max_results: int = 5):
    if not q.strip():
        raise HTTPException(status_code=400, detail="'q' cannot be empty")
    results = _web_search(q, max_results=max_results)
    return {"query": q, "results": results}


# ── GET /monitor  (live browser UI) ──────────────────────────────────────────

@app.get("/monitor", response_class=HTMLResponse)
async def monitor():
    """Open this in your browser to watch the workflow live."""
    html = (Path(__file__).parent / "monitor.html").read_text()
    return HTMLResponse(content=html)


# ── GET /health ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "Healthy", "service": "multi-agent-orchestration"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
