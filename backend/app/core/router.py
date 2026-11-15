import re
import time
from typing import Any, Dict, List, Tuple
import httpx
import psutil
from app.config import settings

DOMAIN_PATTERNS = {
    "finance": re.compile(
        r"\b("
        r"finance|financial|stock|stocks|market|markets|invest|investing|investment|portfolio|bond|bonds|"
        r"inflation|interest rate|fed|ecb|gdp|economy|economic|macroeconomics|valuation|dcf|ebitda|equity|"
        r"dividend|crypto|bitcoin|trading|option|options|hedge|yield|risk|asset|capital|bourse|action|actions|"
        r"investissement|portefeuille|taux|économie|économique|rendement|obligation|valorisation"
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
    r"evaluate|calculate|solve|optimize|explique|pourquoi|comment fonctionne|analyse|compare|différence|calcule"
    r")\b",
    flags=re.IGNORECASE,
)


class DualModelRouter:
    """
    Routes prompts between:
    - FAST model (qwen2.5:3b) for instant everyday answers and quick commands
    - PRO model (qwen2.5:7b) for expert domain questions (Science, Finance, Tech, Strategy) & complex reasoning
    If a task requires PRO and PRO is offline/unavailable, explicitly tells the user it is not possible.
    """

    def __init__(self) -> None:
        self.ollama_url = settings.ollama_url.rstrip("/")
        self.fast_model = settings.fast_model
        self.pro_model = settings.pro_model
        self.routing_mode = settings.routing_mode  # "auto" | "fast" | "pro"
        self.pro_enabled = settings.pro_enabled

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
        # Any specialist domain (Finance, Science, Tech, Strategy) or analytical query uses the PRO brain
        if domain != "general":
            return ("pro", domain)
        if len(text) > 140 or "\n" in text or "```" in text or COMPLEX_TRIGGERS.search(text):
            return ("pro", domain)
        return ("fast", domain)

    async def get_models_status(self) -> Dict[str, Any]:
        installed: List[str] = []
        ollama_online = False
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.ollama_url}/api/tags")
                if resp.status_code == 200:
                    ollama_online = True
                    data = resp.json()
                    installed = [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            ollama_online = False

        vm = psutil.virtual_memory()
        free_ram_gb = round(vm.available / (1024**3), 2)

        fast_ready = ollama_online and any(
            m == self.fast_model or m.startswith(self.fast_model.split(":")[0])
            for m in installed
        )
        pro_installed = ollama_online and any(
            m == self.pro_model or m.startswith(self.pro_model.split(":")[0])
            for m in installed
        )
        pro_ready = self.pro_enabled and pro_installed

        return {
            "ollama_online": ollama_online,
            "routing_mode": self.routing_mode,
            "pro_enabled": self.pro_enabled,
            "free_ram_gb": free_ram_gb,
            "fast": {
                "model": self.fast_model,
                "ready": fast_ready,
            },
            "pro": {
                "model": self.pro_model,
                "installed": pro_installed,
                "ready": pro_ready,
            },
        }

    async def generate(
        self, target_tier: str, messages: List[Dict[str, str]]
    ) -> Tuple[str, str, str, int]:
        """
        Executes the request on the selected tier ('fast' or 'pro').
        Returns (reply_text, tier_used, model_used, latency_ms).
        """
        status = await self.get_models_status()

        # Strict policy: if the task requires the PRO model, verify PRO is available
        if target_tier == "pro":
            if not self.pro_enabled or not status["pro"]["ready"]:
                refusal = (
                    f"This complex task requires the Pro model ({self.pro_model}), "
                    f"which is currently offline or unavailable. "
                    f"It is not possible to execute this request right now."
                )
                return (refusal, "refused", self.pro_model, 0)
            chosen_model = self.pro_model
            keep_alive = "5m"
        else:
            chosen_model = self.fast_model
            keep_alive = "30m"

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                payload = {
                    "model": chosen_model,
                    "messages": messages,
                    "stream": False,
                    "keep_alive": keep_alive,
                    "options": {
                        "temperature": 0.25 if target_tier == "pro" else 0.4,
                    },
                }
                resp = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                latency_ms = int((time.perf_counter() - start) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "").strip()
                    return (content, target_tier, chosen_model, latency_ms)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return (
                f"Local inference error on {chosen_model}: {exc}",
                "refused",
                chosen_model,
                latency_ms,
            )

        return (
            f"Unable to reach local Ollama engine for {chosen_model}.",
            "refused",
            chosen_model,
            0,
        )


model_router = DualModelRouter()
