import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.core.router import DualModelRouter
from app.tools import pc_control


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.reason_phrase = "Error"

    def json(self):
        return self._payload


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str], text: str = ""):
        self.status_code = status_code
        self._lines = lines
        self.text = text
        self.reason_phrase = "Error"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aread(self):
        return self.text.encode("utf-8")

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    def __init__(self, tags_models=None, ps_models=None, chat_responses=None, stream_responses=None, **_kwargs):
        self.tags_models = tags_models or []
        self.ps_models = ps_models or []
        self.chat_responses = list(chat_responses or [])
        self.stream_responses = list(stream_responses or [])
        self.posted_payloads = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        if url.endswith("/api/tags"):
            return _FakeResponse(200, {"models": [{"name": m} for m in self.tags_models]})
        if url.endswith("/api/ps"):
            return _FakeResponse(200, {"models": self.ps_models})
        return _FakeResponse(404, {})

    async def post(self, url, json=None):
        self.posted_payloads.append(json)
        if self.chat_responses:
            return self.chat_responses.pop(0)
        return _FakeResponse(200, {"message": {"role": "assistant", "content": "Nominal."}})

    def stream(self, method, url, json=None):
        self.posted_payloads.append(json)
        if self.stream_responses:
            return self.stream_responses.pop(0)
        return _FakeStreamResponse(200, [])


def test_domain_and_task_classification(isolated_memory_store):
    router = DualModelRouter()
    router.set_routing_mode("auto")

    assert router.classify_task("Salut Evris") == ("fast", "general")
    assert router.classify_task("What is the price of NVDA?") == ("pro", "finance")
    assert router.classify_task("Explain quantum entanglement") == ("pro", "science")
    assert router.classify_task("Write a Python function to sort") == ("pro", "tech")
    assert router.classify_task("Explain Nash equilibrium strategy") == ("pro", "strategy")

    router.set_routing_mode("limitless")
    assert router.classify_task("Salut") == ("limitless", "general")


def test_settings_persistence_across_router_instances(isolated_memory_store):
    r1 = DualModelRouter()
    r1.set_routing_mode("limitless")
    r1.set_pro_enabled(False)
    r1.set_pro_min_free_ram_gb(7.25)
    r1.set_confirm_risky_actions(False)

    r2 = DualModelRouter()
    assert r2.routing_mode == "limitless"
    assert r2.pro_enabled is False
    assert r2.pro_min_free_ram_gb == 7.25
    assert pc_control.is_confirm_risky_actions_enabled() is False

    # Restore default confirmation state
    r2.set_confirm_risky_actions(True)


def test_model_matches():
    assert DualModelRouter._model_matches("qwen3.5:4b", ["qwen3.5:4b"]) is True
    assert DualModelRouter._model_matches("qwen3.5:9b", ["qwen3.5:9b-q4_K_M"]) is True
    assert DualModelRouter._model_matches("qwen3.5", ["qwen3.5:latest"]) is True
    assert DualModelRouter._model_matches("qwen3.5:9b", ["qwen3.5:4b"]) is False


@pytest.mark.asyncio
async def test_ram_guardrail_blocks_low_ram(isolated_memory_store):
    router = DualModelRouter()
    router.set_pro_min_free_ram_gb(8.0)

    fake_vm = SimpleNamespace(available=int(3.0 * (1024**3)))
    fake_client = _FakeAsyncClient(
        tags_models=["qwen3.5:4b", "qwen3.5:9b", "huihui_ai/qwen3.5-abliterated:9b"]
    )

    with patch("app.core.router.psutil.virtual_memory", return_value=fake_vm), patch(
        "app.core.router.httpx.AsyncClient", return_value=fake_client
    ):
        reply, tier, model, _lat, _tools = await router.generate_with_tools(
            "limitless", [{"role": "user", "content": "Test"}]
        )

    assert tier == "refused"
    assert model == router.limitless_model
    assert "RAM Safety Guardrail" in reply


@pytest.mark.asyncio
async def test_generate_with_tools_executes_tool_and_sets_think_flag(isolated_memory_store):
    router = DualModelRouter()
    fake_vm = SimpleNamespace(available=int(12.0 * (1024**3)))
    fake_client = _FakeAsyncClient(
        tags_models=["qwen3.5:4b", "qwen3.5:9b", "huihui_ai/qwen3.5-abliterated:9b"],
        chat_responses=[
            _FakeResponse(
                200,
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "calculate_math", "arguments": {"expression": "2**10"}}}
                        ],
                    }
                },
            ),
            _FakeResponse(
                200,
                {"message": {"role": "assistant", "content": "2**10 equals 1024."}},
            ),
        ],
    )

    with patch("app.core.router.psutil.virtual_memory", return_value=fake_vm), patch(
        "app.core.router.httpx.AsyncClient", return_value=fake_client
    ):
        reply, tier, model, _lat, tools = await router.generate_with_tools(
            "fast", [{"role": "user", "content": "What is 2^10?"}]
        )

    assert tier == "fast"
    assert model == router.fast_model
    assert reply == "2**10 equals 1024."
    assert len(tools) == 1
    assert tools[0]["result"]["result"] == 1024.0
    assert fake_client.posted_payloads[0]["think"] is False


@pytest.mark.asyncio
async def test_generate_surfaces_ollama_http_error(isolated_memory_store):
    router = DualModelRouter()
    fake_vm = SimpleNamespace(available=int(12.0 * (1024**3)))
    fake_client = _FakeAsyncClient(
        tags_models=["qwen3.5:4b", "qwen3.5:9b"],
        chat_responses=[
            _FakeResponse(500, {"error": "CUDA out of memory"}),
        ],
    )

    with patch("app.core.router.psutil.virtual_memory", return_value=fake_vm), patch(
        "app.core.router.httpx.AsyncClient", return_value=fake_client
    ):
        reply, tier, _model, _lat, _tools = await router.generate_with_tools(
            "pro", [{"role": "user", "content": "Analyze"}]
        )

    assert tier == "refused"
    assert "HTTP 500" in reply
    assert "CUDA out of memory" in reply


@pytest.mark.asyncio
async def test_streaming_emits_tokens_and_tool_events(isolated_memory_store):
    router = DualModelRouter()
    fake_vm = SimpleNamespace(available=int(12.0 * (1024**3)))
    stream_round_1 = _FakeStreamResponse(
        200,
        [
            json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "calculate_math", "arguments": {"expression": "6*7"}}}
                        ],
                    },
                    "done": True,
                }
            )
        ],
    )
    stream_round_2 = _FakeStreamResponse(
        200,
        [
            json.dumps({"message": {"role": "assistant", "content": "The answer "}, "done": False}),
            json.dumps({"message": {"role": "assistant", "content": "is 42."}, "done": True}),
        ],
    )
    fake_client = _FakeAsyncClient(
        tags_models=["qwen3.5:4b"],
        stream_responses=[stream_round_1, stream_round_2],
    )

    events = []

    with patch("app.core.router.psutil.virtual_memory", return_value=fake_vm), patch(
        "app.core.router.httpx.AsyncClient", return_value=fake_client
    ):
        reply, tier, _model, _lat, tools = await router.generate_with_tools(
            "fast",
            [{"role": "user", "content": "6*7?"}],
            on_event=events.append,
        )

    assert tier == "fast"
    assert reply == "The answer is 42."
    assert len(tools) == 1
    assert [e["type"] for e in events] == ["status", "tool_start", "tool_end", "token", "token"]
    assert fake_client.posted_payloads[0]["stream"] is True
