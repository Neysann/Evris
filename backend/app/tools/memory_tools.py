from typing import Any, Dict
from app.core.memory import memory_store


def save_memory(category: str, content: str) -> Dict[str, Any]:
    """Saves an important fact, user preference, or project detail into long-term SQLite memory."""
    if not content or not content.strip():
        return {"ok": False, "error": "Memory content cannot be empty."}
    item = memory_store.add_memory(category=category or "general", content=content)
    return {
        "ok": True,
        "memory": item,
        "summary": f"Saved to long-term memory [{item['category']}]: {item['content']}",
    }


def list_memories() -> Dict[str, Any]:
    """Returns all saved long-term memories."""
    items = memory_store.get_memories(limit=50)
    return {
        "ok": True,
        "count": len(items),
        "memories": items,
        "summary": f"Retrieved {len(items)} stored memory item(s).",
    }
