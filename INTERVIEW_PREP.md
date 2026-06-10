# Interview Prep — MCP · ADK · LangGraph · ReAct · Agent Internals

> Grounded in your two repos (`MCP_with_Frameworks`, `DeepAgents`) and resume (EvaBot, Wealth Guardian, Invoice Automation).
> Each answer ties to code you actually wrote — speak from your repo, not theory.
> Order: warm-up → MCP → ADK → ReAct/LangGraph → State → Context → Guardrails → Evaluation → Agent Harness → Tool Correctness → rapid-fire.

---

## How to use this in the room
- When asked a concept question, **define it in one line, then point to your code**: "In my repo, module 01 does X via `output_key`…". This signals hands-on, not memorized.
- If you don't know something, say what you'd do to find out + the closest thing you built. Never bluff numbers.
- Anchor everything to **production concerns**: isolation, cost, latency, observability, failure modes. That's what separates senior from mid.

---

## 0. Warm-up / Positioning

**Q: Walk me through your most complex agentic system.**
A: EvaBot — domain-aware Agentic RAG for 5+ departments (Compliance, Finance, HR, IT). React/Next.js front end streaming over WebSockets, FastAPI backend, LangGraph orchestration. A supervisor routes the query to one of 4 modular agents (94% intent-classification accuracy), each with 30+ tools. RAG layer is Azure AI Search hybrid (keyword + semantic) with BGE reranking, metadata filtering, RBAC, and audit logging. Eval via LangSmith + DeepEval gating quality at >90%. Served 5K+ concurrent at 99.5% uptime on Docker/K8s across Azure and GCP Cloud Run. The hard parts were context isolation per user, intent routing accuracy, and keeping hallucination measurable rather than anecdotal.

**Q: Why so many frameworks — when do you reach for which?**
A: They solve different problems. **ADK** when I'm on GCP + Gemini and want declarative multi-agent with native MCP. **LangGraph** when I need explicit cycles, conditional routing, human-in-the-loop, and LangSmith tracing — anything where failures are expensive. **CrewAI** for fast linear role-based pipelines. **MCP** is the tool/data interface; **A2A** is the cross-service agent-to-agent layer. They compose: in my repo an ADK agent calls an MCP tool that's internally a LangGraph pipeline.

---

## 1. MCP (Model Context Protocol)

**Q: What is MCP and what problem does it solve?**
A: Open standard from Anthropic (Nov 2024) — a universal interface connecting LLMs to external tools, data, and prompts. "USB-C for AI." Before MCP every client (Claude, OpenAI, Cursor) had its own tool format and you rebuilt integrations per client. With MCP, one server exposes tools once and any MCP-compatible client uses them unchanged. It runs over JSON-RPC 2.0.

**Q: MCP architecture and primitives?**
A: Client ↔ Server. Server exposes three primitives: **tools** (callable functions with side effects/returns), **resources** (read-only data sources, no execution), **prompts** (reusable templates). Two key RPCs: `tools/list` (discovery at startup — returns name + description + JSON schema) and `tools/call` (execution with args). In my repo `server.py` uses FastMCP, which auto-generates the JSON schema from Python type hints + docstrings, so I never hand-write schemas.

**Q: MCP transports — when do you use each?**
A: Three. **stdio** — local, client spawns server as a subprocess; my ADK single/multi agents use this via `StdioServerParameters`. **SSE** — legacy remote, HTTP long-poll; my remote agent hits a Cloud Run `/sse` endpoint. **Streamable HTTP** — modern remote, stateless HTTP with optional streaming; what I deploy on Cloud Run. My `server.py` picks transport at runtime from `MCP_TRANSPORT` env or `--http`/`--sse` flags.

**Q: How does an ADK agent actually consume your MCP server?**
A: `MCPToolset(connection_params=...)`. At startup ADK calls `tools/list`, gets the schemas, and injects them into the Gemini agent so they're available in the ReAct loop. For local it's `StdioConnectionParams` wrapping `StdioServerParameters(command=sys.executable, args=[server_path])`; for remote it's `SseServerParams(url=".../sse")`. ADK manages the subprocess lifecycle for stdio.

