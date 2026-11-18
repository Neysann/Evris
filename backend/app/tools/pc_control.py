import os
import platform
import re
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import psutil
from app.config import settings
from app.core.logging_config import get_logger

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows fallback
    winreg = None

logger = get_logger(__name__)

ConfirmationHandler = Callable[[str], bool]
_confirmation_handler: Optional[ConfirmationHandler] = None
_confirm_risky_actions: bool = settings.confirm_risky_actions

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

RISKY_EXTENSIONS = {
    ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".hta", ".scr", ".reg",
}
RISKY_EXECUTABLES = {
    "cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe",
    "mshta.exe", "regedit.exe", "reg.exe", "rundll32.exe", "msiexec.exe",
}
SAFE_BUILTINS = {
    "calc.exe", "notepad.exe", "explorer.exe", "taskmgr.exe",
    "mspaint.exe", "snippingtool.exe", "wt.exe",
}
SAFE_URI_PREFIXES = ("http://", "https://", "ms-settings:")
SENSITIVE_PATH_TOKENS = {
    ".ssh", ".aws", ".gnupg", ".env", ".env.local", ".env.production",
    ".git-credentials", ".npmrc", ".pypirc", ".netrc",
    "id_rsa", "id_ed25519", "id_ecdsa", "credentials.json",
}


def set_confirmation_handler(handler: Optional[ConfirmationHandler]) -> None:
    """Register a callback(prompt: str) -> bool for risky local actions."""
    global _confirmation_handler
    _confirmation_handler = handler


def set_confirm_risky_actions(enabled: bool) -> None:
    global _confirm_risky_actions
    _confirm_risky_actions = enabled


def is_confirm_risky_actions_enabled() -> bool:
    return _confirm_risky_actions


def _confirm_action(action_desc: str, reason: str) -> bool:
    if not _confirm_risky_actions:
        return True
    if _confirmation_handler is None:
        logger.warning("Blocked risky action (no confirmation handler): %s | %s", action_desc, reason)
        return False
    approved = bool(_confirmation_handler(f"{action_desc} — {reason}"))
    logger.info("User confirmation for '%s' (%s): %s", action_desc, reason, approved)
    return approved


def _trusted_install_roots() -> List[Path]:
    roots: List[Path] = []
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "SystemRoot"):
        val = os.environ.get(env_key)
        if val:
            roots.append(Path(val).resolve())
    local_programs = os.environ.get("LOCALAPPDATA")
    if local_programs:
        roots.append((Path(local_programs) / "Programs").resolve())
    return roots


def _start_menu_roots() -> List[Path]:
    roots: List[Path] = []
    for env_key in ("ProgramData", "APPDATA"):
        val = os.environ.get(env_key)
        if val:
            roots.append((Path(val) / "Microsoft/Windows/Start Menu/Programs").resolve())
    return roots


def _is_under_any(path: Path, roots: List[Path]) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def classify_launch_risk(
    target: str,
    resolved_path: Optional[Path] = None,
    is_start_menu: bool = False,
) -> Tuple[bool, str]:
    """Return (needs_confirmation, reason) for an open_application target."""
    t_lower = target.strip().lower()
    if t_lower.startswith(SAFE_URI_PREFIXES):
        return (False, "safe URI")

    # Unknown URI schemes (steam://, discord://, custom handlers)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]{1,}:", t_lower):
        return (True, f"custom URI scheme '{target}'")

    if is_start_menu:
        return (False, "Start Menu shortcut")

    if resolved_path is not None:
        name_low = resolved_path.name.lower()
        suffix_low = resolved_path.suffix.lower()
        path_low = str(resolved_path).lower()

        # Allow VS Code CLI wrapper without friction
        if name_low == "code.cmd" and "microsoft vs code" in path_low:
            return (False, "VS Code CLI")

        if name_low in RISKY_EXECUTABLES or suffix_low in RISKY_EXTENSIONS:
            return (True, f"shell or script execution ({resolved_path.name})")

        if name_low in SAFE_BUILTINS:
            return (False, "safe Windows built-in")

        if _is_under_any(resolved_path, _trusted_install_roots()):
            return (False, "trusted installation directory")

        return (True, f"untrusted or user-writable location ({resolved_path})")

    base_name = Path(t_lower).name
    if base_name in RISKY_EXECUTABLES or Path(t_lower).suffix in RISKY_EXTENSIONS:
        return (True, f"shell or script execution ({base_name})")
    if base_name in SAFE_BUILTINS:
        return (False, "safe Windows built-in")

    return (True, f"unverified launch target '{target}'")


