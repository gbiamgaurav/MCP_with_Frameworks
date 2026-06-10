# One-Page Cheat Sheet — Glance Before You Walk In

## Tool Correctness (THE question) — 7 layers
1. **Description engineering** — `WHEN TO USE` / `DO NOT USE` (anti-example → name the right alt tool) / `Tags`. Highest leverage.
2. **Namespacing** — `db_user_read` not `read`. Domain in the name.
3. **Scale tiers** — <15 static · 15–40 semantic retrieval top-K · 40+ intent→namespace→retrieve→re-rank.
4. **Native tool-binding** — ADK Gemini function-calling / LangGraph `.bind_tools()`. Never parse free-text → kills hallucinated tools.
5. **`before_tool_callback`** — last-resort arg validation (calculate gets non-math → reject).
6. **Distractor tests** — correct + similar tool both present; "now" vs "Friday". Benchmarks ~55% vs 94% human.
7. **Trajectory eval** — score tool *sequence*, not just final answer. Wrong-tool = silent failure.
> Wrong *data* (not selection): structured `{status}` returns · `after_tool_callback` filter/redact · Pydantic validate · faithfulness eval · HITL gate.

## MCP
- Anthropic, Nov 2024 · JSON-RPC 2.0 · "USB-C for AI"
- Primitives: **tools** (exec) · **resources** (read-only data) · **prompts** (templates)
- RPCs: `tools/list` (discovery) · `tools/call` (exec)
- Transports: **stdio** (local subprocess) · **SSE** (legacy remote) · **Streamable HTTP** (modern remote/Cloud Run)
- FastMCP → schema auto-gen from type hints + docstrings
- Security: DNS-rebinding off *only* behind trusted proxy · auth at transport layer · AST not `eval()`

## A2A
- Google, Apr 2025 · HTTP/REST+JSON · Agent Card `/.well-known/agent.json`
- Rule: data/function → **MCP** · delegate to autonomous agent → **A2A**

## ADK
- GCP/Gemini-native · declarative · first-class MCP (`MCPToolset`)
- Types: **LlmAgent** · **SequentialAgent** · **ParallelAgent** · **LoopAgent**
- State: **`output_key`** → `session.state` (scoped, no clobber)
- Sessions: InMemory(dev) → Database(prod) → VertexAi(managed). Multi-replica → never in-memory.
- Callbacks: before/after × agent/model/tool — guardrails + observability. Return value short-circuits.
- `adk web` (UI+trace) · `adk run` (CLI) · `adk api_server`