**Q: A real MCP security concern you hit?**
A: DNS rebinding. Cloud Run's reverse proxy rewrites the `Host` header, which trips MCP's default DNS-rebinding protection. I disable it explicitly with `TransportSecuritySettings(enable_dns_rebinding_protection=False)` — but only because there's a trusted proxy in front. In a non-proxied setup I keep it on. Also: MCP itself is protocol-only; auth (OAuth/API keys) lives at the transport layer in headers/env. And tool code runs with the server's process permissions — that's why my `calculate` tool parses an AST instead of `eval()`.

**Q: MCP vs A2A?**
A: MCP = agent → tool/data (agent is always the client, tools are stateless). A2A (Google, Apr 2025) = agent → agent (either side can initiate, agents hold their own state, discovery via Agent Card at `/.well-known/agent.json`). Complementary: an A2A orchestrator delegates a task to a remote agent that internally uses MCP tools. Rule: needs data/function → MCP; needs to delegate to another autonomous agent → A2A.

**Q: How would you scale MCP to 1000+ tools?**
A: Don't send all schemas every call — that bloats context and *degrades* selection accuracy. Tiered: <15 tools static inclusion; 15–40 semantic retrieval (embed descriptions, top-K by cosine); 40+ layered routing (intent classifier → namespace filter → retrieval → re-rank). At extreme scale, active discovery (MCP-Zero pattern) — agent requests tools only when it detects a capability gap; ~98% token reduction vs sending 3k schemas. My repo has 4–5 tools/server so static inclusion is correct today.

---

## 2. ADK (Google Agent Development Kit)

**Q: What is ADK and how is it different from LangGraph?**
A: Google's framework for production agents, GCP/Gemini-native with first-class MCP support. It's **declarative** — you describe *what agents are* and their relationships; orchestration is baked into agent types. LangGraph is **imperative** — you wire every node and edge explicitly. ADK = lower learning curve, faster on GCP; LangGraph = full control, framework-agnostic, best-in-class tracing (LangSmith). They coexist: ADK for the agent lifecycle, LangGraph inside a tool for complex computation.

**Q: ADK agent types?**
A: `LlmAgent` — the atom (LLM + tools + instruction + `output_key`). `SequentialAgent` — runs sub-agents in order, sharing session state. `ParallelAgent` — concurrent fan-out, merges results. `LoopAgent` — repeats a sub-agent until a condition. My module 01 multi-agent is a `SequentialAgent` of researcher → analyst → reporter.

**Q: How do ADK agents pass data between each other?**
A: `output_key`. Each `LlmAgent` writes its text response into `session.state[output_key]` after it runs. Downstream agents read it — either by referencing `{key}` in their instruction template, or implicitly through conversation history. In my pipeline researcher writes `research_data`, analyst writes `analysis`, reporter writes `final_report`. This is **scoped state** — named keys prevent agents from clobbering each other.

**Q: ADK session / state management?**
A: A session service holds `state` (KV dict across turns), `events` (action/tool-call history), and an `id`. Three implementations on an upgrade path: `InMemorySessionService` (dev — lost on restart), `DatabaseSessionService` (persistent), `VertexAiSessionService` (managed GCP). Critical production rule: if Cloud Run runs more than one replica, in-memory state is wrong by definition — requests routed to different replicas lose state, so you must use Database/Vertex. Always generate a fresh `session_id` (UUID) per user per conversation.

**Q: ADK callbacks/hooks — what are they and what did you use them for?**
A: Lifecycle callbacks: `before/after_agent`, `before/after_model`, `before/after_tool`. Each can short-circuit by returning a value instead of `None`. I use them for cross-cutting concerns without touching agent logic: `before_tool_callback` to log/time every tool call and validate args; `before_model_callback` for prompt-injection screening and rate limiting; `after_tool_callback` to redact secrets and cache expensive calls (Wikipedia/stock). They're where I implement guardrails and observability.

**Q: How do you run/inspect an ADK agent?**
A: `adk web <agent>` gives a chat UI with session management, tool-call visualization, and live state inspection — best first-party dev loop. `adk run` for interactive CLI, `adk api_server` for REST. For automation/testing I write a programmatic runner (`main.py`) that bypasses the CLI.

---

