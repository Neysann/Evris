import json
import re
import time
from typing import Any, Dict, List, Tuple
import httpx
import psutil
from app.config import settings
from app.tools.registry import OLLAMA_TOOLS_SCHEMA, execute_tool

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
    - FAST model (qwen2.5:3b) for instant everyday answers and quick PC commands
    - PRO model (qwen2.5:7b) for expert domain questions (Science, Finance, Tech, Strategy) & complex reasoning
    Supports native Ollama tool calling with multi-step execution.
    """

    def __init__(self) -> None:
        self.ollama_url = settings.ollama_url.rstrip("/")
        self.fast_model = settings.fast_model
        self.pro_model = settings.pro_model
        self.routing_mode = settings.routing_mode  # "auto" | "fast" | "pro"
        self.pro_enabled = settings.pro_enabled
        self.pro_min_free_ram_gb = settings.pro_min_free_ram_gb

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
        """Returns (tier, domain) where tier is 'fast' or 'pro'."""
        domain = self.detect_domain(user_text)

        if self.routing_mode == "fast":
            return ("fast", domain)
        if self.routing_mode == "pro":
            return ("pro", domain)

        text = user_text.strip()
        if domain != "general":
            return ("pro", domain)
        if len(text) > 140 or "\n" in text or "```" in text or COMPLEX_TRIGGERS.search(text):
            return ("pro", domain)
        return ("fast", domain)

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

        pro_installed = ollama_online and self._model_matches(self.pro_model, installed)
        pro_loaded = ollama_online and self._model_matches(self.pro_model, running)

        pro_loaded_ram_gb = 0.0
        for m in running_models_raw:
            if self._model_matches(self.pro_model, [m.get("name", "")]):
                pro_loaded_ram_gb = round((m.get("size") or 0) / (1024**3), 2)
                break

        # RAM Safety Guardrail:
        # Count free OS RAM plus any RAM already allocated to the loaded Pro model in Ollama.
        effective_free_ram_gb = round(free_ram_gb + pro_loaded_ram_gb, 2)
        ram_ok = effective_free_ram_gb >= self.pro_min_free_ram_gb

        if not self.pro_enabled:
            block_reason = "manually_disabled"
        elif not ollama_online:
            block_reason = "ollama_offline"
        elif not pro_installed:
            block_reason = "not_installed"
        elif not ram_ok:
            block_reason = "insufficient_ram"
        else:
            block_reason = None

        pro_ready = block_reason is None

        return {
            "ollama_online": ollama_online,
            "routing_mode": self.routing_mode,
            "pro_enabled": self.pro_enabled,
            "free_ram_gb": free_ram_gb,
            "effective_free_ram_gb": effective_free_ram_gb,
            "pro_min_free_ram_gb": self.pro_min_free_ram_gb,
            "ram_ok": ram_ok,
            "fast": {
                "model": self.fast_model,
                "ready": fast_ready,
                "loaded": fast_loaded,
            },
            "pro": {
                "model": self.pro_model,
                "installed": pro_installed,
                "loaded": pro_loaded,
                "loaded_ram_gb": pro_loaded_ram_gb,
                "ram_ok": ram_ok,
                "ready": pro_ready,
                "block_reason": block_reason,
            },
        }

    async def generate_with_tools(
        self, target_tier: str, messages: List[Dict[str, Any]]
    ) -> Tuple[str, str, str, int, List[Dict[str, Any]]]:
        """
        Executes the request on the selected tier ('fast' or 'pro') with native tool calling.
        Returns (reply_text, tier_used, model_used, latency_ms, executed_tools).
        """
        status = await self.get_models_status()
        executed_tools: List[Dict[str, Any]] = []

        if target_tier == "pro":
            if not status["pro"]["ready"]:
                block_reason = status["pro"]["block_reason"]
                if block_reason == "insufficient_ram":
                    top_procs = self._get_top_ram_processes(limit=3)
                    top_str = (
                        f" Top RAM consumers: {', '.join(top_procs)}."
                        if top_procs
                        else ""
                    )
                    refusal = (
                        f"RAM Safety Guardrail triggered: Loading the Pro model ({self.pro_model}) "
                        f"requires at least {self.pro_min_free_ram_gb:.2f} GB of free RAM, "
                        f"but only {status['free_ram_gb']:.2f} GB is currently available on your system.{top_str} "
                        f"Please close memory-heavy applications or switch to '/mode fast' to proceed safely without swapping."
                    )
                else:
                    refusal = (
                        f"This complex task requires the Pro model ({self.pro_model}), "
                        f"which is currently offline or unavailable. "
                        f"It is not possible to execute this request right now."
                    )
                return (refusal, "refused", self.pro_model, 0, executed_tools)
            chosen_model = self.pro_model
            keep_alive = "5m"
        else:
            chosen_model = self.fast_model
            keep_alive = "30m"

        start = time.perf_counter()
        working_messages = list(messages)

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                # Up to 3 tool-call rounds before final answer
                for _ in range(3):
                    payload: Dict[str, Any] = {
                        "model": chosen_model,
                        "messages": working_messages,
                        "tools": OLLAMA_TOOLS_SCHEMA,
                        "stream": False,
                        "keep_alive": keep_alive,
                        "options": {
                            "temperature": 0.25 if target_tier == "pro" else 0.4,
                        },
                    }
                    resp = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                    if resp.status_code != 200:
                        break

                    data = resp.json()
                    msg = data.get("message", {})
                    tool_calls = msg.get("tool_calls") or []

                    if not tool_calls:
                        latency_ms = int((time.perf_counter() - start) * 1000)
                        content = msg.get("content", "").strip()
                        return (content, target_tier, chosen_model, latency_ms, executed_tools)

                    # Append the assistant's tool_calls message
                    working_messages.append(msg)

                    # Execute each requested tool
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments", {})
                        tool_res = execute_tool(fn_name, fn_args)
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
                    },
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                if resp.status_code == 200:
                    content = resp.json().get("message", {}).get("content", "").strip()
                    return (content, target_tier, chosen_model, latency_ms, executed_tools)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return (
                f"Local inference error on {chosen_model}: {exc}",
                "refused",
                chosen_model,
                latency_ms,
                executed_tools,
            )

        return (
            f"Unable to reach local Ollama engine for {chosen_model}.",
            "refused",
            chosen_model,
            0,
            executed_tools,
        )


model_router = DualModelRouter()
