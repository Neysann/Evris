import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import evris  # noqa: E402


def test_live_turn_display_lifecycle():
    display = evris.LiveTurnDisplay("fast", "general", "qwen3.5:4b")
    display.start()
    display.handle_event({"type": "status", "message": "Thinking..."})
    display.handle_event({"type": "tool_start", "name": "calculate_math"})
    display.handle_event(
        {
            "type": "tool_end",
            "name": "calculate_math",
            "result": {"ok": True, "summary": "2+2 = 4"},
        }
    )
    display.pause()
    display.resume()
    display.handle_event({"type": "token", "delta": "4.", "text": "**4.**"})
    display.handle_event(
        {
            "type": "tier_switch",
            "tier": "limitless",
            "model": "huihui_ai/qwen3.5-abliterated:9b",
            "message": "Switching to LIMITLESS...",
        }
    )
    assert display.tier == "limitless"
    assert display.stream_text == ""
    display.handle_event({"type": "token", "delta": "OK", "text": "OK"})
    display.finish("limitless", "huihui_ai/qwen3.5-abliterated:9b", 123, "OK", [])

    assert display.finished is True
    assert display.stream_text == "OK"
    assert len(display.tool_logs) == 1
