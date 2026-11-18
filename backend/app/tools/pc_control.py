import os
import platform
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional
import psutil

# Convenience aliases (FR/EN shortcuts); no longer a restrictive whitelist.
APP_ALIASES: Dict[str, str] = {
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "calculatrice": "calc.exe",
    "notepad": "notepad.exe",
    "bloc-notes": "notepad.exe",
    "explorer": "explorer.exe",
    "explorateur": "explorer.exe",
    "cmd": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "taskmgr": "taskmgr.exe",
    "gestionnaire des taches": "taskmgr.exe",
    "vscode": "code",
    "vs code": "code",
    "settings": "ms-settings:",
    "parametres": "ms-settings:",
    "paramètres": "ms-settings:",
}


def _find_start_menu_shortcut(query: str) -> Optional[Path]:
    """Search Windows Start Menu and Desktop shortcuts (.lnk/.url) by name."""
    q = query.strip().lower()
    if not q:
        return None

    search_roots = [
        Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path.home() / "Desktop",
    ]
    candidates: List[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for ext in ("*.lnk", "*.url"):
            candidates.extend(root.rglob(ext))

    # Avoid matching uninstaller shortcuts unless explicitly requested
    if "uninstall" not in q and "désinstaller" not in q:
        candidates = [p for p in candidates if "uninstall" not in p.stem.lower()]

    exact = [p for p in candidates if p.stem.lower() == q]
    if exact:
        return exact[0]

    prefix = [p for p in candidates if p.stem.lower().startswith(q)]
    if prefix:
        return min(prefix, key=lambda p: len(p.stem))

    substring = [p for p in candidates if q in p.stem.lower()]
    if substring:
        return min(substring, key=lambda p: len(p.stem))

    return None


def _launch_executable(exe_path: str) -> None:
    if exe_path.lower().endswith((".cmd", ".bat")):
        subprocess.Popen(
            ["cmd", "/c", exe_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    else:
        subprocess.Popen(
            [exe_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def open_application(target: str) -> Dict[str, Any]:
    """Opens any installed desktop application, executable path, Start Menu shortcut, or URL."""
    raw = target.strip()
    if not raw:
        return {"ok": False, "error": "Application target cannot be empty."}

    t_lower = raw.lower()
    if t_lower.startswith(("http://", "https://")):
        webbrowser.open(raw)
        return {"ok": True, "summary": f"Opened URL in browser: {raw}"}

    candidate = APP_ALIASES.get(t_lower, raw)

    # 1. Explicit file or directory path
    expanded_path = Path(os.path.expandvars(os.path.expanduser(candidate)))
    if expanded_path.exists():
        try:
            os.startfile(str(expanded_path))
            return {"ok": True, "summary": f"Launched: {expanded_path}"}
        except Exception as exc:
            return {"ok": False, "error": f"Failed to launch '{expanded_path}': {exc}"}

    # 2. URI scheme (e.g. ms-settings:, steam://, discord://) — exclude drive paths like C:\
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]{1,}:", candidate):
        try:
            os.startfile(candidate)
            return {"ok": True, "summary": f"Launched URI: {candidate}"}
        except Exception as exc:
            return {"ok": False, "error": f"Failed to launch '{candidate}': {exc}"}

    # 3. Executable available on PATH
    which_hit = shutil.which(candidate)
    if which_hit:
        try:
            _launch_executable(which_hit)
            return {"ok": True, "summary": f"Launched application: {Path(which_hit).name}"}
        except Exception as exc:
            return {"ok": False, "error": f"Failed to launch '{which_hit}': {exc}"}

    # 4. Start Menu / Desktop shortcut match (e.g. "Google Chrome", "Discord", "Spotify")
    shortcut = _find_start_menu_shortcut(raw)
    if not shortcut and candidate != raw:
        shortcut = _find_start_menu_shortcut(candidate)
    if shortcut:
        try:
            os.startfile(str(shortcut))
            return {"ok": True, "summary": f"Launched shortcut: {shortcut.stem}"}
        except Exception as exc:
            return {"ok": False, "error": f"Failed to launch shortcut '{shortcut.stem}': {exc}"}

    # 5. Windows Shell / Registry App Paths fallback (e.g. "chrome", "winword", "excel")
    try:
        os.startfile(candidate)
        return {"ok": True, "summary": f"Launched application: {candidate}"}
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Could not find or launch '{raw}': {exc}",
        }


def get_system_report() -> Dict[str, Any]:
    """Returns a detailed live hardware & OS report including top RAM-consuming processes."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    battery = psutil.sensors_battery()
    cpu_pct = psutil.cpu_percent(interval=0.2)

    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            mem_mb = (p.info["memory_info"].rss if p.info["memory_info"] else 0) / (1024**2)
            procs.append({"name": p.info["name"], "ram_mb": round(mem_mb, 1)})
        except Exception:
            pass
    top_procs = sorted(procs, key=lambda x: x["ram_mb"], reverse=True)[:5]

    report = {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu_percent": round(cpu_pct, 1),
        "cpu_cores_logical": psutil.cpu_count(logical=True),
        "ram_used_gb": round(vm.used / (1024**3), 2),
        "ram_total_gb": round(vm.total / (1024**3), 2),
        "ram_free_gb": round(vm.available / (1024**3), 2),
        "disk_free_gb": round(disk.free / (1024**3), 1),
        "disk_percent": round(disk.percent, 1),
        "battery_percent": round(battery.percent, 0) if battery else None,
        "power_plugged": battery.power_plugged if battery else True,
        "top_processes_by_ram": top_procs,
    }
    return {
        "ok": True,
        "report": report,
        "summary": (
            f"CPU {report['cpu_percent']}%, RAM {report['ram_used_gb']}/{report['ram_total_gb']} GB "
            f"({report['ram_free_gb']} GB free), Disk {report['disk_free_gb']} GB free."
        ),
    }


def read_local_file(file_path: str, max_chars: int = 6000) -> Dict[str, Any]:
    """Reads the text content of a local file on the user's computer for analysis or summarization."""
    try:
        p = Path(os.path.expandvars(os.path.expanduser(file_path.strip()))).resolve()
        if not p.exists() or not p.is_file():
            return {"ok": False, "error": f"File not found: {p}"}
        content = p.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars
        snippet = content[:max_chars]
        return {
            "ok": True,
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "truncated": truncated,
            "content": snippet,
            "summary": f"Read {len(snippet)} chars from {p.name}",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def list_directory(dir_path: str = ".") -> Dict[str, Any]:
    """Lists files and folders inside a local directory."""
    try:
        p = Path(os.path.expandvars(os.path.expanduser(dir_path.strip()))).resolve()
        if not p.exists() or not p.is_dir():
            return {"ok": False, "error": f"Directory not found: {p}"}
        entries = []
        for item in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:60]:
            entries.append(
                {
                    "name": item.name + ("/" if item.is_dir() else ""),
                    "type": "dir" if item.is_dir() else "file",
                    "size_kb": round(item.stat().st_size / 1024, 1) if item.is_file() else None,
                }
            )
        return {
            "ok": True,
            "path": str(p),
            "entries": entries,
            "summary": f"Listed {len(entries)} item(s) in {p}",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
