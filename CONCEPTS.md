# AI Agent Ecosystem — Deep Concepts & Project Connection

> Reference document for the `MCP_with_Frameworks` learning repo.  
> Covers: Agents · Sub-Agents · Tools · Context Management · MCP · A2A · LangGraph · ADK · Skills & Hooks · Guardrails

---

## Table of Contents

1. [What Are Agents?](#1-what-are-agents)
2. [Sub-Agents](#2-sub-agents)
3. [What Are Tools?](#3-what-are-tools)
4. [Context Management for Agents](#4-context-management-for-agents)
5. [Model Context Protocol (MCP)](#5-model-context-protocol-mcp)
6. [Agent-to-Agent (A2A)](#6-agent-to-agent-a2a)
7. [LangGraph](#7-langgraph)
8. [Google Agent Development Kit (ADK)](#8-google-agent-development-kit-adk)
9. [Agent Skills and Hooks](#9-agent-skills-and-hooks)
10. [Guardrails](#10-guardrails)
11. [Connecting the Dots — How Everything Fits Together](#11-connecting-the-dots)

---

## 1. What Are Agents?

### The Core Concept

An **AI Agent** is an autonomous loop where a language model (LLM) decides *what to do next* rather than simply generating a single response. The classic characterization:

> **Perceive → Reason → Act → Observe → (repeat)**

Compared to a plain chatbot (one-shot: question in, answer out), an agent can:
- Invoke external tools and act on the results
- Maintain memory across multiple steps
- Break complex goals into sub-steps dynamically
- Collaborate with other agents

### Anatomy of an Agent

| Component | What it does |
|-----------|-------------|
| **LLM Core** | Provides reasoning, planning, language understanding |
| **Tools** | Extend capabilities beyond text (search, calculate, call APIs) |
| **Memory / State** | Persists context across steps (short-term) or sessions (long-term) |
| **Orchestrator** | Controls execution flow: when to call tools, when to stop, when to delegate |
| **Planner (optional)** | Decomposes high-level goals into concrete sub-tasks |

### Types of Agent Architectures

**ReAct (Reason + Act)**  
The LLM alternates between *thinking* (chain-of-thought) and *acting* (tool calls). Most common today. The model emits a `Thought:` → `Action:` → `Observation:` loop until it reaches `Final Answer:`.

**Reflection / Critic Agents**  
An agent reviews its own output before finalizing. Your `editor` in `04_multiagent_orchestration` is exactly this — it scores the draft and sends it back to the writer if quality is below threshold.

**Plan-and-Execute**  
First a *planner* generates a multi-step plan; then an *executor* runs each step. Separates reasoning from action. Better for long tasks where the full plan is known upfront.

**Multi-Agent (Hierarchical)**  
A supervisor/orchestrator delegates work to specialized sub-agents. Each agent owns a narrow slice of the problem. Reduces cognitive load per agent, improves reliability.

### Why Multiple Agents vs. One Big Agent?

| Single Monolithic Agent | Multi-Agent |
|------------------------|-------------|
| Simpler to build | Better separation of concerns |
| Context fills up quickly | Each agent has focused context |
| Hard to parallelize | Can run independent agents in parallel |
| One failure = full failure | Isolated failures, retry per agent |
| Hard to debug | Trace exactly which agent produced what |

### Project Connection — Agents

Your project implements three distinct agent architectures:

**Module `01_adk_with_mcp`** — `adk_agents/single_agent/agent.py`  
Single `LlmAgent` (ReAct loop) using MCP tools. Minimal: one agent, one toolset, Gemini as LLM.

**Module `01_adk_with_mcp`** — `adk_agents/multi_agent/agent.py`  
`SequentialAgent` orchestrating three `LlmAgent`s: `researcher → analyst → reporter`. Classic pipeline multi-agent. Each agent writes to `output_key` in shared session state so the next agent can build on it:

```python
# researcher stores its output
researcher = LlmAgent(..., output_key="research_data")

# analyst reads it from session state implicitly through conversation history
analyst = LlmAgent(..., output_key="analysis")

# reporter synthesizes both
reporter = LlmAgent(..., output_key="final_report")

root_agent = SequentialAgent(sub_agents=[researcher, analyst, reporter])
```

**Module `04_multiagent_orchestration`** — `multiagent_workflow.py`  
Supervisor-routed multi-agent with a rewrite loop: `supervisor → researcher → writer → editor → (loop back to writer if score < 7) → publisher`. Demonstrates conditional routing and quality gates.

---

## 2. Sub-Agents

### What Is a Sub-Agent?

A **sub-agent** is an agent that is invoked *by another agent* to handle a delegated piece of work. The calling agent is the **orchestrator** (or parent); the called agent is the **sub-agent** (or child).

Sub-agents allow complex tasks to be decomposed into specialized, reusable units — each sub-agent is an expert in a narrow domain.

```
User task: "Research AI, write a blog post, review it"
     ↓
Orchestrator Agent
     ├── delegates "research AI" → Research Sub-Agent
     ├── delegates "write post" → Writer Sub-Agent
     └── delegates "review quality" → Editor Sub-Agent
```

### Why Sub-Agents?

| Single large agent | Agent with sub-agents |
|-------------------|----------------------|
| One context window for everything | Each sub-agent has focused context |
| Hard to specialize behavior per task | Each sub-agent has its own instructions and tools |
| Single point of failure | Failures are isolated per sub-agent |
| Sequential only | Sub-agents can run in parallel |
| Hard to reuse | Sub-agents are reusable across orchestrators |

### Sub-Agent Communication Patterns

**Sequential pipeline** — sub-agents run in order, output of one feeds next:
```
researcher → analyst → reporter
```
Each agent's output is passed as context to the next. Your module 01 `SequentialAgent` is exactly this.

**Parallel fan-out** — orchestrator spawns multiple sub-agents simultaneously, collects all results:
```
orchestrator → [sub-agent A, sub-agent B, sub-agent C] → merge results
```
Use when sub-tasks are independent. ADK's `ParallelAgent` does this.

**Supervisor / dynamic routing** — orchestrator decides at runtime which sub-agent to call next based on current state:
```
supervisor → (based on stage) → researcher OR writer OR editor OR publisher
```
Your module 04 implements this with LangGraph conditional edges.

**Recursive / hierarchical** — sub-agents can themselves have sub-agents. No depth limit in principle. Example: a `ResearchAgent` that internally delegates to `WebSearchAgent`, `WikiAgent`, and `PDFParserAgent`.

### Sub-Agent Interfaces

Sub-agents need a defined interface — what they accept and what they return:

**ADK (`SequentialAgent`)** — interface is implicit: sub-agents share session state. Each agent reads what it needs from conversation history and writes its result to `output_key`.

**LangGraph** — interface is the `StateGraph` state type. Nodes receive and return dicts conforming to the TypedDict schema. The "interface" is the state contract.

**A2A (cross-service)** — interface is HTTP + JSON. Sub-agents expose an A2A server; orchestrator sends tasks via HTTP POST and receives results.

**MCP-wrapped sub-agents** — a sub-agent can be wrapped as an MCP tool. The orchestrator calls it like any other tool. Internally it might be a full agent running a LangGraph pipeline.

### Sub-Agent State Isolation vs. Sharing

**Shared state** (your module 01, 04): All agents see the same state. Simple but can cause interference if agents write conflicting keys.

**Isolated state** (A2A pattern): Each sub-agent has its own internal state. Only the result is shared with the orchestrator. More robust for complex multi-team systems.

**Scoped state** (ADK `output_key`): Middle ground — each agent writes to its own named key, preventing overwrites:
```python
researcher = LlmAgent(output_key="research_data")   # writes to session["research_data"]
analyst    = LlmAgent(output_key="analysis")         # writes to session["analysis"]
reporter   = LlmAgent(output_key="final_report")     # writes to session["final_report"]
```

### Sub-Agent vs. Tool — Where Is the Line?

| Tool | Sub-Agent |
|------|-----------|
| Deterministic function | LLM-powered, uses judgment |
| No memory or state | Can maintain state across steps |
| Returns structured data | Returns natural language or structured |
| No tool-calling ability | Can call its own tools |
| Stateless | Stateful |

Rule of thumb: if the "sub-component" needs to make decisions, call tools, or handle ambiguity → it's a sub-agent. If it's a pure computation or data retrieval → it's a tool.

### Project Connection — Sub-Agents

**Module 01** — `researcher`, `analyst`, `reporter` are sub-agents inside `SequentialAgent`:
```python
root_agent = SequentialAgent(
    sub_agents=[researcher, analyst, reporter]
)
```
Each is an `LlmAgent` with specialized instructions. `SequentialAgent` is the orchestrator.

**Module 04** — `researcher`, `writer`, `editor`, `publisher` are sub-agents orchestrated by `supervisor`. The `supervisor` function routes to them based on `state["stage"]`. The rewrite loop (editor sends work back to writer) demonstrates dynamic routing between sub-agents.

**Planned A2A evolution** — each module 04 sub-agent becomes an independent service. The `supervisor` becomes an A2A orchestrator that calls them over HTTP.

---

## 3. What Are Tools?


### The Core Concept

Tools are **functions an LLM can decide to call** to interact with the world outside its weights. They are the bridge from language to action.

Without tools, a model can only generate text from its training data. With tools:
- `search("live data")` → current facts
- `calculate("2^32")` → exact arithmetic
- `call_api(...)` → real-world side effects
- `read_file(...)` → access external knowledge

### Tool Call Mechanism

The LLM receives tool *schemas* (name, description, parameters) alongside the user message. When the model decides to use a tool, it emits a structured call — the framework intercepts it, executes the function, and feeds the result back to the model as an observation. The model continues reasoning from there.

```
User: "What's 144 squared plus the stock price of NVDA?"
  ↓
Model: [decides to call calculate and get_stock_price]
  ↓
Tool: calculate("144**2") → {"result": 20736}
Tool: get_stock_price("NVDA") → {"price_usd": 875.40}
  ↓
Model: [sees results, reasons] → "144 squared is 20,736 and NVDA is $875.40, so together: 21,611.40"
```

### Tool Design Principles

**Docstrings are critical.** The LLM decides *whether and how* to call a tool based entirely on its description. Vague descriptions → wrong tool choices.

```python
@mcp.tool()
def calculate(expression: str) -> dict:
    """
    Safely evaluate a mathematical expression.
    Supports: +, -, *, /, **, %, pi, e, sqrt(), log(), sin(), cos()
    Args:
        expression: Math expression string, e.g. "sqrt(144) + 2 ** 8"
    Returns:
        dict with expression and result (or error)
    """
```

The docstring *is* the API contract the LLM sees.

**Return structured data**, not raw strings. The model needs to extract values, not parse prose.

**Fail gracefully** — return `{"status": "error", "error": "..."}` rather than raising. The model can recover from an error result; it can't recover from an exception.

**Atomic tools** — one tool, one responsibility. Don't build a `do_everything(...)` tool.

### Tool Types

| Type | Description | Example in your project |
|------|-------------|------------------------|
| **Data retrieval** | Fetch external information | `get_weather()`, `get_stock_price()` |
| **Computation** | Deterministic calculation | `calculate()` |
| **Time/context** | Environment state | `get_current_datetime()` |
| **Complex pipelines** | Multi-step processing exposed as one tool | `research_topic()`, `review_code()` |
| **Search** | Live information lookup | `web_search()` in module 04 |

### The LangGraph-as-Tool Pattern (Module 03)

Your `03_mcp_with_Langgraph` demonstrates a powerful advanced pattern: **wrapping an entire multi-step LangGraph pipeline as a single MCP tool**.

From the MCP client's perspective, `review_code(code, language)` is just a tool call. Internally, it runs a 6-node StateGraph:

```
parse_ast → analyze_metrics → detect_issues → score_code → generate_suggestions → format_report
```

The caller (Claude Desktop, ADK agent, any MCP client) doesn't know or care about the pipeline. This pattern lets you add arbitrary complexity inside a tool without changing its external interface.

### Project Connection — Tools

Your `01_adk_with_mcp/mcp_server/server.py` defines 4 tools:
- `get_weather` — dict lookup (mock data for learning)
- `calculate` — AST-based safe evaluator (deliberately avoids `eval()` — good security practice)
- `get_stock_price` — mock stock data
- `get_current_datetime` — environment state

Your `03_mcp_with_Langgraph/server.py` defines 5 tools, each a LangGraph pipeline:
- `research_topic` — 5 nodes, optional depth loop
- `review_code` — 6 nodes, Python AST analysis
- `analyze_document` — 6 nodes, NLP pipeline
- `analyze_data` — 5 nodes, statistical analysis
- `plan_task` — 6 nodes, conditional type routing

Your `02_custom_mcp_server/visual.py` defines `visualize_code` — AST → diagram.

---

## 4. Context Management for Agents

### Why Context Management Matters

Every LLM call has a **context window** — a hard limit on how many tokens (input + output) the model can process at once. For GPT-4: ~128K tokens. For Gemini 2.5 Flash: up to 1M tokens. Sounds large, but complex multi-step agent runs can exhaust it fast:

- Tool outputs can be verbose
- Conversation history accumulates
- Each sub-agent's output feeds into the next
- Documents, code, search results all add up

Poor context management → failures, hallucinations, or truncated reasoning.

### Context Management Strategies

#### 1. Summarization / Compression
Instead of keeping full conversation history, periodically summarize it. An agent periodically emits: "Summary so far: [X]" and drops older raw messages.

#### 2. State as Typed Dicts (LangGraph approach)
Rather than storing everything in unstructured conversation history, define a **typed state schema**. Each node reads only what it needs and writes only what it produces. This prevents context explosion.

```python
class BlogState(TypedDict):
    topic: str
    stage: str
    search_results: str     # only populated by researcher
    outline: str            # only populated by researcher
    draft: str              # only populated by writer
    editor_verdict: str     # only populated by editor
    final_post: str         # only populated by publisher
```

Only the relevant keys get injected into each agent's prompt. The writer doesn't need `search_results` directly — it just reads `outline`.

#### 3. output_key (ADK approach)
In ADK's `SequentialAgent`, each `LlmAgent` has an `output_key`. The agent writes its output to session state under that key. Downstream agents can access it via `{key}` in their instructions, rather than receiving the entire previous conversation.

```python
researcher = LlmAgent(output_key="research_data")
# analyst instruction template can reference {research_data}
```

#### 4. Tool Result Filtering
Don't pass raw tool results back verbatim if they're huge. Have the tool (or a processing step) extract only the relevant data before it enters the model's context.

Your `analyze_data` tool returns a structured markdown report — not all the raw records. Your `review_code` tool returns a formatted summary — not the full AST dump.

#### 5. Chunking / RAG (Retrieval-Augmented Generation)
For large documents or codebases: don't put everything in context at once. Embed chunks, retrieve only the top-K relevant ones per query. Not implemented in your project yet, but the `analyze_document` tool is the foundation for this.

#### 6. External Memory (Long-term)
Store facts outside the model (vector DB, key-value store, SQL). Retrieve relevant memories on demand. Example: `InMemorySessionService` in ADK stores session state; a production app would use `DatabaseSessionService`.

#### 7. Message History Reducers
LangGraph's `add_messages` annotation (you use this in module 04):

```python
log: Annotated[list[str], add_messages]
```

`add_messages` is a reducer function — instead of overwriting `log` each turn, it *appends* new messages. This is how LangGraph manages state merging: each node returns a partial dict, and reducers handle how to combine it with existing state.

### Context Flow in Your Multi-Agent Systems

**Module 01 (ADK Sequential):**
```
User prompt
    → researcher: sees full user message + tool results → writes research_data
    → analyst: sees conversation history (includes research_data) → writes analysis  
    → reporter: sees full history (research_data + analysis) → writes final_report
```
Risk: history grows with each step. ADK manages this via session, but for very long pipelines you'd need summarization.

**Module 04 (LangGraph BlogState):**
```
BlogState dict passed between nodes
Each node reads specific keys, writes specific keys
Supervisor only reads/writes: stage, log
Researcher reads: topic — writes: search_results, outline, stage
Writer reads: topic, outline, editor_notes — writes: draft, stage
Editor reads: draft — writes: quality_score, editor_verdict, editor_notes, stage
Publisher reads: topic, draft, quality_score — writes: final_post
```
Clean separation. No agent sees more than it needs.

---

## 5. Model Context Protocol (MCP)

### What Is MCP?

MCP (Model Context Protocol) is an **open standard by Anthropic** (released Nov 2024) that defines a universal interface for connecting AI models to external tools, data sources, and capabilities.

Think of it as **USB-C for AI** — a single plug that works everywhere, instead of every AI tool having its own proprietary connector.

Before MCP:
- Claude had its own tool-calling format
- OpenAI had a different format
- Each application built its own integrations

With MCP:
- One server exposes tools in MCP format
- Any MCP-compatible client (Claude Desktop, ADK, Cursor, Cline) can use it without modification

### MCP Architecture

```
┌─────────────────────────────────────────┐
│            MCP CLIENT                   │
│  (Claude Desktop, ADK Agent, Cursor...) │
└──────────────────┬──────────────────────┘
                   │ MCP Protocol (JSON-RPC 2.0)
     ┌─────────────▼───────────────┐
     │         MCP SERVER          │
     │  (your FastMCP server.py)   │
     │  - tools: list of functions │
     │  - resources: data sources  │
     │  - prompts: templates       │
     └─────────────────────────────┘
```

### MCP Transports

MCP supports three transport mechanisms:

| Transport | When to use | Example |
|-----------|-------------|---------|
| **stdio** | Local, same machine. Client spawns server as subprocess. | ADK with `StdioServerParameters` |
| **SSE** (Server-Sent Events) | Remote server, legacy. HTTP long-poll stream. | Old Claude Desktop remote config |
| **Streamable HTTP** | Modern remote. Stateless HTTP + optional streaming. | Cloud Run deployment |

Your servers support all three:
```python
# server.py — runtime transport selection
transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
if "--http" in sys.argv:
    transport = "http"
elif "--sse" in sys.argv:
    transport = "sse"
```

### MCP Message Types

**Tool discovery:** Client asks server `tools/list` → server returns all tool schemas (name, description, parameters). This happens at startup.

**Tool execution:** Client sends `tools/call` with tool name + arguments → server executes → returns result.

**Resources:** Static or dynamic data sources (files, DB records). Not tools — no execution, just data access.

**Prompts:** Reusable prompt templates the server exposes. Less commonly used.

### FastMCP

FastMCP is the Python library that makes building MCP servers simple. It handles all protocol-level details.

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("my-server")

@mcp.tool()
def my_tool(param: str) -> dict:
    """Tool description that LLM reads."""
    return {"result": "..."}

mcp.run()  # stdio
```

FastMCP auto-generates tool schemas from Python type hints + docstrings. No manual JSON schema writing needed.

### MCP Security Considerations

**DNS Rebinding Protection:** Your servers disable it for Cloud Run:
```python
_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
```
This is needed because Cloud Run's reverse proxy changes the `Host` header. In a non-proxied environment, keep protection enabled.

**Authentication:** MCP itself is protocol-level only. Authentication (OAuth, API keys) is handled at the transport layer (HTTP headers, env vars).

**Tool Safety:** Your `calculate()` tool uses AST parsing instead of `eval()` — this is the right approach. Tools run with the server's process permissions; never use `eval()`/`exec()` on user input.

### Project Connection — MCP

**Module 01** — ADK connects to MCP server via stdio (local subprocess):
```python
MCPToolset(connection_params=StdioConnectionParams(
    server_params=StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER_PATH)]
    )
))
```

**Module 01 (remote agent)** — ADK connects via SSE to Cloud Run:
```python
MCPToolset(connection_params=SseServerParams(url="https://...run.app/sse"))
```

**Module 02** — Standalone MCP server with `visualize_code` tool, deployed to Cloud Run. Demonstrates custom tool development lifecycle.

**Module 03** — LangGraph pipelines exposed as MCP tools. Any MCP client in the world can now call `research_topic("quantum computing")` and get a structured research report — without knowing LangGraph exists behind it.

**What your project proves:** MCP is the glue layer. Build the complex logic anywhere (Python functions, LangGraph graphs, external APIs), wrap it in FastMCP, and it becomes universally accessible.

---

## 6. Agent-to-Agent (A2A)

### What Is A2A?

**A2A (Agent-to-Agent)** is Google's open protocol (released April 2025) for enabling communication and collaboration between AI agents *across different frameworks, vendors, and environments*.

Where MCP solves **Agent ↔ Tool** communication, A2A solves **Agent ↔ Agent** communication.

```
MCP:  Agent → [MCP Protocol] → Tool/Data Source
A2A:  Agent → [A2A Protocol] → Another Agent
```

### Why A2A Exists

In a real enterprise scenario, you might have:
- An ADK agent on GCP
- A LangChain agent on Azure  
- A custom Python agent on-prem
- A third-party vendor agent

Without A2A, these agents can't talk to each other without custom glue code. A2A provides a standardized HTTP/JSON protocol for:

1. **Agent discovery** — each agent exposes an `Agent Card` (JSON) at `/.well-known/agent.json` describing its capabilities
2. **Task delegation** — sending a task to another agent and getting results
3. **Streaming** — receiving real-time progress updates
4. **Multi-turn** — maintaining conversation context across agent boundaries

### A2A Core Concepts

**Agent Card** — JSON descriptor every A2A agent publishes:
```json
{
  "name": "Research Agent",
  "description": "Researches topics using web search and Wikipedia",
  "url": "https://research-agent.company.com",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "research_topic",
      "name": "Research Topic",
      "description": "Deep research on any topic"
    }
  ]
}
```

**Task** — unit of work sent from one agent to another. Has a lifecycle: `submitted → working → completed | failed | canceled`.

**A2A Server** — the agent receiving tasks (implements A2A endpoints).  
**A2A Client** — the agent delegating tasks (sends HTTP requests to another agent's A2A server).

**Orchestrator vs. Remote Agent** — in A2A terminology, the coordinating agent is the *orchestrator*; the agents it delegates to are *remote agents*.

### A2A vs. MCP

| | MCP | A2A |
|--|-----|-----|
| **Purpose** | Agent talks to tools/data | Agent talks to agent |
| **Direction** | Agent is always client | Either agent can initiate |
| **Statefulness** | Tools are stateless functions | Agents maintain their own state |
| **Discovery** | Tools listed via `tools/list` | Agent capabilities via Agent Card |
| **Protocol** | JSON-RPC 2.0 | HTTP/REST + JSON |
| **Author** | Anthropic | Google |

**They are complementary, not competing.** An A2A orchestrator agent might call a remote agent via A2A, and that remote agent uses MCP tools internally.

```
Orchestrator Agent
    │
    ├── A2A → Research Agent (which uses MCP → Wikipedia tool)
    ├── A2A → Code Review Agent (which uses MCP → LangGraph pipeline)
    └── A2A → Data Agent (which uses MCP → SQL tool)
```

### How A2A Relates to Your Project

Your **Module 04** (`04_multiagent_orchestration`) is *intra-process* multi-agent — all agents run in the same Python process, share a `BlogState` TypedDict, and are orchestrated by LangGraph edges.

**A2A would be the next evolution**: breaking those agents into independent services that communicate over HTTP. Each agent would:
1. Run in its own container on Cloud Run
2. Publish an Agent Card
3. Receive tasks via A2A POST
4. Return results to the orchestrator

**Current state of your project vs. A2A readiness:**

| Module 04 today | A2A-ready equivalent |
|----------------|---------------------|
| `supervisor` function in same process | Supervisor agent with A2A client |
| `researcher` function | Research service with A2A server |
| `writer` function | Writer service with A2A server |
| LangGraph edges = routing | HTTP calls between services |
| `BlogState` TypedDict = shared state | Each service has own state; results passed via A2A tasks |

**Concrete next step:** Module 05 (planned Azure) could implement the `supervisor → researcher` delegation via A2A, demonstrating cross-cloud agent communication.

---

## 7. LangGraph

### What Is LangGraph?

LangGraph (by LangChain Inc.) is a framework for building **stateful, multi-step AI workflows** using directed graphs. It models complex agent behavior as a graph where:

- **Nodes** = processing steps (LLM calls, tool executions, Python functions)
- **Edges** = transitions between steps (fixed or conditional)
- **State** = typed dictionary passed through the graph

The core insight: most complex agent behaviors can be expressed as graphs — including loops, branches, parallel paths, and human-in-the-loop checkpoints.

### Core Components

#### StateGraph

The primary building block. You define a typed state, add nodes, connect them with edges, compile to a runnable.

```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class MyState(TypedDict):
    input: str
    result: str

g = StateGraph(MyState)
g.add_node("process", my_function)
g.add_edge(START, "process")
g.add_edge("process", END)
compiled = g.compile()
result = compiled.invoke({"input": "hello"})
```

#### Nodes

Plain Python functions (or async) that receive state and return a partial update dict. LangGraph merges the returned dict into the current state.

```python
def my_node(state: MyState) -> dict:
    # Process state
    return {"result": "processed: " + state["input"]}
    # Only return changed keys — LangGraph merges
```

#### Edges

**Fixed edges** — always go from node A to node B:
```python
g.add_edge("fetch_data", "process_data")
```

**Conditional edges** — routing function decides next node:
```python
def route(state) -> str:
    if state["quality"] >= 7:
        return "publish"
    return "rewrite"

g.add_conditional_edges("editor", route, {"publish": "publisher", "rewrite": "writer"})
```

#### State Reducers

By default, returned values *overwrite* existing state keys. Annotate a key with a reducer to change this behavior:

```python
from langgraph.graph.message import add_messages
from typing import Annotated

class State(TypedDict):
    log: Annotated[list[str], add_messages]  # appends instead of overwrites
```

This is exactly what you use in module 04:
```python
log: Annotated[list[str], add_messages]
```

### Execution Modes

**`.invoke()`** — runs to completion, returns final state. Synchronous.  
**`.ainvoke()`** — async version. Used in module 03 for all 5 tools.  
**`.stream()`** — yields state after each node. Used in module 04:
```python
for step in graph.stream(initial_state, stream_mode="values"):
    final_state = step
```

### Loops in LangGraph

Loops are natural in LangGraph — just add conditional edges that point back to an earlier node. The iteration cap is enforced in the routing function:

```python
# From your research_graph.py
def should_fetch_more(state: ResearchState) -> str:
    if state.get("depth") == "deep" and state.get("iteration", 0) < 2:
        return "fetch_related"
    return "compile"

# fetch_related can route back to itself
g.add_conditional_edges(
    "fetch_related",
    should_fetch_more,
    {"fetch_related": "fetch_related", "compile": "compile"},
)
```

This loop runs at most twice, then exits to `compile`.

**Module 04's editor loop:**
```
writer → supervisor → editor → supervisor → writer (if score < 7, max 2 rewrites)
```
The rewrite cap lives in supervisor's routing dict:
```python
"needs_rewrite": "writing" if state["rewrite_count"] < 2 else "publishing"
```

### LangGraph vs. Plain Python

Why use LangGraph instead of just writing a Python for-loop with functions?

| Plain Python | LangGraph |
|-------------|-----------|
| State scattered across variables | Centralized typed state |
| Loops are ad-hoc | Loops are first-class graph constructs |
| Hard to add checkpointing | Built-in persistence (Checkpointer) |
| No built-in observability | LangSmith integration for tracing |
| Hard to add human-in-the-loop | `interrupt_before`/`interrupt_after` |
| Can't visualize | Graph structure is inspectable/visualizable |

For simple scripts: plain Python is fine. For complex agent workflows that need reliability, observability, or human-in-the-loop: LangGraph pays off.

### Project Connection — LangGraph

**Module 03 — LangGraph as Tool Pipelines**  
5 StateGraph pipelines, each exposed as an MCP tool. The state types are well-defined TypedDicts (e.g., `ResearchState`, `BlogState`). Key patterns:

- `research_graph.py` — conditional loop with iteration counter
- `code_review_graph.py` — linear 6-node pipeline, AST-based
- `task_planner_graph.py` — conditional routing by task type
- All use `ainvoke()` because the MCP tools are async

**Module 04 — LangGraph for Multi-Agent Orchestration**  
`BlogState` with `add_messages` reducer, supervisor routing, editor quality gate with rewrite loop, real LLM (Gemini) at every node, SSE streaming via `api.py`. This is the most sophisticated LangGraph usage in the project — real tool calling (Gemini function-calling + DuckDuckGo), streaming events, quality-gated publishing.

```python
# The graph: supervisor is entry point, all agents route back through it
g.set_entry_point("supervisor")
g.add_conditional_edges("supervisor", route_after_supervisor, {...})
g.add_edge("researcher", "supervisor")
g.add_edge("writer", "supervisor")
g.add_edge("editor", "supervisor")
g.add_edge("publisher", END)
```

---

## 8. Google Agent Development Kit (ADK)

### What Is ADK?

Google ADK (Agent Development Kit) is Google's framework for building production-grade AI agents, particularly designed for:
- Multi-agent systems
- Integration with Google Cloud (Vertex AI, Cloud Run)
- MCP tool consumption
- Structured agent pipelines

ADK provides higher-level abstractions than LangGraph — you describe *what agents are* and their relationships, rather than drawing explicit graphs. The orchestration logic is baked into agent types.

### Core ADK Agent Types

**`LlmAgent`** — the fundamental building block. An LLM-powered agent that can use tools, maintain state, and follow instructions.

```python
from google.adk.agents import LlmAgent

agent = LlmAgent(
    name="my_agent",
    model="gemini-2.5-flash",
    description="What this agent does (used for agent routing)",
    instruction="Detailed behavioral instructions",
    tools=[toolset],
    output_key="my_output"  # writes response to session state
)
```

**`SequentialAgent`** — executes sub-agents in order. Each agent's output is available to subsequent agents through shared session state. Used in your `multi_agent` setup.

**`ParallelAgent`** — executes sub-agents concurrently. Results are merged. Good for independent data gathering tasks.

**`LoopAgent`** — executes a sub-agent repeatedly until a condition is met.

### ADK Session and State

ADK manages agent state through a **session service**:

```python
InMemorySessionService()    # development
DatabaseSessionService()    # production (persistent)
VertexAiSessionService()    # Google Cloud
```

Each session has:
- **`state`** — key-value dict persisted across agent turns in the session
- **`events`** — history of agent actions and tool calls
- **`id`** — unique session identifier

`output_key` on an `LlmAgent` means: "after this agent runs, store its text response in `session.state["output_key"]`." The next agent can then reference it.

### ADK + MCP Integration

ADK has first-class MCP support via `MCPToolset`:

```python
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams, SseServerParams
from mcp import StdioServerParameters

# Local (stdio)
toolset = MCPToolset(connection_params=StdioConnectionParams(
    server_params=StdioServerParameters(
        command="python", args=["server.py"]
    )
))

# Remote (SSE or HTTP)
toolset = MCPToolset(connection_params=SseServerParams(
    url="https://your-server.run.app/sse"
))
```

ADK automatically calls `tools/list` at startup to discover available tools, then makes them available to the `LlmAgent` for its ReAct loop.

### ADK vs. LangGraph

| | ADK | LangGraph |
|--|-----|-----------|
| **Paradigm** | Declarative agent types | Explicit graph construction |
| **Learning curve** | Lower — describe agents, ADK handles flow | Higher — explicitly wire all edges |
| **MCP support** | Native, first-class | Via library adapters |
| **Cloud integration** | Deep Google Cloud integration | Framework-agnostic |
| **Flexibility** | Less — constrained to ADK agent types | More — any Python function as node |
| **Observability** | ADK web UI, Vertex AI | LangSmith |
| **Multi-agent** | SequentialAgent, ParallelAgent, LoopAgent | Explicit graph edges, supervisor pattern |

**When to use ADK:** Building on Google Cloud, want fast setup, need native MCP support, prefer declarative style.

**When to use LangGraph:** Need full control over execution flow, complex conditional logic, framework-agnostic requirements, building pipelines too complex for ADK's pre-built patterns.

**They can coexist** — your module 01 uses ADK agents that call MCP tools implemented with LangGraph (module 03). ADK handles the agent lifecycle; LangGraph handles the complex computation inside each tool.

### ADK CLI

```bash
adk web multi_agent    # serves a web UI at localhost:8080
adk run multi_agent    # runs agent in CLI interactive mode
adk api_server         # serves REST API
```

`adk web` provides a full chat interface with session management, tool call visualization, and state inspection — extremely useful during development.

### Project Connection — ADK

**Module 01** is entirely ADK-based:
- `single_agent/agent.py` — minimal ADK setup: one LlmAgent, one MCPToolset via stdio
- `multi_agent/agent.py` — SequentialAgent with researcher → analyst → reporter, all sharing session state via `output_key`
- `remote_agent/agent.py` — same LlmAgent but connecting to deployed Cloud Run MCP server via SSE
- `main.py` — programmatic runner (bypasses CLI, useful for testing and automation)

The `mcp_server/deploy.sh` deploys the FastMCP server to Cloud Run, enabling the remote agent flow.

---

## 9. Agent Skills and Hooks

### Agent Skills

A **skill** is a named, reusable capability that an agent (or agent framework) can invoke. Skills are higher-level than raw tools — they encode a *behavior pattern* rather than just a function call.

**In ADK:** Skills map loosely to what the agent is configured to do well, described in the `description` and `instruction` fields. The ADK runtime uses `description` to decide which sub-agent to route a task to in multi-agent setups:

```python
researcher = LlmAgent(
    name="researcher",
    description="Gathers raw data using MCP tools based on the user's request.",
    instruction="You are a research agent. Your job is to collect factual data..."
)
```
The `description` is the skill declaration — it tells the orchestrator what this agent knows how to do.

**In A2A:** Skills are first-class objects in the Agent Card:
```json
{
  "skills": [
    {
      "id": "research_topic",
      "name": "Research Topic",
      "description": "Deep research with Wikipedia and web sources",
      "inputModes": ["text"],
      "outputModes": ["text"]
    }
  ]
}
```
An A2A orchestrator reads skills from other agents' Agent Cards to decide delegation targets.

**In Claude Code / Claude Desktop:** Skills are slash commands backed by skill files (`.claude/skills/`). They're invoked with `/skill-name` and execute a predefined prompt + tool sequence. This is exactly the caveman, review, run, etc. skills you see in this session.

### Skill vs. Tool vs. Sub-Agent

| | Tool | Skill | Sub-Agent |
|--|------|-------|-----------|
| **Execution** | Deterministic function | LLM-guided behavior | LLM with own tools + state |
| **Input** | Typed parameters | Natural language prompt | Natural language or structured task |
| **Composition** | Single-step | Multi-step behavior | Full agent lifecycle |
| **Discovery** | `tools/list` (MCP) | Agent description / Agent Card | A2A Agent Card |
| **Statefulness** | None | Ephemeral | Full session state |

### Hooks

**Hooks** are callbacks that fire at specific points in an agent's lifecycle. They allow you to inject observability, validation, transformation, or side effects without modifying the core agent logic.

#### ADK Hooks (Callbacks)

ADK provides callback hooks on agent events:

```python
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse, LlmRequest

def before_model_call(ctx: CallbackContext, req: LlmRequest) -> LlmRequest | None:
    print(f"[HOOK] Agent '{ctx.agent_name}' about to call LLM")
    print(f"  Messages: {len(req.contents)}")
    return None  # None = proceed normally; return LlmResponse to short-circuit

def after_model_call(ctx: CallbackContext, resp: LlmResponse) -> LlmResponse | None:
    print(f"[HOOK] LLM response received: {resp.text[:100]}")
    return None

agent = LlmAgent(
    name="my_agent",
    before_model_callback=before_model_call,
    after_model_callback=after_model_call,
)
```

**Available ADK hooks:**

| Hook | Fires when | Common use |
|------|-----------|------------|
| `before_agent_callback` | Before agent starts processing | Logging, auth check |
| `after_agent_callback` | After agent completes | Post-processing, audit |
| `before_model_callback` | Before LLM API call | Request modification, rate limiting |
| `after_model_callback` | After LLM API call | Response validation, logging |
| `before_tool_callback` | Before tool execution | Input sanitization, audit |
| `after_tool_callback` | After tool execution | Output filtering, caching |

#### LangGraph Hooks (Checkpointers + Streaming)

LangGraph doesn't call them "hooks" but provides equivalent mechanisms:

**Checkpointer** — saves state after every node execution. Enables pause/resume:
```python
from langgraph.checkpoint.memory import MemorySaver
checkpointer = MemorySaver()
compiled = g.compile(checkpointer=checkpointer)
# State is saved after every node; can resume from any point
```

**Streaming** — receive state updates in real time:
```python
for step in graph.stream(state, stream_mode="values"):
    print(f"After node: {step}")
    # Act on intermediate state (e.g., push to SSE endpoint)
```
Your module 04 `api.py` uses streaming to push agent events to the browser via SSE.

**`interrupt_before` / `interrupt_after`** — pause the graph before/after a specific node:
```python
compiled = g.compile(interrupt_before=["publisher"])
# Graph pauses before publisher; human can review/modify state
# Resume with compiled.invoke(None, config=...)
```
This is human-in-the-loop — the hook is the pause point.

#### Claude Code Hooks (Session Hooks)

Claude Code supports hooks via `settings.json` — shell commands that execute on session events:
```json
{
  "hooks": {
    "UserPromptSubmit": [{"command": "echo 'CAVEMAN MODE ACTIVE'"}],
    "PostToolUse": [{"command": "log_tool_call.sh"}]
  }
}
```
This is exactly what drives the caveman mode session you're in — a `UserPromptSubmit` hook injects the caveman instructions into every prompt.

### Hooks Use Cases in Your Project

**Observability:** Add `before_tool_callback` to log every MCP tool call with timing:
```python
def log_tool_call(ctx, tool_call):
    print(f"[TOOL] {tool_call.function_call.name}({tool_call.function_call.args})")
    return None
```

**Guardrails (see next section):** Use `before_model_callback` to screen prompts, or `after_tool_callback` to filter sensitive tool outputs.

**Caching:** `after_tool_callback` can cache expensive tool results (Wikipedia fetch, stock API call) and `before_tool_callback` can return cached results, skipping the actual call.

**Rate limiting:** `before_model_callback` can enforce delays between LLM calls in high-volume pipelines.

### Project Connection — Skills and Hooks

Your project doesn't yet use ADK hooks explicitly — opportunity to add:

1. **`before_tool_callback`** on the MCP toolset in module 01 to log/time every tool call
2. **`after_agent_callback`** on reporter in multi-agent to validate the final report isn't empty
3. **LangGraph checkpointer** in module 03/04 for fault tolerance — if Cloud Run times out mid-pipeline, restart from last checkpoint
4. **Streaming hooks** already partially used in module 04's `api.py` event emission system

---

## 10. Guardrails

### What Are Guardrails?

**Guardrails** are safety and reliability mechanisms that constrain what an agent can do, say, or process. They prevent:
- Harmful outputs (violence, PII leakage, toxic content)
- Security vulnerabilities (prompt injection, jailbreaks)
- Reliability failures (hallucinations, off-topic responses, infinite loops)
- Business policy violations (competitors mentioned, pricing disclosed)

Guardrails operate at multiple levels and points in the agent lifecycle.

### Guardrail Categories

#### 1. Input Guardrails (Pre-LLM)
Screen the user's message before it reaches the model.

```python
def before_model_callback(ctx, req: LlmRequest) -> LlmResponse | None:
    user_text = req.contents[-1].parts[0].text.lower()
    
    # Block prompt injection attempts
    injection_patterns = ["ignore previous instructions", "disregard your system prompt"]
    if any(p in user_text for p in injection_patterns):
        return LlmResponse(text="I can't process that request.")
    
    # Block PII input
    import re
    if re.search(r'\b\d{3}-\d{2}-\d{4}\b', user_text):  # SSN pattern
        return LlmResponse(text="Please don't share sensitive personal information.")
    
    return None  # Proceed normally
```

#### 2. Output Guardrails (Post-LLM)
Validate or modify the model's response before returning it.

```python
def after_model_callback(ctx, resp: LlmResponse) -> LlmResponse | None:
    text = resp.text or ""
    
    # Block competitor mentions (business policy)
    competitors = ["OpenAI", "Anthropic", "Cohere"]
    for competitor in competitors:
        if competitor.lower() in text.lower():
            return LlmResponse(text="[Response filtered per policy]")
    
    # Check for hallucinated citations
    if "https://" in text:
        # Could verify URLs exist
        pass
    
    return None  # Proceed normally
```

#### 3. Tool Guardrails (Pre/Post-Tool)
Control what tools can be called and what data flows in/out.

```python
def before_tool_callback(ctx, tool_call) -> dict | None:
    tool_name = tool_call.function_call.name
    args = tool_call.function_call.args
    
    # Block tool calls not in allowlist
    allowed_tools = {"get_weather", "calculate", "get_current_datetime"}
    if tool_name not in allowed_tools:
        return {"error": f"Tool '{tool_name}' not permitted in this context"}
    
    # Sanitize calculate input
    if tool_name == "calculate":
        expr = args.get("expression", "")
        if len(expr) > 500:
            return {"error": "Expression too long"}
    
    return None  # Allow tool call

def after_tool_callback(ctx, tool_call, tool_response) -> dict | None:
    # Redact sensitive fields from tool output
    if "api_key" in str(tool_response):
        return {"result": "[REDACTED]"}
    return None
```

#### 4. Structural Guardrails (Architecture-Level)
Built into the pipeline design rather than callbacks.

**Loop caps** — prevent infinite agent loops:
```python
# Your module 03 research_graph.py — hard cap at 2 iterations
def should_fetch_more(state: ResearchState) -> str:
    if state.get("depth") == "deep" and state.get("iteration", 0) < 2:
        return "fetch_related"
    return "compile"
```

**Rewrite limits** — your module 04 editor:
```python
"needs_rewrite": "writing" if state["rewrite_count"] < 2 else "publishing"
```
Even if every draft is below quality threshold, the pipeline terminates after 2 rewrites.

**Timeout** — set max execution time per tool or per graph invocation.

**Token budgets** — limit how many tokens a sub-agent can consume before it must return.

#### 5. Prompt-Level Guardrails
Baked into system instructions:

```python
instruction="""You are a research agent. 
IMPORTANT CONSTRAINTS:
- Never reveal personal information about real people
- Always cite sources for factual claims
- If you cannot find reliable data, say so — do not guess
- Do not call tools more than 10 times per request
"""
```

### LangGraph Guardrails

In LangGraph, guardrails are nodes:

```python
def validate_input(state: MyState) -> dict:
    text = state["user_input"]
    if len(text) > 10000:
        return {"error": "Input too long", "status": "rejected"}
    if contains_pii(text):
        return {"error": "PII detected", "status": "rejected"}
    return {"status": "validated"}

def route_after_validation(state) -> str:
    return "process" if state["status"] == "validated" else "error_handler"

g.add_node("validate", validate_input)
g.add_conditional_edges("validate", route_after_validation, 
                         {"process": "process", "error_handler": "error_handler"})
```

A guardrail node sits at the graph entry point. Bad inputs never reach the LLM.

### MCP-Level Guardrails

Your FastMCP server is the tool execution boundary — a natural guardrail point:

**Input validation in tools:**
```python
@mcp.tool()
def calculate(expression: str) -> dict:
    # Guardrail: reject dangerous input
    if len(expression) > 1000:
        return {"error": "Expression too long", "status": "error"}
    if any(kw in expression for kw in ["import", "exec", "eval", "__"]):
        return {"error": "Unsafe expression", "status": "error"}
    # Safe AST evaluation — no eval()
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval_node(tree.body)
        ...
```

Your `calculate` tool already implements this — AST parsing instead of `eval()` is a classic security guardrail.

### The Guardrail Stack in Your Project

```
User Input
    ↓
[Prompt-level guardrails] — agent instruction constraints
    ↓
[Input guardrails] — before_model_callback (not yet added)
    ↓
LLM (Gemini)
    ↓
[Output guardrails] — after_model_callback (not yet added)
    ↓
Tool Decision
    ↓
[Tool input guardrails] — before_tool_callback (not yet added)
    ↓
MCP Tool Execution
    ↓ [Input validation in tool code] ← YOU HAVE THIS (calculate's AST check)
    ↓ [Loop caps in graphs] ← YOU HAVE THIS (iteration < 2)
    ↓ [Rewrite limits] ← YOU HAVE THIS (rewrite_count < 2)
    ↓
[Tool output guardrails] — after_tool_callback (not yet added)
    ↓
Agent Response
```

**What you have today:** Structural guardrails (loop caps, rewrite limits), tool-level input validation (AST parser), safe-by-design tools (no eval, mock data).

**What to add next:**
1. ADK `before_model_callback` to detect prompt injection
2. ADK `before_tool_callback` to validate tool args before MCP call  
3. LangGraph entry-point validation node in module 03 pipelines
4. Response length caps to prevent runaway outputs

### Guardrails vs. Alignment vs. Safety

| Term | Meaning | Example |
|------|---------|---------|
| **Guardrails** | Technical constraints on behavior | Block PII, cap loops, validate inputs |
| **Alignment** | Model's inherent values + RLHF training | Gemini/Claude refusing harmful requests |
| **Safety** | Broader system-level risk management | Access controls, audit logs, rate limits |

Guardrails are what *you* add on top of model alignment. Never rely solely on model alignment for business-critical constraints — always add guardrails.

---

## 11. Connecting the Dots

### The Full Architecture Picture

Here's how all the concepts in your project fit together into a coherent ecosystem:

```
┌────────────────────────────────────────────────────────────┐
│                    CLIENT / USER INTERFACE                  │
│   adk web UI  |  Claude Desktop  |  Module 04 API (SSE)    │
└───────────────────┬────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────┐
│                    AGENT LAYER                              │
│                                                            │
│  ADK (Module 01)              LangGraph (Module 04)        │
│  ┌─────────────┐              ┌──────────────────────┐     │
│  │SequentialAgt│              │   Supervisor Graph    │     │
│  │ researcher  │              │  supervisor → agents  │     │
│  │ analyst     │              │  with quality loops   │     │
│  │ reporter    │              └──────────────────────┘     │
│  └─────────────┘                                           │
└───────────────────┬────────────────────────────────────────┘
                    │ MCP Protocol
                    ▼
┌────────────────────────────────────────────────────────────┐
│                    MCP SERVER LAYER                         │
│                                                            │
│  Module 01 Server          Module 03 Server                │
│  (simple tools)            (LangGraph tools)               │
│  ┌────────────┐            ┌────────────────┐              │
│  │get_weather │            │research_topic  │              │
│  │calculate   │            │review_code     │              │
│  │get_stock   │            │analyze_doc     │              │
│  │get_time    │            │analyze_data    │              │
│  └────────────┘            │plan_task       │              │
│                            └───────┬────────┘              │
│  Module 02 Server                  │ ainvoke()             │
│  (custom tool)             ┌───────▼────────┐              │
│  ┌──────────────┐          │  StateGraph    │              │
│  │visualize_code│          │  Pipelines     │              │
│  └──────────────┘          └────────────────┘              │
└───────────────────┬────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────┐
│                 DEPLOYMENT LAYER (GCP Cloud Run)            │
│   Docker containers  |  HTTPS  |  IAM auth                 │
└────────────────────────────────────────────────────────────┘
```

### Concept Relationships

| Concept | Role in Ecosystem | Where in Your Project |
|---------|------------------|----------------------|
| **Agent** | Autonomous decision-maker | `LlmAgent`, `SequentialAgent` in module 01; nodes in module 04 |
| **Tools** | Functions agents can invoke | `@mcp.tool()` decorated functions in all server files |
| **Context Management** | State across steps | `output_key` (ADK), `TypedDict` state (LangGraph), `add_messages` reducer |
| **MCP** | Standard protocol connecting agents to tools | FastMCP servers in modules 01, 02, 03; MCPToolset in ADK agents |
| **A2A** | Agent-to-agent communication | Not yet implemented — natural next evolution of module 04 |
| **LangGraph** | Graph-based workflow orchestration | Pipelines in module 03; full multi-agent system in module 04 |
| **ADK** | High-level agent framework (Google) | All of module 01; declarative multi-agent pipeline |

### Learning Progression in Your Project

```
Module 01: ADK + MCP basics
    → Learn: agents, tools, MCP stdio/SSE, ADK SequentialAgent, context via output_key

Module 02: Custom MCP server
    → Learn: tool design, FastMCP, Cloud Run deployment, IAM

Module 03: LangGraph as MCP tools
    → Learn: StateGraph, conditional edges, loops, async tools, complex pipelines

Module 04: LangGraph multi-agent orchestration
    → Learn: supervisor pattern, quality gates, rewrite loops, real LLM tool calling, streaming

[Planned] Module 04 → A2A: Break module 04 into separate services communicating via A2A
[Planned] Module 05 → Azure: Deploy MCP server on Azure Container Apps
[Planned] Module 06 → AWS: Deploy MCP server on AWS Lambda
```

### The "MCP is Universal" Insight

The most important architectural insight from your project:

**MCP is the universal interface layer.** 

Once something is wrapped as an MCP server:
- An ADK agent can use it (module 01 consuming module 01/03 servers)
- Claude Desktop can use it directly
- A LangChain agent can use it (planned module 04)
- A future A2A agent can expose it to other agents
- Any MCP-compatible client can use it without knowing the implementation

Your LangGraph pipelines (module 03) are not "LangGraph tools" — they are **MCP tools that happen to be implemented with LangGraph**. This separation of interface from implementation is the key architectural strength of your project.

### What A2A Adds (The Missing Piece)

Currently your agents communicate:
- **Intra-process** (module 01 SequentialAgent, module 04 LangGraph graph)
- **Via MCP** (agent → tool → result)

What's missing: **agent-to-agent delegation across process/network boundaries**.

With A2A, module 04's `supervisor` could HTTP-call a separately deployed `ResearchAgent`, which internally uses its own LangGraph pipeline + MCP tools. The supervisor wouldn't know or care how the research was done — it just sends a task and gets a result. This is the direction the entire industry is moving.

---

*Document generated June 2026. Covers repo state at commit `5f96645` (multiagent orchestration added).*
