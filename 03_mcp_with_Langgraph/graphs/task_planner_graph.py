"""
Task Planner Pipeline — LangGraph StateGraph
Nodes: classify → define_phases → generate_tasks → estimate_timeline → identify_risks → finalize
Conditional routing: classify_goal routes to type-specific phase templates.
Supports four goal types: project, learning, problem_solving, research.
"""

from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, START, END

# ── Templates ──────────────────────────────────────────────────────────────────

_TEMPLATES = {
    "project": {
        "phases": ["Initiation", "Planning", "Execution", "Monitoring", "Closure"],
        "deliverables": [
            "Project charter & stakeholder list",
            "Work breakdown structure & schedule",
            "Core product/deliverable",
            "Progress reports & risk log",
            "Final deliverable & lessons learned",
        ],
        "phase_tasks": {
            "Initiation": [
                "Define project scope and objectives",
                "Identify all stakeholders",
                "Gather and document requirements",
                "Assess feasibility and constraints",
                "Create project charter",
            ],
            "Planning": [
                "Break down work into tasks (WBS)",
                "Assign responsibilities and ownership",
                "Set milestones and deadlines",
                "Estimate effort and resources",
                "Build risk register",
            ],
            "Execution": [
                "Implement core features or deliverables",
                "Hold regular sync meetings",
                "Document progress and decisions",
                "Manage dependencies and blockers",
                "Conduct iterative reviews",
            ],
            "Monitoring": [
                "Track KPIs and progress metrics",
                "Run weekly status reviews",
                "Adjust plan in response to changes",
                "Escalate blockers promptly",
                "Update risk register",
            ],
            "Closure": [
                "Conduct final review and sign-off",
                "Document lessons learned",
                "Archive all deliverables",
                "Communicate completion to stakeholders",
                "Celebrate team success",
            ],
        },
        "risks": [
            ("Scope Creep", "High", "Define requirements upfront; use formal change control for additions."),
            ("Resource Constraints", "Medium", "Identify resource needs early; maintain a skills inventory."),
            ("Technical Complexity", "High", "Prototype risky components first; time-box spikes."),
            ("Timeline Slippage", "Medium", "Build 20% buffer into estimates; monitor velocity weekly."),
        ],
    },
    "learning": {
        "phases": ["Foundation", "Core Concepts", "Practice", "Deep Dive", "Application"],
        "deliverables": [
            "Learning objectives & resource list",
            "Study notes & concept map",
            "Completed exercises & mini-projects",
            "Advanced topic notes & experiments",
            "Capstone project & portfolio entry",
        ],
        "phase_tasks": {
            "Foundation": [
                "Define clear, measurable learning objectives",
                "Curate books, courses, and documentation",
                "Set up a study schedule (time-blocked)",
                "Configure local development/study environment",
                "Survey the domain at a high level",
            ],
            "Core Concepts": [
                "Work through primary learning resource",
                "Take structured notes (Zettelkasten or similar)",
                "Build a concept map or mind map",
                "Do end-of-chapter exercises",
                "Quiz yourself on each concept",
            ],
            "Practice": [
                "Solve practice problems (LeetCode, HackerRank, exercises)",
                "Build at least 3 small focused projects",
                "Submit work for peer or mentor feedback",
                "Identify and fill knowledge gaps",
                "Track progress against objectives",
            ],
            "Deep Dive": [
                "Read official documentation and papers",
                "Study edge cases and advanced patterns",
                "Experiment with non-obvious configurations",
                "Engage with community (forums, Discord, meetups)",
                "Write about what you've learned (blog, notes)",
            ],
            "Application": [
                "Define and build a capstone project",
                "Integrate multiple concepts from earlier phases",
                "Seek code/work review from experienced practitioner",
                "Publish or present the project",
                "Reflect on learning and plan the next growth area",
            ],
        },
        "risks": [
            ("Knowledge Gaps", "High", "Run a pre-assessment to identify gaps before diving in."),
            ("Information Overload", "Medium", "Limit yourself to one primary resource at a time; use spaced repetition."),
            ("Lack of Practice", "High", "Schedule dedicated coding/exercise sessions—reading alone is insufficient."),
            ("No Feedback Loop", "Medium", "Join a study group, find a mentor, or use automated test suites."),
        ],
    },
    "problem_solving": {
        "phases": ["Problem Definition", "Root Cause Analysis", "Solution Design", "Implementation", "Validation"],
        "deliverables": [
            "Problem statement & impact assessment",
            "Root cause report",
            "Solution design document",
            "Working solution with tests",
            "Validation report & post-mortem",
        ],
        "phase_tasks": {
            "Problem Definition": [
                "Write a clear, one-paragraph problem statement",
                "Quantify the impact (users affected, revenue, time)",
                "List known symptoms vs. root causes",
                "Define what 'solved' looks like (acceptance criteria)",
                "Get stakeholder alignment on the definition",
            ],
            "Root Cause Analysis": [
                "Collect logs, metrics, and error traces",
                "Apply 5-Whys or fishbone (Ishikawa) analysis",
                "Form hypotheses ranked by probability",
                "Design experiments to test each hypothesis",
                "Confirm root cause with data",
            ],
            "Solution Design": [
                "Brainstorm at least 3 candidate solutions",
                "Evaluate trade-offs (cost, risk, effort, impact)",
                "Choose the best-fit solution",
                "Document the design with diagrams if needed",
                "Get design reviewed by a second engineer",
            ],
            "Implementation": [
                "Set up feature branch / sandbox environment",
                "Implement the fix or solution",
                "Write unit and integration tests",
                "Conduct code or peer review",
                "Deploy to staging environment",
            ],
            "Validation": [
                "Run full test suite",
                "Verify the original symptoms are resolved",
                "Monitor production for regressions (24–72 h)",
                "Document the solution and learnings",
                "Write post-mortem or incident report",
            ],
        },
        "risks": [
            ("Wrong Root Cause", "High", "Validate hypotheses with data before implementing; avoid assumption-driven fixes."),
            ("Incomplete Requirements", "Medium", "Run a stakeholder discovery session; document acceptance criteria explicitly."),
            ("Implementation Bugs", "High", "Write tests first (TDD) and require code review before merge."),
            ("Regression Issues", "Medium", "Maintain a regression test suite; monitor after every deployment."),
        ],
    },
    "research": {
        "phases": ["Literature Review", "Hypothesis Formation", "Data Collection", "Analysis", "Synthesis"],
        "deliverables": [
            "Annotated bibliography",
            "Research design & hypotheses document",
            "Raw dataset with collection log",
            "Analysis report with visualisations",
            "Final paper / summary report",
        ],
        "phase_tasks": {
            "Literature Review": [
                "Search academic databases (Google Scholar, PubMed, arXiv)",
                "Apply inclusion/exclusion criteria to shortlist papers",
                "Read and annotate shortlisted papers",
                "Identify themes, consensus, and gaps",
                "Write a structured literature review summary",
            ],
            "Hypothesis Formation": [
                "Identify the core research question(s)",
                "Formulate testable hypotheses (H0, H1)",
                "Choose appropriate research methodology",
                "Define variables and measurement approach",
                "Get methodology reviewed by a peer",
            ],
            "Data Collection": [
                "Set up data collection instruments (surveys, scrapers, APIs)",
                "Collect primary data",
                "Gather secondary data from trusted sources",
                "Validate data quality and completeness",
                "Store data securely with provenance log",
            ],
            "Analysis": [
                "Clean and preprocess the dataset",
                "Run statistical or qualitative analysis",
                "Produce visualisations of key findings",
                "Interpret results in the context of hypotheses",
                "Have results peer-reviewed for analysis errors",
            ],
            "Synthesis": [
                "Write discussion section connecting results to literature",
                "Draw conclusions and state limitations",
                "Outline directions for future research",
                "Write abstract and executive summary",
                "Finalise, format, and submit/publish",
            ],
        },
        "risks": [
            ("Data Quality Issues", "High", "Validate data at collection point; cross-check with multiple sources."),
            ("Confirmation Bias", "High", "Pre-register hypotheses; use blind analysis where possible."),
            ("Limited Sources", "Medium", "Include grey literature, pre-prints, and non-English sources where appropriate."),
            ("Analysis Errors", "Medium", "Have a second analyst independently verify key computations."),
        ],
    },
}

