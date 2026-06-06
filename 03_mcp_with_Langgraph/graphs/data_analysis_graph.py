"""
Data Analysis Pipeline — LangGraph StateGraph
Nodes: parse → compute_stats → detect_anomalies → find_trends → generate_insights
Accepts CSV (with header) or JSON array of objects.
Uses Python stdlib: csv, json, statistics — no pandas required.
"""

import csv
import io
import json
import statistics
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, START, END


class DataAnalysisState(TypedDict):
    raw_data: str
    data_format: str
    records: List[dict]
    columns: List[str]
    column_stats: List[dict]
    anomalies: List[dict]
    trends: List[str]
    insights: str
    report: str
    error: Optional[str]


def parse_data(state: DataAnalysisState) -> dict:
    raw = state["raw_data"].strip()
    fmt = state.get("data_format", "auto").lower()

    if fmt == "auto":
        fmt = "json" if raw.startswith(("[", "{")) else "csv"

    try:
        if fmt == "json":
            parsed = json.loads(raw)
            records: List[dict] = parsed if isinstance(parsed, list) else [parsed]
        else:
            reader = csv.DictReader(io.StringIO(raw))
            records = [dict(row) for row in reader]

        columns = list(records[0].keys()) if records else []
        return {"records": records, "columns": columns, "data_format": fmt, "error": None}

    except Exception as e:
        return {"records": [], "columns": [], "error": f"Parse error ({fmt}): {e}"}