## 3. ReAct + LangGraph

**Q: Explain ReAct.**
A: Reason + Act. The LLM interleaves `Thought:` (chain-of-thought) → `Action:` (tool call) → `Observation:` (tool result), looping until `Final Answer:`. It's the dominant single-agent loop. The model decides the next action from reasoning, not a fixed script. My DeepAgents repo's `normal_agent/react_agent.py` is a textbook single ReAct loop — and it demonstrates ReAct's failure mode: it degrades around 5–15 steps because everything lives in one context window with no plan or external memory. That's the motivation for "deep agents."

> Note: if the interviewer means **React.js** (your resume has heavy React/Next.js), pivot: real-time conversation streaming over WebSockets/SSE, optimistic UI for tool-call progress, and rendering agent step traces. But in an agent interview "React" almost always means ReAct — clarify early.

**Q: What is LangGraph and its core components?**
A: A framework for stateful multi-step workflows as a directed graph. **Nodes** = steps (plain Python/async functions that take state, return a partial-update dict). **Edges** = transitions (fixed or conditional). **State** = a typed dict (TypedDict) passed through and merged. You build a `StateGraph`, add nodes, wire edges, `compile()` to a runnable. The insight: loops, branches, parallelism, and human-in-the-loop all express cleanly as graphs.

**Q: Conditional edges and loops — show me.**
A: A routing function returns the name of the next node. In my module 04, after the editor scores the draft, the supervisor routes: `"needs_rewrite": "writing" if rewrite_count < 2 else "publishing"`. So a low-quality draft loops back to the writer, but the count cap guarantees termination after 2 rewrites — the loop is bounded by design. In module 03's research graph, `should_fetch_more` loops `fetch_related` back to itself at most twice before `compile`.

**Q: How does state get merged between nodes? What's a reducer?**
A: By default a returned key **overwrites** state. A reducer changes that. I annotate `log: Annotated[list[str], add_messages]` so each node *appends* to the log instead of replacing it. Reducers are how LangGraph composes partial updates — each node returns only the keys it changed, and the reducer decides merge semantics (overwrite vs append vs custom).

**Q: invoke vs ainvoke vs stream?**
A: `.invoke()` runs to completion synchronously. `.ainvoke()` is async — required for concurrent users because sync `invoke()` blocks the event loop and serializes everyone; my module 03 MCP tools all use `ainvoke()`. `.stream(state, stream_mode="values")` yields state after each node — I use it in module 04 to push agent events to the browser over SSE in `api.py`.

**Q: Why LangGraph over a plain Python loop?**
A: Centralized typed state instead of scattered variables; loops/branches are first-class; built-in checkpointing (pause/resume/restart after failure); LangSmith tracing per node with token + latency; native human-in-the-loop via `interrupt_before/after`; inspectable/visualizable graph. For a 20-line script plain Python wins. For production agents that need reliability and observability, LangGraph pays off.

**Q: Human-in-the-loop in LangGraph?**
A: `compile(interrupt_before=["publisher"])` pauses the graph before a node; state is checkpointed; a human reviews/edits, then you resume with `invoke(None, config=...)`. In Wealth Guardian I gated portfolio recommendations through HITL validation for 100% regulatory compliance; in Invoice Automation, approval before posting.

**Q: The "LangGraph-as-tool" pattern — explain it.**
A: My module 03 wraps an entire multi-node LangGraph pipeline as a single MCP tool. From the client's view `review_code(code, language)` is one tool call; internally it's a 6-node StateGraph (parse_ast → analyze_metrics → detect_issues → score → suggest → format). The caller never knows LangGraph is behind it. This separates **interface from implementation** — I can add arbitrary complexity inside without changing the tool's contract. It's the strongest architectural idea in the repo.

---

## 4. State Management

**Q: How is state managed differently across your stacks?**
A: Three models. **ADK** — session service + `output_key`; scoped named keys per agent. **LangGraph** — a typed `StateGraph` state contract; nodes read/write specific keys, reducers merge. **DeepAgents** — explicit external memory (notes/findings/timeline) stored *outside* the context window so it survives long runs. The progression is: shared conversation history → scoped keys → typed state → externalized memory, each reducing interference and context bloat.

