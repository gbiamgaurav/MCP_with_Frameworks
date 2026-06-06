"""
Code Review Pipeline — LangGraph StateGraph
Nodes: parse → metrics → detect_issues → score → suggest → format_report
Uses Python's ast module for deep static analysis; falls back to text-based
analysis for non-Python languages.
"""

import ast
import re
from typing import TypedDict, List, Optional, Any
from langgraph.graph import StateGraph, START, END


class CodeReviewState(TypedDict):
    code: str
    language: str
    ast_tree: Optional[Any]
    parse_error: Optional[str]
    metrics: dict
    issues: List[dict]
    suggestions: List[str]
    score: float
    report: str


def parse_code(state: CodeReviewState) -> dict:
    code = state["code"]
    language = state.get("language", "python").lower()

    if language != "python":
        return {
            "ast_tree": None,
            "parse_error": f"AST analysis not supported for '{language}'. Applying text-based checks only.",
        }
    try:
        tree = ast.parse(code)
        return {"ast_tree": tree, "parse_error": None}
    except SyntaxError as e:
        return {"ast_tree": None, "parse_error": f"SyntaxError at line {e.lineno}: {e.msg}"}


def analyze_metrics(state: CodeReviewState) -> dict:
    code = state["code"]
    lines = code.split("\n")
    non_empty = [l for l in lines if l.strip()]

    metrics: dict = {
        "total_lines": len(lines),
        "code_lines": len(non_empty),
        "blank_lines": len(lines) - len(non_empty),
        "avg_line_length": round(sum(len(l) for l in non_empty) / max(len(non_empty), 1), 1),
        "max_line_length": max((len(l) for l in lines), default=0),
    }

    tree = state.get("ast_tree")
    if tree:
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]

        decision_nodes = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                               ast.With, ast.Assert, ast.BoolOp))
        )

        def max_depth(node: ast.AST, depth: int = 0) -> int:
            scope_nodes = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.AsyncFor, ast.AsyncWith)
            best = depth
            for child in ast.iter_child_nodes(node):
                if isinstance(child, scope_nodes):
                    best = max(best, max_depth(child, depth + 1))
                else:
                    best = max(best, max_depth(child, depth))
            return best

        metrics.update({
            "function_count": len(functions),
            "class_count": len(classes),
            "import_count": len(imports),
            "cyclomatic_complexity": decision_nodes + 1,
            "max_nesting_depth": max_depth(tree),
        })

    return {"metrics": metrics}


def detect_issues(state: CodeReviewState) -> dict:
    code = state["code"]
    lines = code.split("\n")
    issues: List[dict] = []

    # ── Text-based checks (all languages) ─────────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()

        if len(stripped) > 120:
            issues.append({
                "severity": "warning", "line": i, "category": "style",
                "message": f"Line too long ({len(stripped)} chars, max 120)",
            })

        for marker in ("TODO", "FIXME", "HACK", "XXX"):
            if marker in line:
                issues.append({
                    "severity": "info", "line": i, "category": "maintenance",
                    "message": f"{marker} comment — resolve or create a tracked issue",
                })
                break

        if re.search(r'(?i)password\s*=\s*["\'][^"\']+["\']', line):
            issues.append({
                "severity": "error", "line": i, "category": "security",
                "message": "Hardcoded password detected",
            })
        if re.search(r'(?i)(?:secret|api_key|token)\s*=\s*["\'][^"\']{6,}["\']', line):
            issues.append({
                "severity": "error", "line": i, "category": "security",
                "message": "Hardcoded secret/token/API key detected",
            })

    # ── AST-based checks (Python only) ────────────────────────────────────────
    tree = state.get("ast_tree")
    if tree:
        for node in ast.walk(tree):
            # Bare except
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append({
                    "severity": "warning", "line": node.lineno, "category": "error_handling",
                    "message": "Bare 'except:' swallows all exceptions — use specific types",
                })

            # eval / exec usage
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec"):
                    issues.append({
                        "severity": "error", "line": node.lineno, "category": "security",
                        "message": f"Use of {node.func.id}() is a security risk",
                    })

            # Missing docstrings on public functions/classes
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                has_doc = (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                )
                if not has_doc and not node.name.startswith("_"):
                    issues.append({
                        "severity": "info", "line": node.lineno, "category": "documentation",
                        "message": f"Public function '{node.name}' is missing a docstring",
                    })

            # Mutable default arguments
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        issues.append({
                            "severity": "warning", "line": node.lineno, "category": "bug_risk",
                            "message": f"'{node.name}' has a mutable default argument — use None instead",
                        })

            # print() calls (might be debug artifacts)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                issues.append({
                    "severity": "info", "line": node.lineno, "category": "maintenance",
                    "message": "print() found — consider using logging module instead",
                })

    return {"issues": issues}


def score_code(state: CodeReviewState) -> dict:
    issues = state.get("issues", [])
    metrics = state.get("metrics", {})
    parse_error = state.get("parse_error")

    score = 10.0
    score -= sum(2.0 for i in issues if i["severity"] == "error")
    score -= sum(0.5 for i in issues if i["severity"] == "warning")
    score -= sum(0.1 for i in issues if i["severity"] == "info")

    if parse_error and "SyntaxError" in (parse_error or ""):
        score -= 3.0

    cc = metrics.get("cyclomatic_complexity", 1)
    if cc > 20:
        score -= 2.0
    elif cc > 10:
        score -= 1.0

    depth = metrics.get("max_nesting_depth", 0)
    if depth > 5:
        score -= 1.5
    elif depth > 3:
        score -= 0.5

    if metrics.get("avg_line_length", 0) > 80:
        score -= 0.5

    return {"score": round(max(0.0, min(10.0, score)), 1)}


