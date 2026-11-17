import json
from typing import Any, Dict, List
from app.tools.memory_tools import list_memories, save_memory
from app.tools.pc_control import (
    get_system_report,
    list_directory,
    open_application,
    read_local_file,
)
from app.tools.research_tools import calculate_math, get_market_quote

OLLAMA_TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save a permanent fact, user preference, or instruction into long-term memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Short category label (e.g. 'preference', 'project', 'finance', 'personal').",
                    },
                    "content": {
                        "type": "string",
                        "description": "The exact fact or instruction to remember permanently.",
                    },
                },
                "required": ["category", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Launch a desktop application (calculator, notepad, explorer, vscode, terminal, taskmgr) or open a https:// URL on the user's PC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Application name or URL to open.",
                    },
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_report",
            "description": "Get a detailed hardware report of the PC including CPU load, free RAM, disk space, battery, and top RAM-consuming processes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_local_file",
            "description": "Read the contents of a local file on the computer to analyze, summarize, or debug it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to read.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and folders inside a directory on the user's PC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "Directory path to inspect (default '.').",
                    },
                },
                "required": ["dir_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_math",
            "description": "Evaluate a mathematical, scientific, or financial formula with exact precision (e.g. '10000 * (1 + 0.07)**10').",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to evaluate.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_quote",
            "description": "Fetch live stock, index, or crypto market price and daily percentage change (e.g. 'NVDA', 'AAPL', 'BTC-USD', 'SPY').",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol (e.g. 'NVDA', 'BTC-USD').",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
]


def execute_tool(name: str, arguments: Dict[str, Any] | str) -> Dict[str, Any]:
    """Executes a registered tool by name and returns a structured result dict."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            arguments = {}

    args = arguments or {}
    try:
        if name == "save_memory":
            return save_memory(
                category=str(args.get("category", "general")),
                content=str(args.get("content", "")),
            )
        if name == "list_memories":
            return list_memories()
        if name == "open_application":
            return open_application(target=str(args.get("target", "")))
        if name == "get_system_report":
            return get_system_report()
        if name == "read_local_file":
            return read_local_file(file_path=str(args.get("file_path", "")))
        if name == "list_directory":
            return list_directory(dir_path=str(args.get("dir_path", ".")))
        if name == "calculate_math":
            return calculate_math(expression=str(args.get("expression", "")))
        if name == "get_market_quote":
            return get_market_quote(symbol=str(args.get("symbol", "")))
        return {"ok": False, "error": f"Unknown tool: {name}"}
    except Exception as exc:
        return {"ok": False, "error": f"Tool execution error ({name}): {exc}"}