**Q: Shared vs scoped vs isolated state — trade-offs?**
A: **Shared** (all agents see one state) — simple, but agents can clobber keys and interfere. **Scoped** (ADK `output_key`, LangGraph distinct keys) — middle ground, named keys prevent overwrites. **Isolated** (A2A / DeepAgents sub-agents) — each sub-agent has private internal state, only the result is shared; most robust for multi-team systems, no cross-contamination. I pick based on coupling: tight pipeline → scoped; independent services → isolated.

**Q: Per-user state isolation in production — how?**
A: The isolation key differs per stack. MCP Streamable HTTP keys by `mcp-session-id` header — but any dict *I* keep must also be keyed by `ctx.client_id`, never module-global. ADK keys by `session_id` (fresh UUID per user). LangGraph keys by `thread_id` in `config={"configurable": {"thread_id": ...}}` — forgetting this is the #1 cause of context bleed because all invocations then share one checkpoint. Backend by scale: in-memory (dev) → SQLite (single prod) → Redis/Postgres (multi-replica, required behind a load balancer) → Redis Cluster + TTL (high volume).

---

## 5. Context Management / Context Engineering

**Q: Why does context management matter and what strategies do you use?**
A: Every call has a hard token window; multi-step runs exhaust it via verbose tool outputs, accumulating history, and stacked sub-agent outputs. Poor management → truncation, hallucination, cost blowup. Strategies I use: (1) **summarization/compression** of old history; (2) **typed state** so each node sees only what it needs; (3) ADK `output_key` instead of dumping full conversation; (4) **tool-result filtering** — my `analyze_data` returns a structured markdown report, not raw records; (5) **RAG/chunking** for big docs — retrieve top-K, don't stuff everything; (6) **external memory** (vector DB / KV) — DeepAgents stores findings outside context; (7) **history reducers** / sliding window (`add_messages`, or keep last N).

**Q: DeepAgents names 5 context strategies — what are they?**
A: **RAW** (pass everything — baseline, wasteful), **WRITE** (persist to external memory), **SELECT** (retrieve only relevant slices back into context), **COMPRESS** (summarize before injecting), **ISOLATE** (give each sub-agent only its scoped slice, no cross-bleed). The pattern: write findings out, select/compress what's needed per step, isolate per sub-agent. This is what lets a deep agent scale to 100+ steps where a plain ReAct agent collapses at ~10.

**Q: Context bloat under concurrency — the math?**
A: Two compounding costs. Tool-schema bloat: 50 concurrent users × 40 schemas × ~300 tokens = ~600K tokens/sec just for schemas — fix with per-request RAG retrieval of top-5 tools. History accumulation: every turn grows the window — fix with summarization or a sliding-window reducer keeping the last ~20 messages. Plus async (`ainvoke`) so users don't serialize.

**Q: Context window of the models you use?**
A: Gemini 2.5 Flash up to ~1M tokens, GPT-4-class ~128K. Large, but a deep multi-agent run with verbose tool dumps still exhausts it — which is *why* externalized memory beats "just use a bigger window."

---

## 6. Guardrails

**Q: What are guardrails and at what layers do you apply them?**
A: Technical constraints on what an agent can do/say/process — distinct from model alignment (RLHF) and system safety (access control, audit). Never rely on alignment alone for business-critical rules. Layers: **prompt-level** (instruction constraints), **input** (`before_model_callback` — block prompt injection, PII), **output** (`after_model_callback` — block competitor mentions, verify citations), **tool** (`before/after_tool_callback` — allowlist tools, sanitize args, redact outputs), and **structural** (loop caps, rewrite limits, timeouts, token budgets baked into the architecture).

**Q: Which guardrails are actually in your repo today?**
A: Structural and tool-level. (1) Loop cap — research graph `iteration < 2`. (2) Rewrite limit — module 04 `rewrite_count < 2` guarantees termination even if every draft fails quality. (3) Tool input validation — `calculate` rejects oversized input and uses AST parsing instead of `eval`/`exec`, with `import`/`__` keyword blocking — a classic injection guardrail. (4) Fail-soft tools — they return `{"status":"error"}` instead of raising, so the model can recover. What I'd add next: ADK `before_model_callback` for injection detection, `before_tool_callback` arg validation, and a LangGraph entry-point validation node that rejects bad input before it reaches the LLM.

