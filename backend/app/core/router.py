import asyncio
import json
import re
import time
from typing import Any, Dict, List, Tuple
import httpx
import psutil
from app.config import settings
from app.core.logging_config import get_logger
from app.core.memory import memory_store
from app.tools.pc_control import is_confirm_risky_actions_enabled, set_confirm_risky_actions
from app.tools.registry import OLLAMA_TOOLS_SCHEMA, execute_tool

logger = get_logger(__name__)

DOMAIN_PATTERNS = {
    "finance": re.compile(
        r"\b("
        r"finance|financial|stock|stocks|market|markets|invest|investing|investment|portfolio|bond|bonds|"
        r"inflation|interest rate|fed|ecb|gdp|economy|economic|macroeconomics|valuation|dcf|ebitda|equity|"
        r"dividend|crypto|bitcoin|btc|eth|nvda|aapl|msft|spy|ticker|price of|share price|trading|option|options|"
        r"hedge|yield|risk|asset|capital|bourse|action|actions|investissement|portefeuille|taux|économie|"
        r"économique|rendement|obligation|valorisation"
        r")\b",
        flags=re.IGNORECASE,
    ),
    "science": re.compile(
        r"\b("
        r"physics|quantum|relativity|thermodynamics|entropy|chemistry|molecule|reaction|atom|biology|dna|"
        r"genetics|neuroscience|cell|evolution|astronomy|astrophysics|math|mathematics|calculus|integral|"
        r"derivative|matrix|theorem|proof|probability|statistics|equation|energy|force|voltage|circuit|"
        r"physique|quantique|thermodynamique|chimie|biologie|mathématiques|équation|énergie|probabilité|théorème"
        r")\b",
        flags=re.IGNORECASE,
    ),
    "tech": re.compile(
        r"\b("
        r"code|coding|python|typescript|javascript|rust|c\+\+|sql|script|function|class|debug|bug|refactor|"
        r"algorithm|architecture|api|database|docker|linux|kernel|network|security|encryption|neural|llm|"
        r"programme|programmer|algorithme|base de données|réseau|sécurité"
        r")\b",
        flags=re.IGNORECASE,
    ),
    "strategy": re.compile(
        r"\b("
        r"strategy|strategic|geopolitics|game theory|nash|history|historical|war|empire|law|legal|contract|"
        r"philosophy|ethics|negotiation|stratégie|géopolitique|histoire|historique|droit|philosophie"
        r")\b",
        flags=re.IGNORECASE,
    ),
}

COMPLEX_TRIGGERS = re.compile(
    r"\b("
    r"analyze|analysis|explain|why|how does|compare|difference between|deep dive|step by step|plan|design|"
    r"evaluate|calculate|solve|optimize|read file|inspect file|summarize|"
    r"explique|pourquoi|comment fonctionne|analyse|compare|différence|calcule|résume"
    r")\b",
    flags=re.IGNORECASE,
)


