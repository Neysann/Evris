import platform
from datetime import datetime
from typing import Any, Dict, List
import psutil
from app.core.memory import memory_store
from app.core.persona import build_evris_persona
from app.core.router import model_router


def get_system_telemetry() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.1)
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu_percent": round(cpu_percent, 1),
        "ram_used_gb": round(vm.used / (1024**3), 2),
        "ram_total_gb": round(vm.total / (1024**3), 2),
        "ram_free_gb": round(vm.available / (1024**3), 2),
        "ram_percent": round(vm.percent, 1),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }


class EvrisAgent:
    async def chat(self, user_text: str) -> Dict[str, Any]:
        user_msg = memory_store.add_message(role="user", content=user_text)

        target_tier, domain = model_router.classify_task(user_text)
        telemetry = get_system_telemetry()
        system_prompt = build_evris_persona(
            tier=target_tier, domain=domain, telemetry=telemetry
        )

        history = memory_store.get_recent_messages(limit=12)
        llm_messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]
        for msg in history:
            if msg["role"] in ("user", "assistant"):
                llm_messages.append({"role": msg["role"], "content": msg["content"]})

        reply_text, tier_used, model_used, latency_ms = await model_router.generate(
            target_tier=target_tier, messages=llm_messages
        )

        assistant_msg = memory_store.add_message(
            role="assistant",
            content=reply_text,
            tier_used=tier_used,
            model_used=model_used,
            latency_ms=latency_ms,
        )

        return {
            "user_message": user_msg,
            "assistant_message": assistant_msg,
            "tier_used": tier_used,
            "domain": domain,
            "model_used": model_used,
            "latency_ms": latency_ms,
        }


evris_agent = EvrisAgent()