**Q: How would you stop prompt injection?**
A: Defense in depth. Input guardrail screening for known patterns ("ignore previous instructions") and PII regex; treat tool/retrieved content as untrusted data, not instructions; least-privilege tool allowlists per context so an injected instruction can't reach a dangerous tool; output guardrails to catch leakage; and audit logging. No single layer is sufficient — I assume any one will be bypassed.

**Q: Guardrails in LangGraph specifically?**
A: Guardrails are nodes. A `validate_input` node at the entry point sets a status; a conditional edge routes valid input to `process` and bad input to `error_handler`, so the LLM never sees rejected input. Bounded loops are guardrails too.

---

## 7. Evaluation

**Q: How do you evaluate an agentic/RAG system?**
A: Multi-layered, automated, gated. Stack: **LangSmith** (tracing + datasets + LLM-as-judge), **DeepEval** (unit-test-style metrics in CI), **RAGAS** (RAG-specific: faithfulness, answer relevancy, context precision/recall), **Langfuse/Opik** (production observability + scoring). For RAG I separate **retrieval** quality (context precision/recall) from **generation** quality (faithfulness/groundedness, answer relevancy). For agents I add **trajectory eval** — did it pick the right tools in the right order, not just final-answer correctness. In EvaBot I gated every endpoint at >90% success and tracked hallucination rate as a first-class metric; Wealth Guardian tracked recommendation quality and regulatory compliance via Opik.

**Q: Component-level vs end-to-end eval?**
A: Both. Component: intent classifier accuracy (94% in EvaBot), retriever recall@k, tool-selection accuracy, reranker lift. End-to-end: final answer faithfulness + user satisfaction. Component eval localizes failures (is it retrieval or generation?); end-to-end measures what the user feels. CI runs component metrics on every change; production runs sampling-based scoring.

**Q: How do you measure hallucination?**
A: Faithfulness/groundedness — every claim in the answer must be entailed by retrieved context (LLM-as-judge or NLI). RAGAS faithfulness score, citation verification (do cited sources exist and support the claim?), and flag answers with no supporting context. Track the rate over time and alarm on regressions.

**Q: DeepAgents has a Critic that scores 0.0–1.0 — what is that?**
A: An **evaluator agent in the loop** (LLM-as-judge). The critic rates each finding's credibility before the synthesizer merges results — low-credibility findings get down-weighted or dropped. My module 04 editor is the same idea: scores the draft 1–10, gates publishing at ≥7, loops back below that. Inline evaluation as a quality gate, not just offline measurement.

**Q: How do you build an eval dataset?**
A: Seed from real production traffic (LangSmith dataset from traces), add curated edge cases and adversarial prompts, label golden answers/expected tool trajectories. Include **distractor cases** for tool selection. Version it, and grow it from every production failure (failure → regression test).

---

## 8. Agent Harness

**Q: What is an agent harness?**
A: The infrastructure wrapper around the agent loop that provides the runtime guarantees — separate from the agent's reasoning. In my DeepAgents repo, `harness/agent_harness.py` provides: **tool gating** (which tools are available in this context), **iteration limits** (hard cap so the loop can't run forever), **step tracing** (every iteration recorded for observability/debugging), and **context injection** (what gets assembled into each LLM call, via `context_manager.py`). Both the normal and deep agent run inside the *same* harness — the harness is the controlled environment; the agent is the policy.

**Q: Why does the harness matter — isn't the model enough?**
A: The model decides *what* to do; the harness decides *what's allowed, observable, and bounded*. Without it you get runaway loops, no tracing, no tool security, and unisolated context. The harness is where reliability, cost control, and safety live. It's the difference between a demo and production: the LLM is interchangeable, the harness is your engineering. ADK callbacks and LangGraph checkpointers/limits are harness features in those frameworks.

**Q: How does the harness relate to ADK/LangGraph?**
A: They *are* harnesses with different ergonomics. ADK's harness = session service + lifecycle callbacks + tool toolset gating + `adk web` tracing. LangGraph's = checkpointer (persistence/resume) + recursion limit + streaming + LangSmith tracing. DeepAgents builds a custom one to expose the concepts explicitly. Same responsibilities — gating, limits, tracing, context — different packaging.

