import platform
import re
from datetime import datetime
from typing import Any, Dict, List
import psutil
from app.core.memory import memory_store
from app.core.persona import build_evris_persona
from app.core.router import model_router
from app.tools.registry import execute_tool


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
    def _run_direct_hooks(self, user_text: str) -> List[Dict[str, Any]]:
        """Deterministic pre-hooks for explicit memory saving so even the 3B Fast model never misses them."""
        hooks: List[Dict[str, Any]] = []
        mem_match = re.search(
            r"^(?:evris[,\s]+)?(?:please\s+)?(?:remember that|memorize that|note that|retiens que|souviens-toi que|mémorise que)\s+(.+)$",
            user_text.strip(),
            flags=re.IGNORECASE,
        )
        if mem_match:
            fact = mem_match.group(1).strip()
            res = execute_tool("save_memory", {"category": "user_fact", "content": fact})
            hooks.append(
                {
                    "name": "save_memory",
                    "arguments": {"category": "user_fact", "content": fact},
                    "result": res,
                }
            )
        return hooks

    async def chat(self, user_text: str) -> Dict[str, Any]:
        user_msg = memory_store.add_message(role="user", content=user_text)
        pre_tools = self._run_direct_hooks(user_text)

        target_tier, domain = model_router.classify_task(user_text)
        telemetry = get_system_telemetry()
        memories = memory_store.get_memories(limit=30)

        system_prompt = build_evris_persona(
            tier=target_tier,
            domain=domain,
            telemetry=telemetry,
            memories=memories,
        )

        history = memory_store.get_recent_messages(limit=12)
        llm_messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        for msg in history:
            if msg["role"] in ("user", "assistant"):
                llm_messages.append({"role": msg["role"], "content": msg["content"]})

        if pre_tools:
            summaries = [t["result"].get("summary", "") for t in pre_tools]
            llm_messages.append(
                {
                    "role": "system",
                    "content": f"System action already executed: {'; '.join(summaries)}. Confirm briefly.",
                }
            )

        (
            reply_text,
            tier_used,
            model_used,
            latency_ms,
            llm_tools,
        ) = await model_router.generate_with_tools(
            target_tier=target_tier, messages=llm_messages
        )

        all_tools = pre_tools + llm_tools

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
            "executed_tools": all_tools,
        }


evris_agent = EvrisAgent()
