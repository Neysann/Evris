from pathlib import Path
from unittest.mock import patch
from app.tools import pc_control


def test_classify_launch_risk_safe_cases():
    assert pc_control.classify_launch_risk("https://github.com")[0] is False
    assert pc_control.classify_launch_risk("ms-settings:")[0] is False
    assert pc_control.classify_launch_risk("calc.exe")[0] is False
    assert pc_control.classify_launch_risk(
        "Google Chrome",
        resolved_path=Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Google Chrome.lnk"),
        is_start_menu=True,
    )[0] is False
    assert pc_control.classify_launch_risk(
        "code",
        resolved_path=Path(r"C:\Users\demo\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd"),
    )[0] is False


def test_classify_launch_risk_requires_confirmation():
    assert pc_control.classify_launch_risk("cmd.exe")[0] is True
    assert pc_control.classify_launch_risk("powershell.exe")[0] is True
    assert pc_control.classify_launch_risk("steam://run/123")[0] is True
    assert pc_control.classify_launch_risk(
        "script.bat",
        resolved_path=Path(r"C:\Users\demo\Downloads\script.bat"),
    )[0] is True
    assert pc_control.classify_launch_risk(
        "setup.exe",
        resolved_path=Path(r"C:\Users\demo\Downloads\setup.exe"),
    )[0] is True


def test_open_application_confirmation_blocks_and_allows(tmp_path):
    script = tmp_path / "danger.bat"
    script.write_text("@echo off\n", encoding="utf-8")

    pc_control.set_confirm_risky_actions(True)
    pc_control.set_confirmation_handler(lambda _msg: False)
    res_denied = pc_control.open_application(str(script))
    assert res_denied["ok"] is False
    assert "confirmation" in res_denied["error"].lower() or "cancelled" in res_denied["error"].lower()

    pc_control.set_confirmation_handler(lambda _msg: True)
    with patch("os.startfile") as mock_startfile:
        res_allowed = pc_control.open_application(str(script))
    assert res_allowed["ok"] is True
    mock_startfile.assert_called_once_with(str(script))

    # Restore clean handler state
    pc_control.set_confirmation_handler(None)


def test_open_application_no_handler_blocks_risky_target(tmp_path):
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")

    pc_control.set_confirm_risky_actions(True)
    pc_control.set_confirmation_handler(None)
    res = pc_control.open_application(str(exe))
    assert res["ok"] is False
    assert "confirmation" in res["error"].lower()


def test_open_application_empty_target():
    res = pc_control.open_application("   ")
    assert res["ok"] is False


def test_sensitive_file_protection(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=123\n", encoding="utf-8")
    normal_file = tmp_path / "notes.txt"
    normal_file.write_text("hello evris\n", encoding="utf-8")

    pc_control.set_confirm_risky_actions(True)
    pc_control.set_confirmation_handler(lambda _msg: False)

    res_env_blocked = pc_control.read_local_file(str(env_file))
    assert res_env_blocked["ok"] is False

    res_normal = pc_control.read_local_file(str(normal_file))
    assert res_normal["ok"] is True
    assert "hello evris" in res_normal["content"]

    pc_control.set_confirmation_handler(lambda _msg: True)
    res_env_allowed = pc_control.read_local_file(str(env_file))
    assert res_env_allowed["ok"] is True
    assert "SECRET=123" in res_env_allowed["content"]

    pc_control.set_confirmation_handler(None)