def is_sensitive_file_path(file_path: Path) -> Tuple[bool, str]:
    """Detect sensitive credential, key, or environment files."""
    parts_low = {part.lower() for part in file_path.parts}
    name_low = file_path.name.lower()
    path_low = str(file_path).lower()

    if name_low.startswith(".env") or name_low in SENSITIVE_PATH_TOKENS:
        return (True, f"sensitive file '{file_path.name}'")

    overlap = parts_low.intersection({".ssh", ".aws", ".gnupg"})
    if overlap:
        return (True, f"sensitive directory '{sorted(overlap)[0]}'")

    if "user data" in path_low and any(b in path_low for b in ("chrome", "edge", "brave", "firefox")):
        return (True, "browser profile data")

    return (False, "")


def _find_start_menu_shortcut(query: str) -> Optional[Tuple[Path, bool]]:
    """Search Windows Start Menu and Desktop shortcuts (.lnk/.url) by name.
    Returns (path, is_start_menu) or None.
    """
    q = query.strip().lower()
    if not q:
        return None

    start_roots = _start_menu_roots()
    desktop_root = Path.home() / "Desktop"
    search_roots: List[Tuple[Path, bool]] = [(r, True) for r in start_roots] + [(desktop_root, False)]

    candidates: List[Tuple[Path, bool]] = []
    for root, is_menu in search_roots:
        if not root.exists():
            continue
        for ext in ("*.lnk", "*.url"):
            for item in root.rglob(ext):
                candidates.append((item, is_menu))

    # Avoid matching uninstaller shortcuts unless explicitly requested
    if "uninstall" not in q and "désinstaller" not in q:
        candidates = [(p, m) for p, m in candidates if "uninstall" not in p.stem.lower()]

    exact = [(p, m) for p, m in candidates if p.stem.lower() == q]
    if exact:
        return exact[0]

    prefix = [(p, m) for p, m in candidates if p.stem.lower().startswith(q)]
    if prefix:
        return min(prefix, key=lambda item: len(item[0].stem))

    substring = [(p, m) for p, m in candidates if q in p.stem.lower()]
    if substring:
        return min(substring, key=lambda item: len(item[0].stem))

    return None