---

## 9. Tool Correctness — "How do you ensure the agent calls the *right* tool?"
*(This is your most-asked target — answer in layers.)*

**Q: How do you make sure the agent picks the correct tool?**
A: The model has no routing table — it semantic-matches the user message against each tool's name + description. So correctness is mostly **description engineering**, backed by validation. My layered answer:

1. **Description engineering (highest leverage).** Descriptions written for humans fail as LLM retrieval targets. I add explicit `WHEN TO USE`, `DO NOT USE` (anti-examples pointing to the right alternative tool), and `Tags`. Anti-examples move accuracy more than rewording the base description.
2. **Namespacing.** `db_user_read`, `fs_file_read` instead of bare `read` — encode domain in the name so the model resolves namespace first, then tool within it.
3. **Scale-tiered selection.** <15 tools static; 15–40 semantic retrieval (top-K); 40+ layered routing (intent → namespace → retrieval → re-rank). My servers have 4–5 tools, so static is correct.
4. **Structured/native tool-binding.** Never parse free-text tool calls. ADK uses Gemini function-calling (model can only emit schemas it was given); LangGraph uses `.bind_tools([...])`. This eliminates *hallucinated* tools (invented names).
5. **`before_tool_callback` as last-resort validation.** Catch obviously-wrong calls — e.g. `calculate` receiving a non-math string → reject before execution. Narrow fallback, not a substitute for good descriptions.
6. **Distractor testing before deploy.** Build test cases where the correct tool and a similar "distractor" are both present — "weather right now" must hit `get_weather`, "will it rain Friday" must hit `get_forecast`. Benchmarks like MCPAgentBench show models miss these often (~55% vs ~94% human), so I test it explicitly and add every failure as a regression case.
7. **Trajectory evaluation.** In eval, score whether the *sequence* of tool calls was correct, not just the final answer — wrong-tool failures are silent and won't throw exceptions.

**Q: What if the tool runs but returns wrong/garbage data?**
A: Different from selection. (1) Tools return structured `{"status": ...}` so the model can detect errors and recover. (2) `after_tool_callback` validates/filters output (redact secrets, bound size). (3) Schema-validate tool outputs (Pydantic). (4) For factual tools, ground the final answer in the result and run faithfulness eval. (5) HITL gate for high-stakes actions (Wealth Guardian, invoice posting).

---

## 10. Rapid-fire (one-liners)

- **MCP author / year?** Anthropic, Nov 2024. **A2A?** Google, Apr 2025.
- **MCP protocol?** JSON-RPC 2.0. **A2A?** HTTP/REST + JSON, Agent Card at `/.well-known/agent.json`.
- **3 MCP transports?** stdio, SSE, Streamable HTTP.
- **MCP primitives?** tools, resources, prompts.
- **ADK agent types?** LlmAgent, SequentialAgent, ParallelAgent, LoopAgent.
- **ADK state passing?** `output_key` → session state.
- **LangGraph isolation key?** `thread_id`. **ADK?** `session_id`. **MCP HTTP?** `mcp-session-id`.
- **Default LangGraph state merge?** overwrite; reducer (`add_messages`) to append.
- **Why ainvoke?** non-blocking — sync invoke serializes concurrent users.
- **FastMCP schema source?** Python type hints + docstrings (auto-generated).
- **Why AST not eval in calculate?** arbitrary code execution risk; tools run with server permissions.
- **ReAct loop?** Thought → Action → Observation → repeat → Final Answer.
- **ReAct failure mode?** context-window-only memory; degrades ~5–15 steps. Fix: plan + external memory + sub-agents (deep agents).
- **Guardrails vs alignment vs safety?** added technical constraints vs RLHF values vs system-level risk mgmt.
- **RAG eval metrics?** faithfulness, answer relevancy, context precision, context recall (RAGAS).
- **Stop infinite loops?** bounded rewrite/iteration counts + recursion limit + timeout.
- **AutoGen production risk?** 3 architectural rewrites in <2 years — needs migration plan.

---