class DualModelRouter:
    """
    Routes prompts between:
    - FAST model (qwen3.5:4b) for instant everyday answers and quick PC commands
    - PRO model (qwen3.5:9b) for expert domain questions (Science, Finance, Tech, Strategy) & complex reasoning
    - LIMITLESS model (huihui_ai/qwen3.5-abliterated:9b) for unrestricted, uncensored responses
    Supports native Ollama tool calling with multi-step execution.
    """

    def __init__(self) -> None:
        self.ollama_url = settings.ollama_url.rstrip("/")
        self.fast_model = settings.fast_model
        self.pro_model = settings.pro_model
        self.limitless_model = settings.limitless_model
        self.routing_mode = settings.routing_mode  # "auto" | "fast" | "pro" | "limitless"
        self.pro_enabled = settings.pro_enabled
        self.pro_thinking = settings.pro_thinking
        self.pro_min_free_ram_gb = settings.pro_min_free_ram_gb
        self.load_persisted_settings()

    def load_persisted_settings(self) -> None:
        """Restore runtime settings from SQLite if previously saved."""
        saved = memory_store.get_all_settings()
        if saved.get("routing_mode") in ("auto", "fast", "pro", "limitless"):
            self.routing_mode = saved["routing_mode"]
        if "pro_enabled" in saved:
            self.pro_enabled = saved["pro_enabled"].lower() == "true"
        if "pro_min_free_ram_gb" in saved:
            try:
                val = float(saved["pro_min_free_ram_gb"])
                if val >= 0:
                    self.pro_min_free_ram_gb = round(val, 2)
            except ValueError:
                pass
        if "confirm_risky_actions" in saved:
            set_confirm_risky_actions(saved["confirm_risky_actions"].lower() == "true")

    def set_routing_mode(self, mode: str) -> None:
        if mode not in ("auto", "fast", "pro", "limitless"):
            raise ValueError(f"Unsupported routing mode: {mode}")
        self.routing_mode = mode
        memory_store.set_setting("routing_mode", mode)
        logger.info("Routing mode updated to '%s'", mode)

    def set_pro_enabled(self, enabled: bool) -> None:
        self.pro_enabled = enabled
        memory_store.set_setting("pro_enabled", "true" if enabled else "false")
        logger.info("Pro node enabled=%s", enabled)

    def set_pro_min_free_ram_gb(self, gb: float) -> None:
        if gb < 0:
            raise ValueError("RAM threshold cannot be negative")
        self.pro_min_free_ram_gb = round(gb, 2)
        memory_store.set_setting("pro_min_free_ram_gb", self.pro_min_free_ram_gb)
        logger.info("Pro min free RAM updated to %.2f GB", self.pro_min_free_ram_gb)

    def set_confirm_risky_actions(self, enabled: bool) -> None:
        set_confirm_risky_actions(enabled)
        memory_store.set_setting("confirm_risky_actions", "true" if enabled else "false")
        logger.info("Risky action confirmation enabled=%s", enabled)

    @staticmethod
    def _model_matches(target: str, candidates: List[str]) -> bool:
        t = target.strip().lower()
        for c in candidates:
            c_low = c.strip().lower()
            if c_low == t:
                return True
            if ":" in t and c_low.startswith(t + "-"):
                return True
            if ":" not in t and c_low == f"{t}:latest":
                return True
        return False

    @staticmethod
    def _get_top_ram_processes(limit: int = 3) -> List[str]:
        procs = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                mem_info = p.info.get("memory_info")
                mem_mb = (mem_info.rss if mem_info else 0) / (1024**2)
                if mem_mb > 50:
                    procs.append((p.info.get("name") or "unknown", mem_mb))
            except Exception:
                pass
        procs.sort(key=lambda x: x[1], reverse=True)
        return [f"{name} ({round(mb)} MB)" for name, mb in procs[:limit]]

    def detect_domain(self, user_text: str) -> str:
        """Detects the primary subject domain ('finance', 'science', 'tech', 'strategy', or 'general')."""
        for domain, pattern in DOMAIN_PATTERNS.items():
            if pattern.search(user_text):
                return domain
        return "general"

    def classify_task(self, user_text: str) -> Tuple[str, str]:
        """Returns (tier, domain) where tier is 'fast', 'pro', or 'limitless'."""
        domain = self.detect_domain(user_text)

        if self.routing_mode == "fast":
            return ("fast", domain)
        if self.routing_mode == "pro":
            return ("pro", domain)
        if self.routing_mode == "limitless":
            return ("limitless", domain)

        text = user_text.strip()
        if domain != "general":
            return ("pro", domain)
        if len(text) > 140 or "\n" in text or "```" in text or COMPLEX_TRIGGERS.search(text):
            return ("pro", domain)
        return ("fast", domain)

    def _inspect_heavy_model(
        self,
        model_name: str,
        ollama_online: bool,
        installed: List[str],
        running: List[str],
        running_models_raw: List[Dict[str, Any]],
        free_ram_gb: float,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """Compute install, load, and RAM guardrail status for Pro or Limitless models."""
        is_installed = ollama_online and self._model_matches(model_name, installed)
        is_loaded = ollama_online and self._model_matches(model_name, running)

        loaded_ram_gb = 0.0
        for m in running_models_raw:
            if self._model_matches(model_name, [m.get("name", "")]):
                loaded_ram_gb = round((m.get("size") or 0) / (1024**3), 2)
                break

        # Count free OS RAM plus any RAM already allocated to this model in Ollama.
        effective_free_ram_gb = round(free_ram_gb + loaded_ram_gb, 2)
        ram_ok = effective_free_ram_gb >= self.pro_min_free_ram_gb

        if not enabled:
            block_reason = "manually_disabled"
        elif not ollama_online:
            block_reason = "ollama_offline"
        elif not is_installed:
            block_reason = "not_installed"
        elif not ram_ok:
            block_reason = "insufficient_ram"
        else:
            block_reason = None

        return {
            "model": model_name,
            "installed": is_installed,
            "loaded": is_loaded,
            "loaded_ram_gb": loaded_ram_gb,
            "effective_free_ram_gb": effective_free_ram_gb,
            "ram_ok": ram_ok,
            "ready": block_reason is None,
            "block_reason": block_reason,
        }

    async def get_models_status(self) -> Dict[str, Any]:
        installed: List[str] = []
        running: List[str] = []
        running_models_raw: List[Dict[str, Any]] = []
        ollama_online = False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                tags_resp = await client.get(f"{self.ollama_url}/api/tags")
                if tags_resp.status_code == 200:
                    ollama_online = True
                    data = tags_resp.json()
                    installed = [m.get("name", "") for m in data.get("models", [])]

                ps_resp = await client.get(f"{self.ollama_url}/api/ps")
                if ps_resp.status_code == 200:
                    ps_data = ps_resp.json()
                    running_models_raw = ps_data.get("models", [])
                    running = [m.get("name", "") for m in running_models_raw]
        except Exception:
            ollama_online = False

        vm = psutil.virtual_memory()
        free_ram_gb = round(vm.available / (1024**3), 2)

        fast_ready = ollama_online and self._model_matches(self.fast_model, installed)
        fast_loaded = ollama_online and self._model_matches(self.fast_model, running)

        pro_status = self._inspect_heavy_model(
            model_name=self.pro_model,
            ollama_online=ollama_online,
            installed=installed,
            running=running,
            running_models_raw=running_models_raw,
            free_ram_gb=free_ram_gb,
            enabled=self.pro_enabled,
        )
        limitless_status = self._inspect_heavy_model(
            model_name=self.limitless_model,
            ollama_online=ollama_online,
            installed=installed,
            running=running,
            running_models_raw=running_models_raw,
            free_ram_gb=free_ram_gb,
            enabled=True,
        )

        return {
            "ollama_online": ollama_online,
            "routing_mode": self.routing_mode,
            "pro_enabled": self.pro_enabled,
            "confirm_risky_actions": is_confirm_risky_actions_enabled(),
            "free_ram_gb": free_ram_gb,
            "effective_free_ram_gb": pro_status["effective_free_ram_gb"],
            "pro_min_free_ram_gb": self.pro_min_free_ram_gb,
            "ram_ok": pro_status["ram_ok"],
            "fast": {
                "model": self.fast_model,
                "ready": fast_ready,
                "loaded": fast_loaded,
            },
            "pro": pro_status,
            "limitless": limitless_status,
        }

    def _build_heavy_refusal(
        self, target_tier: str, model_name: str, status: Dict[str, Any]
    ) -> str:
        tier_status = status[target_tier]
        block_reason = tier_status["block_reason"]
        tier_label = "Limitless" if target_tier == "limitless" else "Pro"

        if block_reason == "insufficient_ram":
            top_procs = self._get_top_ram_processes(limit=3)
            top_str = (
                f" Top RAM consumers: {', '.join(top_procs)}."
                if top_procs
                else ""
            )
            return (
                f"RAM Safety Guardrail triggered: Loading the {tier_label} model ({model_name}) "
                f"requires at least {self.pro_min_free_ram_gb:.2f} GB of free RAM, "
                f"but only {status['free_ram_gb']:.2f} GB is currently available on your system.{top_str} "
                f"Please close memory-heavy applications or switch to '/mode fast' to proceed safely without swapping."
            )
        if block_reason == "not_installed":
            return (
                f"The {tier_label} model ({model_name}) is not installed in Ollama. "
                f"Run 'ollama pull {model_name}' to enable {tier_label} mode."
            )
        return (
            f"This task requires the {tier_label} model ({model_name}), "
            f"which is currently offline or unavailable. "
            f"It is not possible to execute this request right now."
        )

    async def generate_with_tools(
        self, target_tier: str, messages: List[Dict[str, Any]]
    ) -> Tuple[str, str, str, int, List[Dict[str, Any]]]:
        """
        Executes the request on the selected tier ('fast', 'pro', or 'limitless') with native tool calling.
        Returns (reply_text, tier_used, model_used, latency_ms, executed_tools).
        """
        status = await self.get_models_status()
        executed_tools: List[Dict[str, Any]] = []

        if target_tier in ("pro", "limitless"):
            chosen_model = self.limitless_model if target_tier == "limitless" else self.pro_model
            if not status[target_tier]["ready"]:
                refusal = self._build_heavy_refusal(target_tier, chosen_model, status)
                return (refusal, "refused", chosen_model, 0, executed_tools)
            keep_alive = "5m"
            think_enabled = self.pro_thinking
            temperature = 0.25
        else:
            chosen_model = self.fast_model
            keep_alive = "30m"
            think_enabled = False
            temperature = 0.4

        start = time.perf_counter()
        working_messages = list(messages)
        use_tools = True
        options = {"temperature": temperature, "num_ctx": 8192}

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # Up to 3 tool-call rounds before final answer
                for _ in range(3):
                    payload: Dict[str, Any] = {
                        "model": chosen_model,
                        "messages": working_messages,
                        "stream": False,
                        "keep_alive": keep_alive,
                        "think": think_enabled,
                        "options": options,
                    }
                    if use_tools:
                        payload["tools"] = OLLAMA_TOOLS_SCHEMA
                    resp = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                    if resp.status_code == 400 and use_tools:
                        logger.warning("Model '%s' rejected tools payload (HTTP 400); retrying without tools.", chosen_model)
                        use_tools = False
                        continue
                    if resp.status_code != 200:
                        err_detail = self._extract_http_error(resp)
                        logger.error("Ollama HTTP %s on '%s': %s", resp.status_code, chosen_model, err_detail)
                        latency_ms = int((time.perf_counter() - start) * 1000)
                        return (
                            f"Local inference error on {chosen_model} (HTTP {resp.status_code}): {err_detail}",
                            "refused",
                            chosen_model,
                            latency_ms,
                            executed_tools,
                        )

                    data = resp.json()
                    msg = data.get("message", {})
                    tool_calls = msg.get("tool_calls") or []

                    if not tool_calls:
                        latency_ms = int((time.perf_counter() - start) * 1000)
                        content = (msg.get("content") or msg.get("thinking") or "").strip()
                        logger.info(
                            "Completed tier=%s model=%s latency=%dms tools=%d",
                            target_tier, chosen_model, latency_ms, len(executed_tools),
                        )
                        return (content, target_tier, chosen_model, latency_ms, executed_tools)

                    # Append the assistant's tool_calls message
                    working_messages.append(msg)

                    # Execute each requested tool off the asyncio event loop
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments", {})
                        tool_res = await asyncio.to_thread(execute_tool, fn_name, fn_args)
                        logger.info("Executed tool '%s' ok=%s", fn_name, tool_res.get("ok"))
                        executed_tools.append(
                            {
                                "name": fn_name,
                                "arguments": fn_args,
                                "result": tool_res,
                            }
                        )
                        working_messages.append(
                            {
                                "role": "tool",
                                "content": json.dumps(tool_res, ensure_ascii=False),
                            }
                        )

                # Final synthesis call without tools if max tool rounds reached
                resp = await client.post(
                    f"{self.ollama_url}/api/chat",
                    json={
                        "model": chosen_model,
                        "messages": working_messages,
                        "stream": False,
                        "keep_alive": keep_alive,
                        "think": think_enabled,
                        "options": options,
                    },
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                if resp.status_code == 200:
                    msg = resp.json().get("message", {})
                    content = (msg.get("content") or msg.get("thinking") or "").strip()
                    return (content, target_tier, chosen_model, latency_ms, executed_tools)
                err_detail = self._extract_http_error(resp)
                logger.error("Ollama synthesis HTTP %s on '%s': %s", resp.status_code, chosen_model, err_detail)
                return (
                    f"Local inference error on {chosen_model} (HTTP {resp.status_code}): {err_detail}",
                    "refused",
                    chosen_model,
                    latency_ms,
                    executed_tools,
                )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Local inference exception on '%s'", chosen_model)
            return (
                f"Local inference error on {chosen_model}: {exc}",
                "refused",
                chosen_model,
                latency_ms,
                executed_tools,
            )

    @staticmethod
    def _extract_http_error(resp: httpx.Response) -> str:
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                return str(data["error"])
        except Exception:
            pass
        return (resp.text or resp.reason_phrase or "Unknown error").strip()[:300]


model_router = DualModelRouter()
