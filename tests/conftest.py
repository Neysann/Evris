import sys
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def isolated_memory_store(tmp_path, monkeypatch):
    """Provide an isolated SQLite MemoryStore backed by a temporary file."""
    from app.core.memory import MemoryStore
    import app.core.memory as memory_mod
    import app.core.router as router_mod

    db_file = tmp_path / "test_evris.db"
    store = MemoryStore(db_path=str(db_file))
    monkeypatch.setattr(memory_mod, "memory_store", store)
    monkeypatch.setattr(router_mod, "memory_store", store)
    return store