## LangGraph
- Nodes (fn: state→partial dict) · Edges (fixed/conditional) · State (TypedDict)
- Conditional edge = routing fn returns next-node name
- **Reducer**: default overwrite; `Annotated[list, add_messages]` appends
- `invoke` sync · **`ainvoke` async (concurrency!)** · `stream(stream_mode="values")` (SSE)
- HITL: `interrupt_before/after` + checkpointer resume
- Isolation: **`thread_id`** in config — missing = context bleed (#1 bug)
- LangGraph-as-MCP-tool = interface ≠ implementation (your module 03)

## ReAct
- Thought → Action → Observation → loop → Final Answer
- Fails ~5–15 steps (context-only memory). Fix: plan + external memory + sub-agents = **deep agent** (100+ steps)
- ("React" in agent interview = ReAct. Clarify if unsure.)

## State Isolation Keys
| Stack | Key | Bleed if missing |
|---|---|---|
| MCP HTTP | `mcp-session-id` | A's results in B |
| ADK | `session_id` (UUID/user) | shared session |
| LangGraph | `thread_id` | one checkpoint for all |
> Backend: in-mem(dev) → SQLite(1 prod) → Redis/Postgres(multi-replica REQUIRED) → +TTL(scale)

## Context Engineering (DeepAgents 5)
**RAW** (all, wasteful) · **WRITE** (persist external) · **SELECT** (retrieve relevant) · **COMPRESS** (summarize) · **ISOLATE** (per sub-agent slice)
> Bloat math: 50 users × 40 schemas × 300 tok = 600K tok/s. Fix: RAG top-5 tools + sliding-window history.

## Guardrails (layers)
prompt-level · input (`before_model`: injection/PII) · output (`after_model`: leakage) · tool (`before/after_tool`: allowlist/redact) · **structural** (loop cap, rewrite cap, timeout, token budget)
> Have today: loop cap (iter<2) · rewrite cap (<2) · AST calculate · fail-soft `{status:error}`
> Guardrails(added) ≠ alignment(RLHF) ≠ safety(access/audit). Never trust alignment alone.

## Evaluation
- Tools: **LangSmith** (trace+judge) · **DeepEval** (CI) · **RAGAS** (faithfulness/answer-rel/context prec+recall) · **Langfuse/Opik** (prod)
- Split: retrieval (precision/recall) vs generation (faithfulness/groundedness)
- Agent: **trajectory eval** (right tools right order) + final-answer
- Hallucination = faithfulness: every claim entailed by context
- Critic/editor = LLM-as-judge **inline quality gate** (DeepAgents 0–1 credibility · module 04 editor ≥7)
- Dataset: prod traces + edge/adversarial + distractors; every failure → regression case

## Agent Harness (DeepAgents)
Wrapper around the loop: **tool gating · iteration limits · step tracing · context injection**
> Model = policy (what to do). Harness = guarantees (what's allowed/bounded/observable). ADK callbacks + LangGraph checkpointer/recursion-limit ARE harness features.

## Your Projects (own the numbers)
- **EvaBot** — Agentic RAG, 4 agents (Compliance/Finance/HR/IT), 30+ tools, 94% intent, Azure AI Search hybrid + BGE rerank, RBAC, >90% eval gate, 5K users, 99.5%
- **Wealth Guardian** — LangGraph, HITL 100% compliance, Opik eval, <500ms, AWS Step Functions
- **Invoice Automation** — ADK+LangGraph, HITL approval, Azure Doc Intelligence, 60% time cut (3d→2h)

## Infra — Kafka · API Gateway · Rate Limiting
**Kafka** (event bus, decouple ingest from processing — Invoice/EvaBot async):
- topic · partition (parallelism+order) · consumer group (scale≤partitions) · offset (commit=at-least-once) · key (entity→same partition, ordering)
- Win: decouple · buffer/backpressure · **durable replay** (resume from offset on crash) · fan-out
- **Partitions (worked ex):** `invoice.events`, 6 partitions, key=`invoice_id` → `hash%6` → same invoice→same partition (ordered), diff invoices spread (parallel). Group of 6 consumers → 1 partition each → 6 parallel, steps ordered. **max consumers = partitions** (7th idle; over-partition up front). 2nd group (audit) reads same partitions own offsets = fan-out. Crash → rebalance → resume committed offset → idempotent (dedupe event id). Each agent-service = own group.
- = LangGraph checkpointer at *service* boundary (A2A evolution). Exactly-once → idempotent consumer (dedupe by event id)
> Honesty: not on resume. Own only if you ran it. Resume = "event-driven FastAPI" + Step Functions.

**API Gateway** (AWS=Wealth Guardian/Lambda · GCP=Invoice):
- single entry: routing · auth(JWT/RBAC) · rate limit · req validation · TLS · CORS · per-route metrics
- = outermost guardrail (validate/auth before LLM). vs LB: app-aware not just L4/L7 distribution

**Rate Limiting** (why: LLM cost fan-out + fairness/stability):
- **token bucket** (bursty, default) · sliding window (strict per-window) · fixed window (boundary-burst bug)
- multi-replica → **Redis** atomic INCR+TTL (local in-mem = wrong, same bug as session state)
- edge (per-key) + `before_model_callback` (LLM TPM/RPM). Return **429 + Retry-After** → client backoff+jitter
> 5K-user path: GW(TLS/auth/limit/validate) → FastAPI → Kafka(heavy async)+SSE(stream) → agents(commit offset) → thread_id/session_id isolate → DB session + Redis/Postgres → Prometheus/Grafana/LangSmith

## Framework pick (one-liner)
GCP+Gemini → **ADK** · cycles/HITL/trace → **LangGraph** · fast linear roles → **CrewAI** · research/debate → **AutoGen** (3 rewrites risk!) · cross-service agents → **A2A**