## 11. Likely curveballs — have an answer ready
- "Your repo uses mock weather/stock data — how would you productionize?" → real APIs behind the same tool interface, add caching via `after_tool_callback`, rate limits, retries/timeouts, error normalization to `{status}`.
- "Cloud Run scales to N replicas — what breaks?" → in-memory ADK session / LangGraph `MemorySaver` → context bleed. Switch to Database/Vertex session and Postgres/Redis checkpointer.
- "How do you debug a multi-agent run that produced a bad answer?" → LangSmith/step trace → find which node/agent, inspect its scoped state and tool calls, replay from checkpoint; trajectory eval to localize.
- "Why not one big agent?" → context fills fast, one failure = total failure, hard to debug/parallelize. Multi-agent = focused context, isolated failures, traceable, parallelizable.
- "MCP or A2A for X?" → external data/function = MCP; delegate to another autonomous agent = A2A.

---

## 12. Infra & Systems Design — Kafka · API Gateway · Rate Limiting
*(Systems-design layer behind your agentic apps — interviewers probe "how does this survive 5K users?")*

### Kafka (event-driven backbone)
> Honesty check: not on your resume. Speak to it only if you actually operated it. Your resume *does* say "event-driven FastAPI" + AWS Step Functions — Kafka is the standard message-bus that fits there. Frame as how you decoupled the pipeline.

**Q: Where did Kafka help in your projects?**
A: In Invoice Automation and EvaBot the heavy work is async — document extraction, RAG indexing, multi-agent steps — and you can't block the HTTP request on them. I used Kafka as the durable event bus to decouple ingestion from processing: the API publishes an event (`invoice.uploaded`, `query.received`) and returns immediately; downstream consumers (extraction agent, embedding/indexer, notifier) process independently. Benefits: (1) **decoupling** — producers don't know consumers; (2) **buffering/backpressure** — traffic spikes queue instead of dropping; (3) **durability + replay** — if a consumer crashes mid-pipeline, it resumes from the last committed offset (no lost invoices); (4) **fan-out** — one event feeds indexer + audit logger + metrics consumer.

**Q: Kafka core concepts you'd name?**
A: **Topic** (named log, e.g. `invoice.events`), **partition** (parallelism + ordering unit — order guaranteed only within a partition), **consumer group** (load-balances partitions across instances; scale consumers up to partition count), **offset** (consumer's position; commit after successful processing for at-least-once), **key** (routes related events to same partition — I key by `invoice_id`/`user_id` so a given entity's events stay ordered).

**Q: Kafka vs a simple queue / why not just call the function?**
A: Synchronous call blocks the request and loses work on crash. SQS-style queue gives decoupling but Kafka adds **replay** (re-read history to rebuild state / reprocess after a bug fix), **multiple independent consumer groups** on the same stream, and high throughput via partitions. For agent pipelines where a step can fail and must resume, the durable replayable log matters.

**Q: Show me concretely how partitions work in your invoice pipeline.**
A: Topic `invoice.events` with, say, **6 partitions**. I produce with `key = invoice_id`. Kafka hashes the key → `partition = hash(invoice_id) % 6`, so **every event for one invoice lands on the same partition** and stays strictly ordered (uploaded → extracted → validated → approved → posted never reorder). Different invoices spread across all 6 partitions → parallelism.

Consumer side: an `extraction-service` consumer **group** with 6 instances → Kafka assigns one partition per instance → 6 invoices process in parallel, but each invoice's steps stay in order. Scaling rule: **max useful consumers = partition count.** 6 partitions caps parallelism at 6; a 7th instance sits idle. So I size partitions for peak throughput up front (over-partition slightly — you can add consumers later but can't easily reduce partitions).

```
                         topic: invoice.events  (6 partitions, key=invoice_id)
producer (API) ──┬─ inv_A → hash%6 → P0 ─┐
                 ├─ inv_B → hash%6 → P3 ─┤   group: extraction-service (6 consumers)
                 ├─ inv_C → hash%6 → P0 ─┤   P0→C1  P1→C2  P2→C3  P3→C4 ...
                 └─ inv_D → hash%6 → P1 ─┘   inv_A & inv_C share P0 → ordered, same consumer
```

