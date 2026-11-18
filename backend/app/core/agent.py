import asyncio
import platform
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import psutil
from app.core.logging_config import get_logger
from app.core.memory import memory_store
from app.core.persona import build_evris_persona
from app.core.router import model_router
from app.tools.registry import execute_tool

logger = get_logger(__name__)


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
        """Deterministic pre-hooks for explicit memory saving and exact math evaluation."""
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

        # Extract explicit math expression if user asks to calculate one
        math_match = re.search(
            r"(?:calculate|compute|calcule|eval)\s+([0-9\.\+\-\*\/\(\)\^\s]{3,})$",
            user_text.strip(),
            flags=re.IGNORECASE,
        )
        if math_match:
            expr = math_match.group(1).strip()
            res = execute_tool("calculate_math", {"expression": expr})
            if res.get("ok"):
                hooks.append(
                    {
                        "name": "calculate_math",
                        "arguments": {"expression": expr},
                        "result": res,
                    }
                )
        return hooks

    async def chat(
        self,
        user_text: str,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        user_msg = memory_store.add_message(role="user", content=user_text)
        pre_tools = await asyncio.to_thread(self._run_direct_hooks, user_text)
        for hook_tool in pre_tools:
            await model_router._emit_event(on_event, {"type": "tool_end", **hook_tool})

        target_tier, domain = model_router.classify_task(user_text)
        logger.info("Chat routed tier=%s domain=%s chars=%d", target_tier, domain, len(user_text))
        telemetry = await asyncio.to_thread(get_system_telemetry)
        memories = memory_store.get_memories(limit=30)

        system_prompt = build_evris_persona(
            tier=target_tier,
            domain=domain,
            telemetry=telemetry,
            memories=memories,
        )

        is_french = bool(
            re.search(
                r"[éèêàùçîô]|(\b(je|tu|il|elle|nous|vous|est|es|suis|qui|quoi|comment|pourquoi|salut|bonjour|merci|quels|quelle)\b)",
                user_text,
                flags=re.IGNORECASE,
            )
        )
        priming = (
            [
                {"role": "user", "content": "Qui es-tu ?"},
                {
                    "role": "assistant",
                    "content": "Je suis EVRIS, votre intelligence artificielle locale. Tous les systèmes sont opérationnels.",
                },
            ]
            if is_french
            else [
                {"role": "user", "content": "Hey, you online?"},
                {
                    "role": "assistant",
                    "content": "Very much so. Systems are nominal—what are we working on?",
                },
            ]
        )

        history = memory_store.get_recent_messages(limit=12)
        llm_messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *priming,
        ]
        for msg in history:
            if msg["role"] in ("user", "assistant"):
                llm_messages.append({"role": msg["role"], "content": msg["content"]})

        if pre_tools:
            summaries = [t["result"].get("summary", "") for t in pre_tools]
            llm_messages.append(
                {
                    "role": "system",
                    "content": f"Verified tool result: {'; '.join(summaries)}. State this result directly to the user in your EVRIS voice.",
                }
            )

        (
            reply_text,
            tier_used,
            model_used,
            latency_ms,
            llm_tools,
        ) = await model_router.generate_with_tools(
            target_tier=target_tier, messages=llm_messages, on_event=on_event
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