_KEYWORDS = {
    "learning": {"learn", "study", "understand", "master", "course", "skill", "tutorial", "practice", "training"},
    "research": {"research", "investigate", "analyze", "analyse", "survey", "review", "literature", "hypothesis"},
    "problem_solving": {"fix", "solve", "debug", "resolve", "troubleshoot", "problem", "issue", "bug", "incident"},
}


class TaskPlanState(TypedDict):
    goal: str
    task_type: str
    classified_type: str
    phases: List[dict]
    all_tasks: List[dict]
    timeline: dict
    risks: List[dict]
    success_criteria: List[str]
    final_plan: str


def classify_goal(state: TaskPlanState) -> dict:
    task_type = state.get("task_type", "auto").lower()
    if task_type in _TEMPLATES:
        return {"classified_type": task_type}

    goal_lower = state["goal"].lower()
    for type_name, keywords in _KEYWORDS.items():
        if any(kw in goal_lower for kw in keywords):
            return {"classified_type": type_name}

    return {"classified_type": "project"}


def define_phases(state: TaskPlanState) -> dict:
    t = _TEMPLATES[state["classified_type"]]
    goal = state["goal"]
    complexity = min(3, len(goal.split()) // 8 + 1)  # 1–3 complexity multiplier

    phases: List[dict] = []
    for i, (name, deliverable) in enumerate(zip(t["phases"], t["deliverables"])):
        base_days = (3 + i) * complexity
        phases.append({
            "number": i + 1,
            "name": name,
            "deliverable": deliverable,
            "estimated_days": base_days,
            "depends_on": [f"Phase {i}"] if i > 0 else [],
        })

    return {"phases": phases}


def generate_tasks(state: TaskPlanState) -> dict:
    t = _TEMPLATES[state["classified_type"]]
    phases = state["phases"]
    all_tasks: List[dict] = []
    task_num = 1

    for phase in phases:
        phase_task_names = t["phase_tasks"].get(phase["name"], [f"Complete {phase['name']} work"])
        for name in phase_task_names:
            priority = "high" if phase["number"] <= 2 else "medium" if phase["number"] <= 4 else "low"
            effort_h = 2 + (task_num % 5)  # 2–6 hours per task
            all_tasks.append({
                "id": f"T{task_num:03d}",
                "phase": phase["name"],
                "name": name,
                "priority": priority,
                "effort_hours": effort_h,
                "status": "pending",
            })
            task_num += 1

    return {"all_tasks": all_tasks}


def estimate_timeline(state: TaskPlanState) -> dict:
    phases = state["phases"]
    all_tasks = state["all_tasks"]

    total_days = sum(p["estimated_days"] for p in phases)
    total_hours = sum(t["effort_hours"] for t in all_tasks)
    daily_hrs = max(2, round(total_hours / max(total_days, 1)))

    milestones = []
    cumulative = 0
    for phase in phases:
        cumulative += phase["estimated_days"]
        milestones.append({
            "name": f"✓ {phase['name']} complete",
            "day": cumulative,
            "deliverable": phase["deliverable"],
        })

    return {
        "timeline": {
            "total_days": total_days,
            "total_hours": total_hours,
            "daily_hours_recommended": daily_hrs,
            "milestones": milestones,
        }
    }


def identify_risks(state: TaskPlanState) -> dict:
    t = _TEMPLATES[state["classified_type"]]
    goal = state["goal"]
    risks: List[dict] = []

    for risk_name, severity, mitigation in t["risks"]:
        risks.append({
            "risk": risk_name,
            "severity": severity,
            "probability": "Medium",
            "mitigation": mitigation,
        })

    if len(goal.split()) > 25:
        risks.append({
            "risk": "Goal Ambiguity",
            "severity": "High",
            "probability": "Medium",
            "mitigation": "Simplify and narrow the goal; break into two or more separate sub-goals.",
        })

    return {"risks": risks}


def finalize_plan(state: TaskPlanState) -> dict:
    goal = state["goal"]
    classified_type = state["classified_type"]
    phases = state["phases"]
    all_tasks = state["all_tasks"]
    timeline = state["timeline"]
    risks = state["risks"]

    success_criteria = [
        f"All {len(phases)} phases completed in order",
        f"All {len(all_tasks)} tasks marked done",
        "Key deliverable produced for every phase",
        "No high-severity risks went unmitigated",
        f"Delivered within {timeline['total_days']} days at {timeline['daily_hours_recommended']} h/day",
    ]

    type_label = classified_type.replace("_", " ").title()
    lines = [
        f"# Task Plan",
        f"**Goal:** {goal}",
        f"**Type:** {type_label}  |  **Phases:** {len(phases)}  |  **Tasks:** {len(all_tasks)}  |  **Est. Days:** {timeline['total_days']}",
        "",
        "---",
        "",
        "## Phases & Tasks",
    ]

    for phase in phases:
        dep_str = f" *(requires: {', '.join(phase['depends_on'])})*" if phase["depends_on"] else ""
        lines += [
            "",
            f"### Phase {phase['number']}: {phase['name']}  (~{phase['estimated_days']} days){dep_str}",
            f"**Deliverable:** {phase['deliverable']}",
            "",
        ]
        phase_tasks = [t for t in all_tasks if t["phase"] == phase["name"]]
        for task in phase_tasks:
            badge = "🔴" if task["priority"] == "high" else "🟡" if task["priority"] == "medium" else "🟢"
            lines.append(f"- {badge} `{task['id']}` {task['name']} *(~{task['effort_hours']}h)*")

    lines += ["", "---", "", "## Milestones"]
    for m in timeline["milestones"]:
        lines.append(f"- **Day {m['day']}** — {m['name']} → *{m['deliverable']}*")

    lines += [
        "",
        "---",
        "",
        "## Effort Summary",
        f"- **Total days:** {timeline['total_days']}",
        f"- **Total effort:** ~{timeline['total_hours']} hours",
        f"- **Recommended pace:** {timeline['daily_hours_recommended']} hours/day",
        "",
        "---",
        "",
        "## Risk Register",
    ]
    for r in risks:
        sev_icon = "🔴" if r["severity"] == "High" else "🟡"
        lines.append(f"- {sev_icon} **{r['risk']}** [{r['severity']}]: {r['mitigation']}")

    lines += ["", "---", "", "## Success Criteria"]
    for c in success_criteria:
        lines.append(f"- ☐ {c}")

    return {"success_criteria": success_criteria, "final_plan": "\n".join(lines)}


def _build():
    g = StateGraph(TaskPlanState)
    g.add_node("classify", classify_goal)
    g.add_node("phases", define_phases)
    g.add_node("tasks", generate_tasks)
    g.add_node("timeline", estimate_timeline)
    g.add_node("risks", identify_risks)
    g.add_node("finalize", finalize_plan)

    g.add_edge(START, "classify")
    g.add_edge("classify", "phases")
    g.add_edge("phases", "tasks")
    g.add_edge("tasks", "timeline")
    g.add_edge("timeline", "risks")
    g.add_edge("risks", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


compiled = _build()
