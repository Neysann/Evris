import asyncio
import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
VENV_PYTHON = BACKEND_DIR / "venv" / "Scripts" / "python.exe"

# Automatically switch to the project's virtual environment if invoked with system Python
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    res = subprocess.run([str(VENV_PYTHON), str(__file__), *sys.argv[1:]])
    sys.exit(res.returncode)

sys.path.insert(0, str(BACKEND_DIR))


def _enable_windows_vt100() -> None:
    """Enable Windows ANSI/VT100 processing BEFORE creating Rich Console."""
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        for std_handle in (-11, -12):  # stdout, stderr
            handle = kernel32.GetStdHandle(std_handle)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass
    if sys.stdout.isatty():
        os.system("")


_enable_windows_vt100()

import psutil  # noqa: E402
from rich import box  # noqa: E402
from rich.console import Console, ConsoleOptions, Group, RenderResult  # noqa: E402
from rich.live import Live  # noqa: E402
from rich.markdown import Markdown  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.spinner import Spinner  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

from app.core.agent import evris_agent, get_system_telemetry  # noqa: E402
from app.core.logging_config import setup_logging  # noqa: E402
from app.core.memory import memory_store  # noqa: E402
from app.core.router import model_router  # noqa: E402
from app.tools.pc_control import set_confirmation_handler  # noqa: E402
from app.tools.registry import OLLAMA_TOOLS_SCHEMA  # noqa: E402

console = Console()

TIER_STYLES: Dict[str, str] = {
    "fast": "cyan",
    "pro": "yellow",
    "limitless": "magenta",
    "refused": "red",
}


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


