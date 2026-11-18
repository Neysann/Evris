from app.core.logging_config import setup_logging
from app.tools.research_tools import calculate_math


def test_memory_store_messages_memories_and_settings(isolated_memory_store):
    store = isolated_memory_store

    store.add_message("user", "Hello", tier_used=None)
    store.add_message("assistant", "Systems nominal.", tier_used="fast", model_used="qwen3.5:4b", latency_ms=120)
    history = store.get_recent_messages(limit=10)
    assert len(history) == 2
    assert history[1]["tier_used"] == "fast"

    m1 = store.add_memory("finance", "Target return is 12%")
    m2 = store.add_memory("finance", "target return is 12%")  # duplicate check
    assert m1["id"] == m2["id"]
    assert len(store.get_memories()) == 1
    assert store.delete_memory(m1["id"]) is True
    assert len(store.get_memories()) == 0

    store.set_setting("routing_mode", "limitless")
    assert store.get_setting("routing_mode") == "limitless"
    assert store.get_setting("missing_key", "default") == "default"


def test_calculate_math_safe_and_accurate():
    ok_res = calculate_math("10000 * (1 + 0.08)^2")
    assert ok_res["ok"] is True
    assert round(ok_res["result"], 2) == 11664.0

    sqrt_res = calculate_math("sqrt(144) + 5")
    assert sqrt_res["ok"] is True
    assert sqrt_res["result"] == 17.0

    bad_res = calculate_math("__import__('os').system('whoami')")
    assert bad_res["ok"] is False


def test_setup_logging_creates_file(tmp_path):
    log_path = tmp_path / "evris_test.log"
    logger = setup_logging(log_file=str(log_path))
    logger.info("Test log line")
    assert logger.name == "evris"
