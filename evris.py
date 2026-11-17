import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
VENV_PYTHON = BACKEND_DIR / "venv" / "Scripts" / "python.exe"

# Automatically switch to the project's virtual environment if invoked with system Python
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    res = subprocess.run([str(VENV_PYTHON), str(__file__), *sys.argv[1:]])
    sys.exit(res.returncode)

sys.path.insert(0, str(BACKEND_DIR))

from app.core.agent import evris_agent, get_system_telemetry  # noqa: E402
from app.core.memory import memory_store  # noqa: E402
from app.core.router import model_router  # noqa: E402
from app.tools.registry import OLLAMA_TOOLS_SCHEMA  # noqa: E402

CYAN = "\033[96m"
AMBER = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
DIM = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ensure_ollama_running() -> None:
    ollama_exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if not ollama_exe.exists():
        return
    try:
        out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq ollama.exe"], text=True)
        if "ollama.exe" not in out.lower():
            subprocess.Popen(
                [str(ollama_exe), "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
    except Exception:
        pass


async def print_banner() -> None:
    status = await model_router.get_models_status()
    telemetry = get_system_telemetry()
    mem_count = len(memory_store.get_memories(limit=100))

    pro_info = status["pro"]
    if pro_info["ready"]:
        pro_sub = "LOADED" if pro_info.get("loaded") else "RAM OK"
        pro_state = f"{GREEN}ONLINE • {pro_sub}{RESET}"
    elif pro_info.get("block_reason") == "insufficient_ram":
        pro_state = f"{RED}BLOCKED • LOW RAM (<{status['pro_min_free_ram_gb']} GB){RESET}"
    else:
        pro_state = f"{RED}OFFLINE{RESET}"

    ram_guard_color = GREEN if status["ram_ok"] else RED
    ram_guard_label = (
        f"{ram_guard_color}{telemetry['ram_free_gb']} GB free "
        f"(Guardrail >= {status['pro_min_free_ram_gb']} GB){RESET}"
    )

    print(f"\n{CYAN}{BOLD}============================================================{RESET}")
    print(f"{CYAN}{BOLD}   E.V.R.I.S. — Terminal Interface (Dual-Model + Tools){RESET}")
    print(f"{CYAN}{BOLD}============================================================{RESET}")
    print(
        f" {DIM}System:{RESET} CPU {telemetry['cpu_percent']}% | "
        f"RAM {telemetry['ram_used_gb']}/{telemetry['ram_total_gb']} GB | {ram_guard_label}"
    )
    print(
        f" {DIM}Models:{RESET} FAST={CYAN}{status['fast']['model']}{RESET} | "
        f"PRO={AMBER}{status['pro']['model']}{RESET} ({pro_state}) | "
        f"Mode={BOLD}{status['routing_mode'].upper()}{RESET} | "
        f"Memories={BOLD}{mem_count}{RESET}"
    )
    print(f"{DIM}------------------------------------------------------------{RESET}")
    print(f" {DIM}Commands:{RESET}")
    print(f"   {CYAN}/mode auto|fast|pro{RESET}  - Switch routing mode")
    print(f"   {CYAN}/pro on|off{RESET}          - Toggle Pro model availability (test refusal)")
    print(f"   {CYAN}/ram [gb]{RESET}            - Check or set Pro RAM safety threshold (e.g. /ram 3.0)")
    print(f"   {CYAN}/memories{RESET}            - List saved long-term facts")
    print(f"   {CYAN}/forget <id|all>{RESET}     - Delete a saved memory (or all)")
    print(f"   {CYAN}/tools{RESET}               - List autonomous agent tools")
    print(f"   {CYAN}/status{RESET}              - Show system & model status")
    print(f"   {CYAN}/clear{RESET}               - Clear conversation history")
    print(f"   {CYAN}/exit{RESET}                - Quit Evris")
    print(f"{CYAN}{BOLD}============================================================{RESET}\n")


async def repl() -> None:
    os.system("")  # Enable ANSI colors on Windows console
    ensure_ollama_running()
    await print_banner()

    while True:
        try:
            user_input = input(f"{BOLD}You > {RESET}").lstrip("\ufeff").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Shutting down Evris.{RESET}")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            parts = user_input.split()
            cmd = parts[0].lower()

            if cmd in ("/exit", "/quit"):
                print(f"{DIM}Shutting down Evris.{RESET}")
                break
            elif cmd == "/clear":
                memory_store.clear_messages()
                print(f"{GREEN}✓ Conversation history cleared (long-term memories preserved).{RESET}\n")
                continue
            elif cmd == "/status":
                await print_banner()
                continue
            elif cmd == "/memories":
                items = memory_store.get_memories(limit=50)
                if not items:
                    print(f"{DIM}No long-term memories saved yet. Try saying: 'Remember that my target return is 12%'{RESET}\n")
                else:
                    print(f"\n{CYAN}{BOLD}Long-Term Memories ({len(items)}):{RESET}")
                    for m in items:
                        print(f"  {AMBER}#{m['id']}{RESET} [{m['category']}] {m['content']} {DIM}({m['created_at']}){RESET}")
                    print()
                continue
            elif cmd == "/forget" and len(parts) > 1:
                target = parts[1].lower()
                if target == "all":
                    memory_store.clear_memories()
                    print(f"{GREEN}✓ All long-term memories cleared.{RESET}\n")
                elif target.isdigit():
                    ok = memory_store.delete_memory(int(target))
                    if ok:
                        print(f"{GREEN}✓ Memory #{target} deleted.{RESET}\n")
                    else:
                        print(f"{RED}Memory #{target} not found.{RESET}\n")
                else:
                    print(f"{RED}Usage: /forget <id> or /forget all{RESET}\n")
                continue
            elif cmd == "/tools":
                print(f"\n{CYAN}{BOLD}Available Autonomous Tools ({len(OLLAMA_TOOLS_SCHEMA)}):{RESET}")
                for t in OLLAMA_TOOLS_SCHEMA:
                    fn = t["function"]
                    print(f"  • {GREEN}{fn['name']}{RESET}: {fn['description']}")
                print()
                continue
            elif cmd == "/mode" and len(parts) > 1 and parts[1].lower() in ("auto", "fast", "pro"):
                mode_val = parts[1].lower()
                model_router.routing_mode = mode_val
                print(f"{GREEN}✓ Routing mode set to: {mode_val.upper()}{RESET}\n")
                continue
            elif cmd == "/pro" and len(parts) > 1 and parts[1].lower() in ("on", "off"):
                model_router.pro_enabled = parts[1].lower() == "on"
                state_str = f"{GREEN}ONLINE{RESET}" if model_router.pro_enabled else f"{RED}OFFLINE{RESET}"
                print(f"✓ Pro Node state set to: {state_str}\n")
                continue
            elif cmd == "/ram":
                if len(parts) > 1:
                    try:
                        val = float(parts[1])
                        if val < 0:
                            raise ValueError
                        model_router.pro_min_free_ram_gb = round(val, 2)
                        print(
                            f"{GREEN}✓ Pro RAM safety guardrail set to >= {model_router.pro_min_free_ram_gb:.2f} GB free RAM.{RESET}\n"
                        )
                    except ValueError:
                        print(f"{RED}Usage: /ram [gb] (e.g. /ram 3.0 or /ram 12.0 to test low-RAM refusal){RESET}\n")
                else:
                    status = await model_router.get_models_status()
                    ok_str = f"{GREEN}PASS{RESET}" if status["ram_ok"] else f"{RED}BLOCKED (LOW RAM){RESET}"
                    loaded_str = "Yes (already in RAM)" if status["pro"]["loaded"] else "No (on standby)"
                    print(
                        f"\n{CYAN}{BOLD}RAM Safety Guardrail Status:{RESET}\n"
                        f"  • Free System RAM : {BOLD}{status['free_ram_gb']:.2f} GB{RESET}\n"
                        f"  • Pro Min Required: {BOLD}{status['pro_min_free_ram_gb']:.2f} GB{RESET}\n"
                        f"  • Pro Model Loaded: {loaded_str}\n"
                        f"  • Guardrail Check : {ok_str}\n"
                    )
                continue
            else:
                print(
                    f"{RED}Unknown command. Use /mode, /pro, /ram, /memories, /forget, /tools, /status, /clear, or /exit.{RESET}\n"
                )
                continue

        # Preview which model & specialist domain the router selected before inference starts
        predicted_tier, domain = model_router.classify_task(user_input)
        domain_tag = domain.upper()
        tier_label = (
            f"{CYAN}FAST [{domain_tag}] ({model_router.fast_model}){RESET}"
            if predicted_tier == "fast"
            else f"{AMBER}PRO [{domain_tag}] ({model_router.pro_model}){RESET}"
        )
        print(f"{DIM}→ Routing to {tier_label}...{RESET}")

        result = await evris_agent.chat(user_input)
        tier = result["tier_used"]
        model = result["model_used"]
        latency = result["latency_ms"]
        reply = result["assistant_message"]["content"]
        executed_tools = result.get("executed_tools") or []

        for tool_call in executed_tools:
            t_name = tool_call["name"]
            t_res = tool_call["result"]
            summary = t_res.get("summary") or t_res.get("error") or "Done"
            status_color = GREEN if t_res.get("ok") else RED
            print(f"  {status_color}⚡ Tool [{t_name}]: {summary}{RESET}")

        if tier == "fast":
            badge = f"{CYAN}[FAST • {domain_tag} • {model} • {latency} ms]{RESET}"
        elif tier == "pro":
            badge = f"{AMBER}[PRO • {domain_tag} • {model} • {latency} ms]{RESET}"
        else:
            reason_tag = "LOW RAM" if "RAM Safety Guardrail" in reply else "OFFLINE"
            badge = f"{RED}[REFUSED • {domain_tag} • {model} {reason_tag}]{RESET}"

        print(f"\n{BOLD}EVRIS{RESET} {badge}\n{reply}\n")


def main() -> None:
    asyncio.run(repl())


if __name__ == "__main__":
    main()
