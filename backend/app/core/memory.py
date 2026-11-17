import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
from app.config import settings


class MemoryStore:
    def __init__(self, db_path: str = settings.db_path) -> None:
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tier_used TEXT,
                    model_used TEXT,
                    latency_ms INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            cols = [
                r["name"]
                for r in conn.execute("PRAGMA table_info(messages)").fetchall()
            ]
            if "tier_used" not in cols:
                conn.execute("ALTER TABLE messages ADD COLUMN tier_used TEXT")
            if "latency_ms" not in cols:
                conn.execute("ALTER TABLE messages ADD COLUMN latency_ms INTEGER")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add_message(
        self,
        role: str,
        content: str,
        tier_used: Optional[str] = None,
        model_used: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (role, content, tier_used, model_used, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (role, content, tier_used, model_used, latency_ms, now),
            )
            conn.commit()
            return {
                "id": cursor.lastrowid,
                "role": role,
                "content": content,
                "tier_used": tier_used,
                "model_used": model_used,
                "latency_ms": latency_ms,
                "created_at": now,
            }

    def get_recent_messages(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_messages(self) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM messages")
            conn.commit()

    # Long-Term Fact Memory
    def add_memory(self, category: str, content: str) -> Dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        with self._get_conn() as conn:
            # Avoid exact duplicates
            existing = conn.execute(
                "SELECT * FROM memories WHERE LOWER(content) = LOWER(?)",
                (content.strip(),),
            ).fetchone()
            if existing:
                return dict(existing)

            cursor = conn.execute(
                "INSERT INTO memories (category, content, created_at) VALUES (?, ?, ?)",
                (category.strip().lower(), content.strip(), now),
            )
            conn.commit()
            return {
                "id": cursor.lastrowid,
                "category": category.strip().lower(),
                "content": content.strip(),
                "created_at": now,
            }

    def get_memories(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_memory(self, memory_id: int) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0

    def clear_memories(self) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM memories")
            conn.commit()


memory_store = MemoryStore()