Independent **second group** `audit-service` reads the *same* 6 partitions from its own offsets — fan-out, no interference. If a consumer crashes mid-invoice, its partitions **rebalance** to surviving instances, which resume from the last **committed offset** — at-least-once, so my consumer is **idempotent** (dedupe by event id) to avoid double-posting an invoice. Multi-agent angle: each agent-service (extractor, indexer, notifier) is its own consumer group on the relevant topic — Kafka's partition assignment *is* the work distribution.

**Q: Kafka + agents — the real win?**
A: It's the production version of LangGraph's checkpointer at the *service* boundary. Where LangGraph checkpoints state in-process, Kafka persists the inter-service events so a multi-agent system split into separate deployments (the A2A evolution) survives partial failure — each agent-service consumes its topic, commits offset on success, and a crash just re-delivers from the last offset. Exactly-once needs idempotent consumers (dedupe by event id) since Kafka is at-least-once by default.

### API Gateway
**Q: What did API Gateway do in your architecture?**
A: Single entry point in front of the microservices/agents — my resume uses AWS API Gateway (Wealth Guardian, Lambda-backed) and GCP API Gateway (Invoice Automation). It handles cross-cutting edge concerns so the services stay clean: **routing** (path → service), **auth** (JWT/API-key validation, RBAC at the edge), **rate limiting/throttling**, **request validation** (reject malformed before it hits the agent — a cheap guardrail), **TLS termination**, **CORS**, and **observability** (per-route metrics, latency, error rates feeding CloudWatch/Prometheus). It decouples clients from internal topology — I can reshuffle services behind it without breaking the React front end.

**Q: Gateway vs load balancer?**
A: LB = L4/L7 traffic distribution, dumb-ish. Gateway = application-aware: per-route auth, rate limits, transformation, validation, API key management. In practice gateway sits in front, LB distributes behind it across replicas.

**Q: How does it relate to the agent guardrail story?**
A: It's the outermost guardrail layer — schema/size validation and auth happen at the edge before a request ever reaches the LLM, so prompt-injection payloads or oversized inputs get cut cheaply. Defense in depth: gateway → input guardrail → tool allowlist.

### Rate Limiting
**Q: Why and where did you rate-limit?**
A: Two reasons in agentic systems specifically. (1) **Protect downstream cost** — every agent request fans out into multiple LLM + tool calls; an unthrottled client can rack huge token spend and hit provider quotas. (2) **Stability/fairness** — prevent one tenant starving the 5K shared users, and absorb spikes. I applied it at the API Gateway edge (per-API-key/user quotas) and, for LLM calls, inside the agent via `before_model_callback` to pace high-volume pipelines under provider TPM/RPM limits.

**Q: Algorithms — which and why?**
A: **Token bucket** (my default) — allows bursts up to bucket size, refills at a steady rate; matches bursty user traffic. **Sliding window** for strict per-window caps (e.g. provider's requests-per-minute). **Fixed window** is simplest but has the boundary burst problem (2× at the window edge). For distributed multi-replica enforcement, the counter lives in **Redis** (atomic INCR + TTL) so all replicas share one limit — local in-memory limits are wrong behind a load balancer (same bug class as session state).

**Q: What do you return when limited, and how do clients behave?**
A: HTTP **429** with a `Retry-After` header; clients back off with exponential backoff + jitter. For LLM provider 429s, the agent harness retries with backoff rather than failing the whole run. Tiered limits per plan/role, and I alarm on sustained 429 rates (signals a hot tenant or an attack).

**Q: Tie it together — 5K concurrent users, how does the request survive?**
A: API Gateway terminates TLS, authenticates (JWT/RBAC), rate-limits per user (token bucket in Redis), validates the payload → routes to FastAPI → which publishes heavy work to Kafka and streams the agent's progress back over SSE/WebSocket → agents consume their topics, commit offsets on success → LangGraph/ADK with per-`thread_id`/`session_id` isolation → DatabaseSessionService + Redis/Postgres so multi-replica doesn't bleed state → Prometheus/Grafana + LangSmith trace the whole path. Every layer is independently scalable and independently observable.

---

*Speak from the repo. Every concept above maps to a file you wrote — name it. That's your edge.*
