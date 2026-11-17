"""Runs one spoken request through DeepSeek Harness without its window.

Each request is `dsh --profile headless --json`, with a patch layer that

- re-enables the DeepSeek account sign-in the headless profile turns off, so the request uses the
  login of the desktop app and needs no API key, and
- adds the ai-os MCP server, so the agent has the desktop tools.

The user's own profiles are not modified. Follow-ups reuse the Session for a while, so "close it"
still knows what "it" is.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .paths import HEADLESS_PATCH, STATE_DIR

WORKSPACE = STATE_DIR / "workspace"

PATCH = """\
# Written by ai-os; edits are overwritten on the next start.
- id: authorization
  name: '@deepseek-ai/dsh-authorization'
  disabled: false
- id: deepseek-account
  name: '@deepseek-ai/dsh-deepseek-account'
  disabled: false
- id: credentials
  name: '@deepseek-ai/dsh-credentials-local'
  disabled: false
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: {provider}
    model: {model}
- insert:
    - id: mcp-ai-os
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: ai-os
        transport: stdio
        command: ai-os-mcp
"""

TOOL_LABELS = {
    "get_screen_elements": "读取界面",
    "click_element": "点击",
    "click_xy": "点击",
    "type_text": "输入文字",
    "press_keys": "按键",
    "scroll": "滚动",
    "open_app": "打开应用",
    "open_url": "打开网页",
    "open_path": "打开文件",
    "list_windows": "查看窗口",
    "focus_window": "切换窗口",
    "look_at_screen": "看屏幕",
    "wait": "等待",
}

TIMEOUT_S = 300


class DshError(RuntimeError):
    pass


class DshCancelled(DshError):
    pass


def _kill_tree(pid: int) -> None:
    # dsh runs node, which runs ai-os-mcp; killing only the top process would orphan them.
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


@dataclass
class Reply:
    text: str
    session_id: str | None
    tools: int


class DshBrain:
    def __init__(self, provider: str = "deepseek-account", model: str = "deepseek-flash",
                 follow_up_s: float = 300):
        self.exe = shutil.which("dsh")
        # Nobody is there to approve a command, so shell commands default to read-only;
        # desktop actions go through the ai-os tools and are unaffected.
        self.permission_mode = os.environ.get("AI_OS_PERMISSION_MODE", "read-only")
        self.follow_up_s = follow_up_s
        self.session_id: str | None = None
        self.last_at = 0.0
        HEADLESS_PATCH.parent.mkdir(parents=True, exist_ok=True)
        HEADLESS_PATCH.write_text(PATCH.format(provider=provider, model=model), encoding="utf-8")

    def problem(self) -> str | None:
        """A setup problem that makes every request fail, or None."""
        if not self.exe:
            return "找不到 dsh 命令：请先安装 DeepSeek Harness（npm install -g @deepseek-ai/dsh）"
        return None

    def forget(self) -> None:
        self.session_id = None

    def run(self, text: str, on_tool: Callable[[str], None] = lambda _label: None,
            cancel: threading.Event | None = None) -> Reply:
        """Raises DshCancelled when cancel is set while the request runs."""
        problem = self.problem()
        if problem:
            raise DshError(problem)
        if time.monotonic() - self.last_at > self.follow_up_s:
            self.session_id = None

        args = [self.exe, "--profile", "headless", "--patch", str(HEADLESS_PATCH), "--json",
                "--permission-mode", self.permission_mode]
        if self.session_id:
            args += ["--session-id", self.session_id]
        args.append("-")
        # The desktop tools' hotkey belongs to the daemon while it runs.
        env = {**os.environ, "AI_OS_HOTKEY": "off"}
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, cwd=str(WORKSPACE), creationflags=subprocess.CREATE_NO_WINDOW)
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        errors: list[bytes] = []
        drain = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
        drain.start()
        timer = threading.Timer(TIMEOUT_S, _kill_tree, args=(proc.pid,))
        timer.start()
        done = threading.Event()
        if cancel is not None:
            def watch() -> None:
                while not done.wait(0.1):
                    if cancel.is_set():
                        _kill_tree(proc.pid)
                        return
            threading.Thread(target=watch, daemon=True).start()

        final, session_id, tools = None, self.session_id, 0
        try:
            for line in proc.stdout:
                event = _parse(line)
                kind = event.get("type")
                if kind == "session":
                    session_id = event.get("sessionId") or session_id
                elif kind == "tool_call":
                    tools += 1
                    name = str(event.get("tool", "")).rsplit("__", 1)[-1]
                    on_tool(TOOL_LABELS.get(name, name))
                elif kind == "final":
                    final = event
            proc.wait()
        finally:
            done.set()
            timed_out = not timer.is_alive() and final is None
            timer.cancel()
        drain.join(timeout=5)
        stderr = b"".join(errors).decode("utf-8", "replace")

        if cancel is not None and cancel.is_set():
            raise DshCancelled("已取消")
        if final is None:
            if timed_out:
                raise DshError(f"超过 {TIMEOUT_S // 60} 分钟没有完成，已停止")
            raise DshError(_explain(stderr) or f"DeepSeek Harness 异常退出（{proc.returncode}）")
        self.session_id = final.get("sessionId") or session_id
        self.last_at = time.monotonic()
        text = (final.get("text") or "").strip()
        if final.get("reason", {}).get("kind") != "completed" and not text:
            text = "这件事没有做完。"
        return Reply(text=text, session_id=self.session_id, tools=tools)


def _parse(line: bytes) -> dict:
    try:
        event = json.loads(line)
    except ValueError:
        return {}
    return event if isinstance(event, dict) else {}


def _explain(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in reversed(lines):
        if "ACCOUNT_SIGN_IN_REQUIRED" in line:
            return "DeepSeek 账号未登录：打开一次 DeepSeek Harness 并登录"
        if "MISSING_CREDENTIAL" in line:
            return "没有可用的模型凭据：在 DeepSeek Harness 里登录账号或配置 API Key"
        if line.startswith("dsh:"):
            return line.removeprefix("dsh:").strip()
    return lines[-1] if lines else ""