def _resolve_windows_app_path(app_name: str) -> Optional[Path]:
    """Look up an application executable in Windows Registry App Paths."""
    if winreg is None:
        return None
    names = [app_name] if app_name.lower().endswith(".exe") else [f"{app_name}.exe", app_name]
    subkey_base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for candidate in names:
            try:
                with winreg.OpenKey(hive, f"{subkey_base}\\{candidate}") as key:
                    val, _ = winreg.QueryValueEx(key, None)
                    if val:
                        p = Path(os.path.expandvars(str(val).strip().strip('"')))
                        if p.exists():
                            return p
            except OSError:
                continue
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
        logger.info("Opened URL: %s", raw)
        return {"ok": True, "summary": f"Opened URL in browser: {raw}"}

    candidate = APP_ALIASES.get(t_lower, raw)

    # 1. Explicit file or directory path
    expanded_path = Path(os.path.expandvars(os.path.expanduser(candidate)))
    if expanded_path.exists():
        needs_confirm, reason = classify_launch_risk(candidate, resolved_path=expanded_path)
        if needs_confirm and not _confirm_action(f"Launch '{expanded_path}'", reason):
            return {"ok": False, "error": f"Launch cancelled or confirmation required for '{raw}' ({reason})."}
        try:
            os.startfile(str(expanded_path))
            logger.info("Launched explicit path: %s", expanded_path)
            return {"ok": True, "summary": f"Launched: {expanded_path}"}
        except Exception as exc:
            logger.error("Failed to launch '%s': %s", expanded_path, exc)
            return {"ok": False, "error": f"Failed to launch '{expanded_path}': {exc}"}

    # 2. URI scheme (e.g. ms-settings:, steam://, discord://) — exclude drive paths like C:\
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]{1,}:", candidate):
        needs_confirm, reason = classify_launch_risk(candidate)
        if needs_confirm and not _confirm_action(f"Open URI '{candidate}'", reason):
            return {"ok": False, "error": f"Launch cancelled or confirmation required for '{raw}' ({reason})."}
        try:
            os.startfile(candidate)
            logger.info("Launched URI: %s", candidate)
            return {"ok": True, "summary": f"Launched URI: {candidate}"}
        except Exception as exc:
            logger.error("Failed to launch URI '%s': %s", candidate, exc)
            return {"ok": False, "error": f"Failed to launch '{candidate}': {exc}"}

    # 3. Executable available on PATH
    which_hit = shutil.which(candidate)
    if which_hit:
        hit_path = Path(which_hit)
        needs_confirm, reason = classify_launch_risk(candidate, resolved_path=hit_path)
        if needs_confirm and not _confirm_action(f"Launch '{hit_path.name}'", reason):
            return {"ok": False, "error": f"Launch cancelled or confirmation required for '{raw}' ({reason})."}
        try:
            _launch_executable(which_hit)
            logger.info("Launched PATH executable: %s", which_hit)
            return {"ok": True, "summary": f"Launched application: {hit_path.name}"}
        except Exception as exc:
            logger.error("Failed to launch '%s': %s", which_hit, exc)
            return {"ok": False, "error": f"Failed to launch '{which_hit}': {exc}"}

    # 4. Windows Registry App Paths (e.g. "chrome", "winword", "excel")
    app_path_hit = _resolve_windows_app_path(candidate)
    if app_path_hit:
        needs_confirm, reason = classify_launch_risk(candidate, resolved_path=app_path_hit)
        if needs_confirm and not _confirm_action(f"Launch '{app_path_hit.name}'", reason):
            return {"ok": False, "error": f"Launch cancelled or confirmation required for '{raw}' ({reason})."}
        try:
            _launch_executable(str(app_path_hit))
            logger.info("Launched App Paths executable: %s", app_path_hit)
            return {"ok": True, "summary": f"Launched application: {app_path_hit.name}"}
        except Exception as exc:
            logger.error("Failed to launch '%s': %s", app_path_hit, exc)
            return {"ok": False, "error": f"Failed to launch '{app_path_hit}': {exc}"}

    # 5. Start Menu / Desktop shortcut match (e.g. "Google Chrome", "Discord", "Spotify")
    shortcut_match = _find_start_menu_shortcut(raw)
    if not shortcut_match and candidate != raw:
        shortcut_match = _find_start_menu_shortcut(candidate)
    if shortcut_match:
        shortcut, is_menu = shortcut_match
        needs_confirm, reason = classify_launch_risk(
            candidate, resolved_path=shortcut, is_start_menu=is_menu
        )
        if needs_confirm and not _confirm_action(f"Launch shortcut '{shortcut.stem}'", reason):
            return {"ok": False, "error": f"Launch cancelled or confirmation required for '{raw}' ({reason})."}
        try:
            os.startfile(str(shortcut))
            logger.info("Launched shortcut: %s", shortcut)
            return {"ok": True, "summary": f"Launched shortcut: {shortcut.stem}"}
        except Exception as exc:
            logger.error("Failed to launch shortcut '%s': %s", shortcut, exc)
            return {"ok": False, "error": f"Failed to launch shortcut '{shortcut.stem}': {exc}"}

    # 6. Windows Shell fallback (only after smart confirmation if not a safe built-in)
    needs_confirm, reason = classify_launch_risk(candidate)
    if needs_confirm and not _confirm_action(f"Launch '{candidate}'", reason):
        return {"ok": False, "error": f"Launch cancelled or confirmation required for '{raw}' ({reason})."}
    try:
        os.startfile(candidate)
        logger.info("Launched shell target: %s", candidate)
        return {"ok": True, "summary": f"Launched application: {candidate}"}
    except Exception as exc:
        logger.warning("Could not find or launch '%s': %s", raw, exc)
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
        is_sensitive, reason = is_sensitive_file_path(p)
        if is_sensitive and not _confirm_action(f"Read file '{p}'", reason):
            return {"ok": False, "error": f"Read cancelled or confirmation required for '{p.name}' ({reason})."}
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
