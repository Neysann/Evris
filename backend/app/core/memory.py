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


memory_store = MemoryStore()