class LiveTurnDisplay:
    """Dynamic 12 FPS Rich renderable: animated spinner, elapsed timer, tok/s, tools, and live Markdown."""

    def __init__(self, predicted_tier: str, domain: str, model_name: str) -> None:
        self.tier = predicted_tier
        self.domain = domain.upper()
        self.model = model_name
        self.status_text = f"Checking Ollama & RAM guardrail for {predicted_tier.upper()}..."
        self.active_tool: Optional[str] = None
        self.tool_logs: List[Tuple[str, bool, str]] = []
        self.stream_text = ""
        self.token_count = 0
        self.started_at = time.perf_counter()
        self.first_token_at: Optional[float] = None
        self.finished = False
        self.latency_ms = 0
        self._last_sys_sample = 0.0
        self._sys_snap = ""
        self._lock = threading.RLock()
        self._live: Optional[Live] = None
        self._paused = False
        self._spinner = Spinner("dots", style=self._border_style())
        psutil.cpu_percent(interval=None)  # prime non-blocking CPU delta

    def _border_style(self) -> str:
        return TIER_STYLES.get(self.tier, "cyan")

    def _sample_system(self, now: float) -> str:
        if now - self._last_sys_sample >= 1.0 or not self._sys_snap:
            cpu = psutil.cpu_percent(interval=None)
            free_gb = psutil.virtual_memory().available / (1024**3)
            self._sys_snap = f"CPU {cpu:.0f}% • RAM {free_gb:.1f} GB free"
            self._last_sys_sample = now
        return self._sys_snap

    def _tok_per_sec(self, now: float) -> float:
        if not self.first_token_at or self.token_count <= 1:
            return 0.0
        gen_elapsed = max(0.05, now - self.first_token_at)
        return self.token_count / gen_elapsed

    def render(self) -> Group:
        now = time.perf_counter()
        elapsed_s = now - self.started_at
        sys_info = self._sample_system(now)
        color = self._border_style()
        parts: List[Any] = []

        for t_name, ok, summary in self.tool_logs:
            icon = "⚡" if ok else "✖"
            t_color = "green" if ok else "red"
            parts.append(Text.from_markup(f"  [{t_color}]{icon} Tool [{t_name}]:[/{t_color}] {summary}"))

        if not self.finished:
            if self.active_tool:
                spinner_msg = (
                    f"[yellow]Running tool [bold]{self.active_tool}[/bold][/yellow] "
                    f"[dim]({elapsed_s:.1f}s • {sys_info})[/dim]"
                )
            elif self.stream_text:
                tps = self._tok_per_sec(now)
                tps_str = f" • {tps:.0f} tok/s" if tps > 0 else ""
                spinner_msg = (
                    f"[{color}]Streaming {self.tier.upper()} [{self.domain}] • {self.model}[/{color}] "
                    f"[dim]({self.token_count} chunks{tps_str} • {elapsed_s:.1f}s)[/dim]"
                )
            else:
                spinner_msg = f"[{color}]{self.status_text}[/{color}] [dim]({elapsed_s:.1f}s • {sys_info})[/dim]"

            self._spinner.text = Text.from_markup(spinner_msg)
            self._spinner.style = color
            parts.append(self._spinner)

        if self.stream_text or self.finished:
            title = f"[bold {color}]EVRIS[/bold {color}] [dim]• {self.tier.upper()} • {self.domain}[/dim]"
            if self.finished:
                subtitle = f"[dim]{self.model} • {self.latency_ms} ms[/dim]"
            else:
                tps = self._tok_per_sec(now)
                tps_str = f" • {tps:.0f} tok/s" if tps > 0 else ""
                subtitle = f"[dim]{self.model}{tps_str} • {elapsed_s:.1f}s[/dim]"
            body = Markdown(self.stream_text or "...")
            parts.append(
                Panel(
                    body,
                    title=title,
                    subtitle=subtitle,
                    title_align="left",
                    subtitle_align="right",
                    border_style=color,
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )

        return Group(*parts)

    def __rich_console__(self, _console: Console, _options: ConsoleOptions) -> RenderResult:
        with self._lock:
            rendered = self.render()
        yield rendered

    def start(self) -> None:
        live = Live(
            self,
            console=console,
            refresh_per_second=12,
            vertical_overflow="visible",
        )
        with self._lock:
            self._live = live
        live.start()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
            live = self._live
        if live is not None:
            live.stop()

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            live = self._live if not self.finished else None
        if live is not None:
            live.start()
            live.refresh()

    def handle_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            etype = event.get("type")
            if etype == "status":
                self.status_text = event.get("message") or self.status_text
            elif etype == "tool_start":
                self.active_tool = event.get("name", "tool")
            elif etype == "tool_end":
                self.active_tool = None
                res = event.get("result") or {}
                summary = res.get("summary") or res.get("error") or "Done"
                self.tool_logs.append((event.get("name", "tool"), bool(res.get("ok")), str(summary)))
            elif etype == "token":
                if self.first_token_at is None:
                    self.first_token_at = time.perf_counter()
                self.token_count += 1
                self.stream_text = event.get("text", "")

            live = self._live
            paused = self._paused

        if live is not None and not paused:
            live.refresh()

    def finish(
        self,
        tier_used: str,
        model_used: str,
        latency_ms: int,
        final_reply: str,
        executed_tools: List[Dict[str, Any]],
    ) -> None:
        with self._lock:
            self.tier = tier_used
            self.model = model_used
            self.latency_ms = latency_ms
            self.active_tool = None
            self.finished = True
            if final_reply:
                self.stream_text = final_reply
            if not self.tool_logs and executed_tools:
                for tc in executed_tools:
                    res = tc.get("result") or {}
                    summary = res.get("summary") or res.get("error") or "Done"
                    self.tool_logs.append((tc.get("name", "tool"), bool(res.get("ok")), str(summary)))
            live = self._live
            self._live = None

        if live is not None:
            live.refresh()
            live.stop()


_active_display: Optional[LiveTurnDisplay] = None


def _cli_confirm(action_prompt: str) -> bool:
    """Pause live rendering, prompt user in terminal, then resume live rendering."""
    if _active_display is not None:
        _active_display.pause()
    try:
        console.print(f"\n[bold yellow]⚠ Security confirmation required:[/bold yellow] {action_prompt}")
        answer = console.input("  [bold]Proceed? [y/N] > [/bold]").strip().lower()
        return answer in ("y", "yes", "o", "oui")
    except (EOFError, KeyboardInterrupt):
        return False
    finally:
        if _active_display is not None:
            _active_display.resume()


def _format_heavy_state(info: dict) -> str:
    if info["ready"]:
        sub = "LOADED" if info.get("loaded") else "RAM OK"
        return f"[green]ONLINE • {sub}[/green]"
    if info.get("block_reason") == "insufficient_ram":
        return "[red]LOW RAM[/red]"
    if info.get("block_reason") == "not_installed":
        return "[red]NOT PULLED[/red]"
    return "[red]OFFLINE[/red]"


async def print_banner() -> None:
    status = await model_router.get_models_status()
    telemetry = get_system_telemetry()
    mem_count = len(memory_store.get_memories(limit=100))

    fast_state = (
        "[green]ONLINE • LOADED[/green]"
        if status["fast"].get("loaded")
        else ("[green]ONLINE • READY[/green]" if status["fast"].get("ready") else "[red]OFFLINE[/red]")
    )
    pro_state = _format_heavy_state(status["pro"])
    limitless_state = _format_heavy_state(status["limitless"])

    ram_color = "green" if status["ram_ok"] else "red"
    confirm_label = (
        "[green]ON[/green]" if status.get("confirm_risky_actions", True) else "[yellow]OFF[/yellow]"
    )

    table = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    table.add_column("Key", style="dim", width=12)
    table.add_column("Value")
    table.add_row(
        "System",
        f"CPU [bold]{telemetry['cpu_percent']}%[/bold] | "
        f"RAM [bold]{telemetry['ram_used_gb']}/{telemetry['ram_total_gb']} GB[/bold] | "
        f"[{ram_color}]{telemetry['ram_free_gb']} GB free (Guardrail >= {status['pro_min_free_ram_gb']} GB)[/{ram_color}]",
    )
    table.add_row(
        "Models",
        f"[cyan]FAST[/cyan]={status['fast']['model']} ({fast_state})  |  "
        f"[yellow]PRO[/yellow]={status['pro']['model']} ({pro_state})  |  "
        f"[magenta]LIMITLESS[/magenta]={status['limitless']['model']} ({limitless_state})",
    )
    table.add_row(
        "Config",
        f"Mode=[bold]{status['routing_mode'].upper()}[/bold] | "
        f"Confirm={confirm_label} | "
        f"Memories=[bold]{mem_count}[/bold]",
    )

    console.print()
    console.print(
        Panel(
            table,
            title="[bold cyan]E.V.R.I.S. — Terminal Interface (Qwen 3.5 + Streaming)[/bold cyan]",
            subtitle="[dim]Type /help to show available commands[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()


def print_commands() -> None:
    table = Table(title="Available Commands", box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description")
    commands = [
        ("/help", "Show this command list"),
        ("/status", "Show live system & model monitoring"),
        ("/mode auto|fast|pro|limitless", "Switch routing mode (limitless = uncensored)"),
        ("/pro on|off", "Toggle Pro model availability (test refusal)"),
        ("/confirm on|off", "Toggle smart confirmation for risky actions"),
        ("/ram [gb]", "Check or set heavy-model RAM threshold (e.g. /ram 5.5)"),
        ("/memories", "List saved long-term facts"),
        ("/forget <id|all>", "Delete a saved memory (or all)"),
        ("/tools", "List autonomous agent tools"),
        ("/clear", "Clear conversation history"),
        ("/exit", "Quit Evris"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)
    console.print()
    console.print(table)
    console.print()


def print_live_prompt_bar() -> None:
    """Show the active routing mode above the user prompt."""
    mode = model_router.routing_mode.upper()
    mode_color = TIER_STYLES.get(model_router.routing_mode, "cyan")
    console.print(f"[dim]┌─[/dim] [{mode_color}]MODE:{mode}[/{mode_color}]")


async def repl() -> None:
    global _active_display
    setup_logging()
    set_confirmation_handler(_cli_confirm)
    ensure_ollama_running()
    await print_banner()

    while True:
        try:
            print_live_prompt_bar()
            user_input = console.input("[bold white]└─ You > [/bold white]").lstrip("\ufeff").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Shutting down Evris.[/dim]")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            parts = user_input.split()
            cmd = parts[0].lower()

            if cmd in ("/exit", "/quit"):
                console.print("[dim]Shutting down Evris.[/dim]")
                break
            elif cmd in ("/help", "/commands"):
                print_commands()
                continue
            elif cmd == "/clear":
                memory_store.clear_messages()
                console.print("[green]✓ Conversation history cleared (long-term memories preserved).[/green]\n")
                continue
            elif cmd == "/status":
                await print_banner()
                continue
            elif cmd == "/memories":
                items = memory_store.get_memories(limit=50)
                if not items:
                    console.print("[dim]No long-term memories saved yet. Try saying: 'Remember that my target return is 12%'[/dim]\n")
                else:
                    table = Table(
                        title=f"Long-Term Memories ({len(items)})",
                        box=box.ROUNDED,
                        border_style="cyan",
                        header_style="bold cyan",
                    )
                    table.add_column("ID", style="yellow", no_wrap=True)
                    table.add_column("Category", style="cyan", no_wrap=True)
                    table.add_column("Content")
                    table.add_column("Created", style="dim", no_wrap=True)
                    for m in items:
                        table.add_row(f"#{m['id']}", m["category"], m["content"], m["created_at"])
                    console.print()
                    console.print(table)
                    console.print()
                continue
            elif cmd == "/forget" and len(parts) > 1:
                target = parts[1].lower()
                if target == "all":
                    memory_store.clear_memories()
                    console.print("[green]✓ All long-term memories cleared.[/green]\n")
                elif target.isdigit():
                    ok = memory_store.delete_memory(int(target))
                    if ok:
                        console.print(f"[green]✓ Memory #{target} deleted.[/green]\n")
                    else:
                        console.print(f"[red]Memory #{target} not found.[/red]\n")
                else:
                    console.print("[red]Usage: /forget <id> or /forget all[/red]\n")
                continue
            elif cmd == "/tools":
                table = Table(
                    title=f"Available Autonomous Tools ({len(OLLAMA_TOOLS_SCHEMA)})",
                    box=box.ROUNDED,
                    border_style="green",
                    header_style="bold green",
                )
                table.add_column("Tool", style="green", no_wrap=True)
                table.add_column("Capability")
                for t in OLLAMA_TOOLS_SCHEMA:
                    fn = t["function"]
                    table.add_row(fn["name"], fn["description"])
                console.print()
                console.print(table)
                console.print()
                continue
            elif cmd == "/mode" and len(parts) > 1 and parts[1].lower() in ("auto", "fast", "pro", "limitless"):
                mode_val = parts[1].lower()
                model_router.set_routing_mode(mode_val)
                console.print(f"[green]✓ Routing mode set to: {mode_val.upper()} (saved)[/green]\n")
                continue
            elif cmd == "/pro" and len(parts) > 1 and parts[1].lower() in ("on", "off"):
                enabled = parts[1].lower() == "on"
                model_router.set_pro_enabled(enabled)
                state_str = "[green]ONLINE[/green]" if model_router.pro_enabled else "[red]OFFLINE[/red]"
                console.print(f"✓ Pro Node state set to: {state_str} (saved)\n")
                continue
            elif cmd == "/confirm" and len(parts) > 1 and parts[1].lower() in ("on", "off"):
                enabled = parts[1].lower() == "on"
                model_router.set_confirm_risky_actions(enabled)
                state_str = "[green]ON[/green]" if enabled else "[yellow]OFF[/yellow]"
                console.print(f"✓ Smart security confirmation set to: {state_str} (saved)\n")
                continue
            elif cmd == "/ram":
                if len(parts) > 1:
                    try:
                        val = float(parts[1])
                        if val < 0:
                            raise ValueError
                        model_router.set_pro_min_free_ram_gb(val)
                        console.print(
                            f"[green]✓ Pro RAM safety guardrail set to >= {model_router.pro_min_free_ram_gb:.2f} GB free RAM (saved).[/green]\n"
                        )
                    except ValueError:
                        console.print("[red]Usage: /ram [gb] (e.g. /ram 5.5 or /ram 12.0 to test low-RAM refusal)[/red]\n")
                else:
                    status = await model_router.get_models_status()
                    ok_str = "[green]PASS[/green]" if status["ram_ok"] else "[red]BLOCKED (LOW RAM)[/red]"
                    loaded_str = "Yes (already in RAM)" if status["pro"]["loaded"] else "No (on standby)"
                    console.print(
                        f"\n[bold cyan]RAM Safety Guardrail Status:[/bold cyan]\n"
                        f"  • Free System RAM : [bold]{status['free_ram_gb']:.2f} GB[/bold]\n"
                        f"  • Pro Min Required: [bold]{status['pro_min_free_ram_gb']:.2f} GB[/bold]\n"
                        f"  • Pro Model Loaded: {loaded_str}\n"
                        f"  • Guardrail Check : {ok_str}\n"
                    )
                continue
            else:
                console.print("[red]Unknown command. Type /help to see all available commands.[/red]\n")
                continue

        predicted_tier, domain = model_router.classify_task(user_input)
        predicted_model = (
            model_router.fast_model
            if predicted_tier == "fast"
            else (model_router.limitless_model if predicted_tier == "limitless" else model_router.pro_model)
        )

        display = LiveTurnDisplay(
            predicted_tier=predicted_tier,
            domain=domain,
            model_name=predicted_model,
        )
        _active_display = display
        display.start()
        try:
            result = await evris_agent.chat(user_input, on_event=display.handle_event)
            display.finish(
                tier_used=result["tier_used"],
                model_used=result["model_used"],
                latency_ms=result["latency_ms"],
                final_reply=result["assistant_message"]["content"],
                executed_tools=result.get("executed_tools") or [],
            )
        except Exception as exc:
            display.finish(
                tier_used="refused",
                model_used=predicted_model,
                latency_ms=0,
                final_reply=f"Unexpected error: {exc}",
                executed_tools=[],
            )
        finally:
            _active_display = None
        console.print()


def main() -> None:
    asyncio.run(repl())


if __name__ == "__main__":
    main()
