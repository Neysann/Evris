import os
import platform
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, List
import psutil

APP_ALIASES: Dict[str, List[str]] = {
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "calculatrice": ["calc.exe"],
    "notepad": ["notepad.exe"],
    "bloc-notes": ["notepad.exe"],
    "explorer": ["explorer.exe"],
    "explorateur": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "terminal": ["wt.exe"],
    "powershell": ["powershell.exe"],
    "taskmgr": ["taskmgr.exe"],
    "vscode": ["code"],
    "code": ["code"],
}


def open_application(target: str) -> Dict[str, Any]:
    """Opens a local desktop application or a web URL on the host PC."""
    t = target.strip()
    t_lower = t.lower()

    if t_lower.startswith("http://") or t_lower.startswith("https://"):
        webbrowser.open(t)
        return {"ok": True, "summary": f"Opened URL in browser: {t}"}

    for key, cmd in APP_ALIASES.items():
        if key == t_lower or key in t_lower:
            try:
                subprocess.Popen(
                    cmd,
                    shell=(cmd[0] == "code"),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {"ok": True, "summary": f"Launched application: {cmd[0]}"}
            except Exception as exc:
                return {"ok": False, "error": f"Failed to launch {cmd[0]}: {exc}"}

    return {
        "ok": False,
        "error": f"Application '{target}' is not in the allowed whitelist ({', '.join(APP_ALIASES.keys())}).",
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
