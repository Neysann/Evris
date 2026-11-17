import ast
import math
import operator
from typing import Any, Dict
import httpx

SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

SAFE_FUNCTIONS = {
    "sqrt": math.sqrt,
    "log": math.log,
    "ln": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "round": round,
    "factorial": math.factorial,
    "pi": math.pi,
    "e": math.e,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in SAFE_FUNCTIONS:
        val = SAFE_FUNCTIONS[node.id]
        if isinstance(val, (int, float)):
            return float(val)
    if isinstance(node, ast.BinOp) and type(node.op) in SAFE_OPERATORS:
        return SAFE_OPERATORS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_OPERATORS:
        return SAFE_OPERATORS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn_name = node.func.id
        if fn_name in SAFE_FUNCTIONS and callable(SAFE_FUNCTIONS[fn_name]):
            args = [_eval_node(a) for a in node.args]
            return float(SAFE_FUNCTIONS[fn_name](*args))
    raise ValueError(f"Unsupported mathematical expression element: {ast.dump(node)}")


def calculate_math(expression: str) -> Dict[str, Any]:
    """Evaluates a mathematical, scientific, or financial formula safely with exact precision."""
    try:
        cleaned = expression.strip().replace("^", "**")
        tree = ast.parse(cleaned, mode="eval")
        result = _eval_node(tree.body)
        return {
            "ok": True,
            "expression": expression,
            "result": result,
            "summary": f"{expression} = {result}",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Calculation error: {exc}"}


def get_market_quote(symbol: str) -> Dict[str, Any]:
    """Fetches real-time market price and daily change for a stock, index, or crypto ticker (e.g. NVDA, AAPL, BTC-USD, SPY)."""
    ticker = symbol.strip().upper()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        with httpx.Client(timeout=6.0, headers=headers) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return {"ok": False, "error": f"Ticker '{ticker}' not found (HTTP {resp.status_code})."}
            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                return {"ok": False, "error": f"No market data returned for '{ticker}'."}
            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            currency = meta.get("currency", "USD")
            change_pct = (
                round(((price - prev) / prev) * 100, 2)
                if (price is not None and prev)
                else 0.0
            )
            sign = "+" if change_pct >= 0 else ""
            return {
                "ok": True,
                "symbol": ticker,
                "price": price,
                "currency": currency,
                "previous_close": prev,
                "change_percent": change_pct,
                "summary": f"{ticker}: {price} {currency} ({sign}{change_pct}%)",
            }
    except Exception as exc:
        return {"ok": False, "error": f"Market lookup failed for {ticker}: {exc}"}
