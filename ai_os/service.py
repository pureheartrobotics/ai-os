"""Runs the background assistant as a per-user service: `ai-os service start|stop|restart|status|enable|disable`.

`start` launches a small supervisor without a console. The supervisor runs `ai-os daemon` and
restarts it when it crashes; only `stop` (or a setup problem a restart can't fix) ends it.

`status`, `start` and `restart` exit with
  0  running normally
  1  not running, or not answering; a restart may fix it
  2  running, but part of it has a problem (the hotkey is taken, the last request failed)
  3  waiting for setup; a restart won't fix it
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import winreg
from ctypes import wintypes
from pathlib import Path

from .paths import LOG_DIR, PID_FILE, STATE_FILE, STOP_FILE

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "AI OS"
KEEP_LOGS = 20
START_WAIT_S = 30
STOP_WAIT_S = 15
EXIT_SETUP = 3

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    code = wintypes.DWORD()
    try:
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _supervisor_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _alive(pid) else None


def _windowless_python() -> str:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else sys.executable)


def _new_log() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for old in sorted(LOG_DIR.glob("daemon-*.log"))[:-(KEEP_LOGS - 1)]:
        old.unlink(missing_ok=True)
    return LOG_DIR / time.strftime("daemon-%Y%m%d-%H%M%S.log")


# ---------- status ----------

def check() -> tuple[int, list[str]]:
    supervisor = _supervisor_pid()
    state = _read_json(STATE_FILE)
    daemon_alive = _alive(state.get("pid"))
    lines: list[str] = []

    if state.get("problem") and not daemon_alive:
        return EXIT_SETUP, [f"需要设置：{state['problem']}"]
    if not supervisor and not daemon_alive:
        return 1, ["后台助手没有运行。用 ai-os service start 启动。"]
    if not daemon_alive or not state.get("ready"):
        return 1, ["后台助手正在启动或没有响应。"]

    code = 0
    lines.append(f"后台助手正在运行（进程 {state['pid']}）")
    speech = {"local": "本地 SenseVoice（声音不上传）", "cloud": "云端识别"}.get(state.get("speech"), "未知")
    lines.append(f"  语音识别：{speech}")
    if state.get("hotkey") == "ok":
        lines.append("  快捷键：Ctrl+Alt+Space 可用")
    elif state.get("hotkey") == "busy":
        code = 2
        lines.append("  快捷键：Ctrl+Alt+Space 被占用（通常是先打开的 DeepSeek Harness），关掉它后会自动接管")
    if state.get("stopKey"):
        lines.append("  停止键：Ctrl+Alt+Esc（停止聆听、执行或朗读）")
    elif state.get("stopKey") is False:
        lines.append("  停止键：Ctrl+Alt+Esc 被其他程序占用")
    if state.get("wakeWord"):
        lines.append(f"  唤醒词：{state['wakeWord']}")
    task = state.get("lastTask")
    if task:
        lines.append(f"  上次任务：{time.strftime('%H:%M:%S', time.localtime(task['at']))}，"
                     f"用时 {task['seconds']} 秒，调用工具 {task['tools']} 次")
    error = state.get("lastError")
    if error:
        code = 2
        lines.append(f"  上次失败：{error['detail']}")
    lines.append(f"  开机自启：{'已开启' if _autostart_command() else '未开启'}")
    return code, lines


def status() -> int:
    code, lines = check()
    print("\n".join(lines))
    return code


# ---------- start / stop ----------

def start() -> int:
    if _supervisor_pid():
        return status()
    STOP_FILE.unlink(missing_ok=True)
    STATE_FILE.unlink(missing_ok=True)
    log = _new_log()
    with open(log, "ab") as out:
        proc = subprocess.Popen(
            [_windowless_python(), "-m", "ai_os", "service", "run"],
            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, cwd=str(Path.home()),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    PID_FILE.write_text(str(proc.pid))

    deadline = time.monotonic() + START_WAIT_S
    while time.monotonic() < deadline:
        state = _read_json(STATE_FILE)
        if state.get("ready") or state.get("problem") or proc.poll() is not None:
            break
        time.sleep(0.5)
    code = status()
    if code == 1:
        print(f"日志：{log}")
    return code


def stop() -> int:
    supervisor = _supervisor_pid()
    daemon = _read_json(STATE_FILE).get("pid")
    if not supervisor and not _alive(daemon):
        print("后台助手没有运行。")
        return 0
    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text("stop")
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline and (_alive(supervisor) or _alive(daemon)):
        time.sleep(0.3)
    for pid in (supervisor, daemon):
        if _alive(pid):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    PID_FILE.unlink(missing_ok=True)
    print("后台助手已停止。")
    return 0


def restart() -> int:
    stop()
    return start()


def run_supervisor() -> int:
    """Keeps `ai-os daemon` running until stop() asks it to end."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    backoff = 2.0
    while not STOP_FILE.exists():
        started = time.monotonic()
        print(time.strftime("[%Y-%m-%d %H:%M:%S] 启动后台助手"), flush=True)
        # Windows children inherit no handles unless they are passed explicitly.
        code = subprocess.call([sys.executable, "-m", "ai_os", "daemon"], stdin=subprocess.DEVNULL,
                               stdout=sys.stdout, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        if STOP_FILE.exists() or code in (0, EXIT_SETUP):
            print(time.strftime(f"[%Y-%m-%d %H:%M:%S] 后台助手退出（{code}）"), flush=True)
            break
        backoff = 2.0 if time.monotonic() - started > 300 else min(backoff * 2, 60.0)
        print(time.strftime(f"[%Y-%m-%d %H:%M:%S] 后台助手异常退出（{code}），{backoff:.0f} 秒后重启"), flush=True)
        deadline = time.monotonic() + backoff
        while time.monotonic() < deadline and not STOP_FILE.exists():
            time.sleep(0.5)
    STOP_FILE.unlink(missing_ok=True)
    if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
        PID_FILE.unlink(missing_ok=True)
    return 0


# ---------- autostart ----------

def _autostart_command() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_VALUE)[0]
    except OSError:
        return None


def enable() -> int:
    command = f'"{_windowless_python()}" -m ai_os service start'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)
    print("已开启开机自启：登录 Windows 后后台助手会自动运行。")
    return 0


def disable() -> int:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except FileNotFoundError:
        pass
    print("已关闭开机自启。")
    return 0


def logs() -> int:
    files = sorted(LOG_DIR.glob("daemon-*.log"))
    if not files:
        print("还没有日志。")
        return 1
    print(files[-1])
    return 0


COMMANDS = {
    "start": start, "stop": stop, "restart": restart, "status": status,
    "enable": enable, "disable": disable, "logs": logs, "run": run_supervisor,
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ai-os service", description="管理 AI OS 后台语音助手")
    parser.add_argument("command", choices=[c for c in COMMANDS if c != "run"] + ["run"],
                        help="start 启动 / stop 停止 / restart 重启 / status 状态 / "
                             "enable 开机自启 / disable 取消自启 / logs 最新日志路径")
    args = parser.parse_args(argv)
    raise SystemExit(COMMANDS[args.command]())