def generate_suggestions(state: CodeReviewState) -> dict:
    issues = state.get("issues", [])
    metrics = state.get("metrics", {})
    score = state.get("score", 10.0)
    suggestions: List[str] = []

    categories = {i["category"] for i in issues}

    if "security" in categories:
        suggestions.append(
            "CRITICAL — Fix all security issues: remove hardcoded credentials and replace eval()/exec() with safe alternatives."
        )
    if "error_handling" in categories:
        suggestions.append(
            "Replace bare 'except:' with specific exception types (e.g., 'except ValueError, TypeError:') to avoid masking unexpected errors."
        )
    if "bug_risk" in categories:
        suggestions.append(
            "Mutable default arguments cause shared state bugs. Replace list/dict defaults with None and initialize inside the function body."
        )
    if "documentation" in categories:
        suggestions.append(
            "Add docstrings to all public functions. Follow Google or NumPy docstring conventions for consistency."
        )
    if "style" in categories:
        suggestions.append(
            "Lines exceed 120 characters. Extract long expressions into named variables or wrap using implicit line continuation."
        )
    if "maintenance" in categories:
        suggestions.append(
            "Resolve TODO/FIXME/HACK comments or convert them to tracked issues. Use the 'logging' module instead of print() calls."
        )

    cc = metrics.get("cyclomatic_complexity", 1)
    if cc > 15:
        suggestions.append(
            f"Cyclomatic complexity is high ({cc}). Break large functions into smaller, single-purpose helpers to improve testability."
        )

    depth = metrics.get("max_nesting_depth", 0)
    if depth > 4:
        suggestions.append(
            f"Nesting depth of {depth} is too deep. Use early returns, guard clauses, or extract inner blocks into helper functions."
        )

    if score >= 8.5:
        suggestions.append(
            "Code quality is excellent. Consider adding type hints throughout and property-based testing for edge cases."
        )
    elif score >= 6.0:
        suggestions.append(
            "Good foundation. Addressing the warnings above will bring quality to production-ready level."
        )

    return {"suggestions": suggestions}


def format_report(state: CodeReviewState) -> dict:
    language = state.get("language", "python")
    metrics = state.get("metrics", {})
    issues = state.get("issues", [])
    suggestions = state.get("suggestions", [])
    score = state.get("score", 0.0)
    parse_error = state.get("parse_error")

    grade = "A" if score >= 9 else "B" if score >= 7 else "C" if score >= 5 else "D" if score >= 3 else "F"

    lines = [
        "# Code Review Report",
        f"**Language:** {language.title()}  |  **Quality Score:** {score}/10  |  **Grade:** {grade}",
        "",
    ]

    if parse_error:
        lines += ["## Parse Issues", f"> {parse_error}", ""]

    lines += ["## Metrics"]
    label_map = {
        "total_lines": "Total Lines",
        "code_lines": "Non-empty Lines",
        "blank_lines": "Blank Lines",
        "avg_line_length": "Avg Line Length",
        "max_line_length": "Max Line Length",
        "function_count": "Functions",
        "class_count": "Classes",
        "import_count": "Imports",
        "cyclomatic_complexity": "Cyclomatic Complexity",
        "max_nesting_depth": "Max Nesting Depth",
    }
    for k, label in label_map.items():
        if k in metrics:
            v = metrics[k]
            lines.append(f"- **{label}:** {v:.1f}" if isinstance(v, float) else f"- **{label}:** {v}")

    if issues:
        lines += ["", "## Issues Found"]
        by_sev: dict = {}
        for issue in issues:
            by_sev.setdefault(issue["severity"], []).append(issue)
        icons = {"error": "🔴", "warning": "🟡", "info": "🔵"}
        for sev in ("error", "warning", "info"):
            if sev in by_sev:
                lines.append(f"\n### {icons[sev]} {sev.title()}s ({len(by_sev[sev])})")
                for issue in by_sev[sev][:15]:
                    lines.append(f"- **L{issue['line']}** [{issue['category']}] {issue['message']}")
    else:
        lines += ["", "## Issues Found", "No issues detected."]

    if suggestions:
        lines += ["", "## Suggestions"]
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. {s}")

    return {"report": "\n".join(lines)}


def _build():
    g = StateGraph(CodeReviewState)
    g.add_node("parse", parse_code)
    g.add_node("metrics", analyze_metrics)
    g.add_node("issues", detect_issues)
    g.add_node("score", score_code)
    g.add_node("suggest", generate_suggestions)
    g.add_node("report", format_report)

    g.add_edge(START, "parse")
    g.add_edge("parse", "metrics")
    g.add_edge("metrics", "issues")
    g.add_edge("issues", "score")
    g.add_edge("score", "suggest")
    g.add_edge("suggest", "report")
    g.add_edge("report", END)
    return g.compile()


compiled = _build()
