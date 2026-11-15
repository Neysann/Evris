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
    pro_state = f"{GREEN}ONLINE{RESET}" if status["pro_enabled"] else f"{RED}OFFLINE{RESET}"

    print(f"\n{CYAN}{BOLD}============================================================{RESET}")
    print(f"{CYAN}{BOLD}   E.V.R.I.S. — Terminal Interface (Phase 1 Dual-Model){RESET}")
    print(f"{CYAN}{BOLD}============================================================{RESET}")
    print(
        f" {DIM}System:{RESET} CPU {telemetry['cpu_percent']}% | "
        f"RAM {telemetry['ram_used_gb']}/{telemetry['ram_total_gb']} GB ({telemetry['ram_free_gb']} GB free)"
    )
    print(
        f" {DIM}Models:{RESET} FAST={CYAN}{status['fast']['model']}{RESET} | "
        f"PRO={AMBER}{status['pro']['model']}{RESET} ({pro_state}) | "
        f"Mode={BOLD}{status['routing_mode'].upper()}{RESET}"
    )
    print(f"{DIM}------------------------------------------------------------{RESET}")
    print(f" {DIM}Commands:{RESET}")
    print(f"   {CYAN}/mode auto|fast|pro{RESET}  - Switch routing mode")
    print(f"   {CYAN}/pro on|off{RESET}          - Toggle Pro model availability (test refusal)")
    print(f"   {CYAN}/status{RESET}              - Show system & model status")
    print(f"   {CYAN}/clear{RESET}               - Clear conversation memory")
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
            parts = user_input.lower().split()
            cmd = parts[0]

            if cmd in ("/exit", "/quit"):
                print(f"{DIM}Shutting down Evris.{RESET}")
                break
            elif cmd == "/clear":
                memory_store.clear_messages()
                print(f"{GREEN}✓ Conversation memory cleared.{RESET}\n")
                continue
            elif cmd == "/status":
                await print_banner()
                continue
            elif cmd == "/mode" and len(parts) > 1 and parts[1] in ("auto", "fast", "pro"):
                model_router.routing_mode = parts[1]
                print(f"{GREEN}✓ Routing mode set to: {parts[1].upper()}{RESET}\n")
                continue
            elif cmd == "/pro" and len(parts) > 1 and parts[1] in ("on", "off"):
                model_router.pro_enabled = parts[1] == "on"
                state_str = f"{GREEN}ONLINE{RESET}" if model_router.pro_enabled else f"{RED}OFFLINE{RESET}"
                print(f"✓ Pro Node state set to: {state_str}\n")
                continue
            else:
                print(f"{RED}Unknown command. Use /mode auto|fast|pro, /pro on|off, /status, /clear, or /exit.{RESET}\n")
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

        if tier == "fast":
            badge = f"{CYAN}[FAST • {domain_tag} • {model} • {latency} ms]{RESET}"
        elif tier == "pro":
            badge = f"{AMBER}[PRO • {domain_tag} • {model} • {latency} ms]{RESET}"
        else:
            badge = f"{RED}[REFUSED • {domain_tag} • {model} OFFLINE]{RESET}"

        print(f"\n{BOLD}EVRIS{RESET} {badge}\n{reply}\n")


def main() -> None:
    asyncio.run(repl())


if __name__ == "__main__":
    main()
