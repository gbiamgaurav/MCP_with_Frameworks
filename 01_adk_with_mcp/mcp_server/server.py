

import ast
import math
import operator
import os
import sys
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
mcp = FastMCP("learning-tools-server", transport_security=_security)


# ---------------------------------------------------------------------------
# Tool: get_weather
# ---------------------------------------------------------------------------

_WEATHER_DB: dict[str, dict] = {
    "london":    {"temp_c": 15, "condition": "Cloudy",  "humidity": 75, "wind_kmh": 20},
    "new york":  {"temp_c": 22, "condition": "Sunny",   "humidity": 60, "wind_kmh": 12},
    "tokyo":     {"temp_c": 28, "condition": "Humid",   "humidity": 85, "wind_kmh": 8},
    "sydney":    {"temp_c": 18, "condition": "Partly Cloudy", "humidity": 70, "wind_kmh": 25},
    "paris":     {"temp_c": 17, "condition": "Overcast","humidity": 80, "wind_kmh": 15},
    "mumbai":    {"temp_c": 32, "condition": "Hot",     "humidity": 90, "wind_kmh": 10},
    "singapore": {"temp_c": 30, "condition": "Thunderstorm", "humidity": 88, "wind_kmh": 18},
}


@mcp.tool()
def get_weather(city: str) -> dict:
    """
    Get current weather for a city.

    Args:
        city: City name (e.g. "London", "Tokyo", "New York")

    Returns:
        dict with temp_c, condition, humidity, wind_kmh
    """
    key = city.strip().lower()
    data = _WEATHER_DB.get(key, {"temp_c": 20, "condition": "Clear", "humidity": 65, "wind_kmh": 10})
    return {
        "city": city,
        "temp_celsius": data["temp_c"],
        "temp_fahrenheit": round(data["temp_c"] * 9 / 5 + 32, 1),
        "condition": data["condition"],
        "humidity_pct": data["humidity"],
        "wind_kmh": data["wind_kmh"],
    }


# ---------------------------------------------------------------------------
# Tool: calculate  (safe AST-based evaluator — no eval())
# ---------------------------------------------------------------------------

_SAFE_OPS = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Pow:  operator.pow,
    ast.Mod:  operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_SAFE_NAMES = {
    "pi": math.pi,
    "e":  math.e,
    "sqrt":  math.sqrt,
    "log":   math.log,
    "log10": math.log10,
    "sin":   math.sin,
    "cos":   math.cos,
    "tan":   math.tan,
    "abs":   abs,
    "round": round,
}


def _eval_node(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _SAFE_NAMES:
            return _SAFE_NAMES[node.id]
        raise ValueError(f"Unknown name: {node.id}")
    if isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.Call):
        func = _eval_node(node.func)
        args = [_eval_node(a) for a in node.args]
        return func(*args)
    raise ValueError(f"Unsupported AST node: {type(node).__name__}")


@mcp.tool()
def calculate(expression: str) -> dict:
    """
    Safely evaluate a mathematical expression.

    Supports: +, -, *, /, **, %, pi, e, sqrt(), log(), sin(), cos(), tan(), abs(), round()

    Args:
        expression: Math expression string, e.g. "sqrt(144) + 2 ** 8"

    Returns:
        dict with expression and result (or error)
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval_node(tree.body)
        return {"expression": expression, "result": result, "status": "ok"}
    except ZeroDivisionError:
        return {"expression": expression, "error": "Division by zero", "status": "error"}
    except Exception as exc:
        return {"expression": expression, "error": str(exc), "status": "error"}


# ---------------------------------------------------------------------------
# Tool: get_stock_price  (mock data for learning)
# ---------------------------------------------------------------------------

_STOCK_DB: dict[str, dict] = {
    "AAPL":  {"price": 189.30, "change_pct": +1.2,  "company": "Apple Inc."},
    "GOOGL": {"price": 175.80, "change_pct": -0.4,  "company": "Alphabet Inc."},
    "MSFT":  {"price": 415.20, "change_pct": +0.8,  "company": "Microsoft Corp."},
    "AMZN":  {"price": 184.50, "change_pct": +2.1,  "company": "Amazon.com Inc."},
    "TSLA":  {"price": 248.70, "change_pct": -1.5,  "company": "Tesla Inc."},
    "NVDA":  {"price": 875.40, "change_pct": +3.2,  "company": "NVIDIA Corp."},
    "META":  {"price": 512.60, "change_pct": +0.6,  "company": "Meta Platforms Inc."},
}


@mcp.tool()
def get_stock_price(ticker: str) -> dict:
    """
    Get mock stock price for a ticker symbol.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL", "GOOGL", "TSLA")

    Returns:
        dict with price, change_pct, company name
    """
    key = ticker.strip().upper()
    if key in _STOCK_DB:
        data = _STOCK_DB[key]
        return {"ticker": key, "price_usd": data["price"], "change_pct": data["change_pct"], "company": data["company"]}
    return {"ticker": key, "error": f"Ticker '{key}' not found. Available: {', '.join(_STOCK_DB)}", "status": "not_found"}


# ---------------------------------------------------------------------------
# Tool: get_current_datetime
# ---------------------------------------------------------------------------

@mcp.tool()
def get_current_datetime() -> dict:
    """
    Get the current UTC date and time.

    Returns:
        dict with date, time, day_of_week, unix_timestamp
    """
    now = datetime.now(timezone.utc)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timezone": "UTC",
        "day_of_week": now.strftime("%A"),
        "unix_timestamp": int(now.timestamp()),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if "--sse" in sys.argv:
        transport = "sse"
    elif "--http" in sys.argv:
        transport = "http"

    if transport == "http":
        import uvicorn
        port = int(os.getenv("PORT", "8080"))
        print(f"Starting MCP server with Streamable HTTP transport on port {port}", flush=True)
        uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")
    elif transport == "sse":
        import uvicorn
        port = int(os.getenv("PORT", "8080"))
        print(f"Starting MCP server with SSE transport on port {port}", flush=True)
        uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")
    else:
        # stdio — used by ADK via StdioServerParameters (subprocess)
        mcp.run()