def compute_statistics(state: DataAnalysisState) -> dict:
    records = state.get("records", [])
    columns = state.get("columns", [])

    if not records:
        return {"column_stats": []}

    col_stats: List[dict] = []

    for col in columns:
        raw_values = [r.get(col) for r in records]
        missing = sum(1 for v in raw_values if v is None or str(v).strip() in ("", "null", "None", "NA", "N/A"))
        present = [v for v in raw_values if v is not None and str(v).strip() not in ("", "null", "None", "NA", "N/A")]

        # Try numeric cast
        numeric: List[float] = []
        for v in present:
            try:
                numeric.append(float(str(v).replace(",", "").replace("$", "").strip()))
            except (ValueError, TypeError):
                pass

        is_numeric = len(numeric) > len(present) * 0.5
        str_values = [str(v) for v in present]
        unique_vals = list(dict.fromkeys(str_values))

        # Top-5 most frequent values
        from collections import Counter
        freq_map = Counter(str_values)
        top = [f"{v} ({c}×)" for v, c in freq_map.most_common(5)]

        stats: dict = {
            "name": col,
            "count": len(present),
            "missing": missing,
            "unique_count": len(unique_vals),
            "is_numeric": is_numeric,
            "top_values": top,
            "min": None, "max": None, "mean": None, "median": None,
            "stdev": None, "p25": None, "p75": None, "iqr": None,
        }

        if is_numeric and len(numeric) >= 2:
            sv = sorted(numeric)
            n = len(sv)
            stats["min"] = round(sv[0], 4)
            stats["max"] = round(sv[-1], 4)
            stats["mean"] = round(statistics.mean(numeric), 4)
            stats["median"] = round(statistics.median(numeric), 4)
            stats["stdev"] = round(statistics.stdev(numeric), 4)
            stats["p25"] = round(sv[n // 4], 4)
            stats["p75"] = round(sv[3 * n // 4], 4)
            stats["iqr"] = round(stats["p75"] - stats["p25"], 4)

        col_stats.append(stats)

    return {"column_stats": col_stats}


def detect_anomalies(state: DataAnalysisState) -> dict:
    col_stats = state.get("column_stats", [])
    records = state.get("records", [])
    anomalies: List[dict] = []

    for stats in col_stats:
        if not stats["is_numeric"]:
            continue

        col = stats["name"]
        mean = stats.get("mean")
        stdev = stats.get("stdev")
        iqr = stats.get("iqr")
        p25 = stats.get("p25")
        p75 = stats.get("p75")

        if mean is None:
            continue

        # Z-score outliers (|z| > 3)
        if stdev and stdev > 0:
            for i, rec in enumerate(records):
                v = rec.get(col)
                if v is None or str(v).strip() in ("", "null"):
                    continue
                try:
                    num = float(str(v).replace(",", "").replace("$", "").strip())
                    z = abs(num - mean) / stdev
                    if z > 3.0:
                        anomalies.append({
                            "type": "z_score_outlier",
                            "row": i + 1,
                            "column": col,
                            "value": num,
                            "z_score": round(z, 2),
                            "direction": "high" if num > mean else "low",
                            "description": f"Row {i + 1}, '{col}' = {num} (z={z:.2f}, mean={mean})",
                        })
                except (ValueError, TypeError):
                    pass

        # IQR fence outliers (beyond 1.5×IQR)
        if iqr and iqr > 0 and p25 is not None and p75 is not None:
            fence_lo = p25 - 1.5 * iqr
            fence_hi = p75 + 1.5 * iqr
            for i, rec in enumerate(records):
                v = rec.get(col)
                if v is None or str(v).strip() in ("", "null"):
                    continue
                try:
                    num = float(str(v).replace(",", "").replace("$", "").strip())
                    if num < fence_lo or num > fence_hi:
                        # Skip if already flagged by z-score
                        already = any(
                            a["row"] == i + 1 and a["column"] == col
                            for a in anomalies
                        )
                        if not already:
                            anomalies.append({
                                "type": "iqr_outlier",
                                "row": i + 1,
                                "column": col,
                                "value": num,
                                "z_score": None,
                                "direction": "high" if num > fence_hi else "low",
                                "description": (
                                    f"Row {i + 1}, '{col}' = {num} is outside IQR fence "
                                    f"[{fence_lo:.2f}, {fence_hi:.2f}]"
                                ),
                            })
                except (ValueError, TypeError):
                    pass

        # High missing-value rate
        total = stats["count"] + stats["missing"]
        if total > 0 and stats["missing"] / total > 0.20:
            pct = stats["missing"] / total * 100
            anomalies.append({
                "type": "high_missing",
                "row": -1,
                "column": col,
                "value": None,
                "z_score": None,
                "direction": "missing_data",
                "description": f"Column '{col}' has {pct:.1f}% missing values ({stats['missing']}/{total})",
            })

    return {"anomalies": anomalies}


def find_trends(state: DataAnalysisState) -> dict:
    col_stats = state.get("column_stats", [])
    records = state.get("records", [])
    trends: List[str] = []

    numeric_cols = [s for s in col_stats if s["is_numeric"] and s["count"] >= 4]

    for stats in numeric_cols:
        col = stats["name"]
        values: List[float] = []
        for r in records:
            v = r.get(col)
            if v is None or str(v).strip() in ("", "null"):
                continue
            try:
                values.append(float(str(v).replace(",", "").replace("$", "").strip()))
            except (ValueError, TypeError):
                pass

        if len(values) < 4:
            continue

        # First-half vs second-half trend
        mid = len(values) // 2
        avg_first = sum(values[:mid]) / mid
        avg_second = sum(values[mid:]) / (len(values) - mid)

        if avg_first != 0:
            change_pct = (avg_second - avg_first) / abs(avg_first) * 100
            if abs(change_pct) > 10:
                direction = "increasing" if change_pct > 0 else "decreasing"
                trends.append(
                    f"'{col}' shows a {direction} trend "
                    f"({change_pct:+.1f}% change; first-half avg {avg_first:.3g} → second-half avg {avg_second:.3g})"
                )

        # Coefficient of variation → volatility
        mean = stats.get("mean")
        stdev = stats.get("stdev")
        if mean and stdev and mean != 0:
            cv = stdev / abs(mean)
            if cv > 0.5:
                trends.append(
                    f"'{col}' is highly volatile (CV = {cv:.2f}), suggesting inconsistent values."
                )

    # Pearson correlation between numeric column pairs
    if len(numeric_cols) >= 2:
        for i in range(len(numeric_cols)):
            for j in range(i + 1, len(numeric_cols)):
                c1 = numeric_cols[i]["name"]
                c2 = numeric_cols[j]["name"]
                v1, v2 = [], []
                for r in records:
                    try:
                        a = float(str(r.get(c1, "")).replace(",", "").replace("$", "").strip())
                        b = float(str(r.get(c2, "")).replace(",", "").replace("$", "").strip())
                        v1.append(a)
                        v2.append(b)
                    except (ValueError, TypeError):
                        pass

                n = len(v1)
                if n < 4:
                    continue

                m1 = sum(v1) / n
                m2 = sum(v2) / n
                num = sum((v1[k] - m1) * (v2[k] - m2) for k in range(n))
                d1 = sum((v1[k] - m1) ** 2 for k in range(n)) ** 0.5
                d2 = sum((v2[k] - m2) ** 2 for k in range(n)) ** 0.5

                if d1 > 0 and d2 > 0:
                    r_val = num / (d1 * d2)
                    if abs(r_val) > 0.7:
                        rel = "positively" if r_val > 0 else "negatively"
                        trends.append(
                            f"'{c1}' and '{c2}' are strongly {rel} correlated (r = {r_val:.2f})."
                        )

    return {"trends": trends}


def generate_insights(state: DataAnalysisState) -> dict:
    records = state.get("records", [])
    columns = state.get("columns", [])
    col_stats = state.get("column_stats", [])
    anomalies = state.get("anomalies", [])
    trends = state.get("trends", [])
    error = state.get("error")

    if error:
        msg = f"# Data Analysis Report\n\n**Error:** {error}"
        return {"insights": error, "report": msg}

    # ── Report ──────────────────────────────────────────────────────────────
    lines = [
        "# Data Analysis Report",
        "",
        "## Dataset Overview",
        f"- **Rows:** {len(records)}",
        f"- **Columns:** {len(columns)} ({', '.join(columns)})",
        f"- **Outliers detected:** {sum(1 for a in anomalies if a['type'] in ('z_score_outlier', 'iqr_outlier'))}",
        f"- **Missing-value issues:** {sum(1 for a in anomalies if a['type'] == 'high_missing')}",
        "",
        "## Column Profiles",
    ]

    for stats in col_stats:
        lines.append(f"\n### {stats['name']}")
        dtype = "Numeric" if stats["is_numeric"] else "Categorical"
        lines.append(f"- **Type:** {dtype}  |  **Non-null:** {stats['count']}  |  **Missing:** {stats['missing']}  |  **Unique:** {stats['unique_count']}")
        if stats["is_numeric"]:
            lines.append(
                f"- **Range:** {stats['min']} – {stats['max']}  |  "
                f"**Mean:** {stats['mean']}  |  **Median:** {stats['median']}  |  **StdDev:** {stats['stdev']}"
            )
            lines.append(f"- **P25:** {stats['p25']}  |  **P75:** {stats['p75']}  |  **IQR:** {stats['iqr']}")
        else:
            lines.append(f"- **Top values:** {', '.join(stats['top_values'][:3])}")

    if anomalies:
        lines += ["", "## Anomalies"]
        for a in anomalies[:20]:
            lines.append(f"- {a['description']}")

    if trends:
        lines += ["", "## Trends & Correlations"]
        for t in trends:
            lines.append(f"- {t}")

    # Natural-language summary
    numeric_cols = [s for s in col_stats if s["is_numeric"]]
    parts = [
        f"Analyzed {len(records)} records across {len(columns)} columns.",
        f"{len(numeric_cols)} numeric column(s) profiled." if numeric_cols else "",
        f"{len(anomalies)} anomaly/anomalies detected." if anomalies else "No anomalies detected.",
        f"{len(trends)} trend pattern(s) identified." if trends else "",
    ]
    insights = " ".join(p for p in parts if p)

    lines += ["", "## Summary Insights", insights]

    return {"insights": insights, "report": "\n".join(lines)}


def _build():
    g = StateGraph(DataAnalysisState)
    g.add_node("parse", parse_data)
    g.add_node("stats", compute_statistics)
    g.add_node("anomalies", detect_anomalies)
    g.add_node("trends", find_trends)
    g.add_node("insights", generate_insights)

    g.add_edge(START, "parse")
    g.add_edge("parse", "stats")
    g.add_edge("stats", "anomalies")
    g.add_edge("anomalies", "trends")
    g.add_edge("trends", "insights")
    g.add_edge("insights", END)
    return g.compile()


compiled = _build()
