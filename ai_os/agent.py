import json
import time

import pyautogui
from openai import OpenAI

from .actions import READ_ONLY_TOOLS, TOOLS, Actions
from .config import Config
from .deepseek import is_deepseek
from .overlay import StatusFn, no_status
from .screen import ScreenReader
from .voice import Speaker

SCREEN_MARK = "\n\n=== 当前屏幕 ===\n"
TOOL_LABELS = {
    "get_screen_elements": "读取屏幕", "click_element": "点击", "click_xy": "点击坐标",
    "type_text": "输入", "press_keys": "按键", "scroll": "滚动", "open_app": "打开",
    "open_url": "打开网址", "open_path": "打开", "list_windows": "查看窗口", "focus_window": "切换到",
    "look_at_screen": "看屏幕", "run_powershell": "运行命令", "wait": "等待", "ask_user": "询问",
}
STALE_SCREEN = "\n\n（旧的屏幕状态已省略）"

SYSTEM_PROMPT = """你是一个运行在 Windows 电脑上的语音操作助手，用户完全通过语音控制电脑，不使用鼠标和键盘。
你的任务是把用户的口语指令转化为一系列电脑操作并执行完成。

工作方式：
- 每次操作后你会收到最新的屏幕控件列表，格式为 [编号] 类型 名称。
- 优先使用 click_element 按编号点击；控件列表里找不到目标时，再用 look_at_screen + click_xy。
- 善用快捷键（press_keys）和 open_app / open_url / focus_window，它们比逐个点击更可靠。
- 输入文字前先点击或聚焦目标输入框。
- 每一步后检查屏幕状态是否符合预期，不符合就调整策略，不要盲目重复同一个动作。
- 用户口述可能有同音错别字，请结合语境理解。
- 指令有歧义或缺少关键信息（如收件人、文件名）时，用 ask_user 询问。
- 删除文件、发送消息、付款、关机等不可逆操作，执行前先用 ask_user 确认。
- 完成后调用 finish，summary 用一两句口语化中文告诉用户结果。纯问答类问题（不需要操作电脑）也直接用 finish 回答。
"""


class Agent:
    def __init__(self, cfg: Config, speaker: Speaker, actions: Actions, screen: ScreenReader,
                 status: StatusFn = no_status):
        self.client = OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)
        self.model = cfg.llm_model
        self.extra_body = ({"thinking": {"type": cfg.llm_thinking}}
                           if is_deepseek(cfg.llm_base_url) and cfg.llm_thinking else None)
        self.max_steps = cfg.max_steps
        self.speaker = speaker
        self.actions = actions
        self.screen = screen
        self.status = status

    def run(self, command: str) -> None:
        print(f"[用户] {command}")
        self.command = command
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": command + SCREEN_MARK + self.screen.snapshot()},
        ]
        try:
            for _ in range(self.max_steps):
                if self._step(messages):
                    return
            self.speaker.say("步骤太多了，我先停下来。你可以换个说法再试一次。")
        except pyautogui.FailSafeException:
            self.speaker.say("已紧急停止。")
        except Exception as e:
            print(f"[错误] {type(e).__name__}: {e}")
            self.speaker.say("出错了，请稍后再试。")

    def _step(self, messages: list[dict]) -> bool:
        """Runs one model turn; returns True when the task is finished."""
        self.status("thinking", self.command)
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=TOOLS, tool_choice="auto", temperature=0.2,
            extra_body=self.extra_body)
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        entry: dict = {"role": "assistant", "content": message.content or ""}
        # DeepSeek thinking mode requires the reasoning to be echoed back while tool calls are in flight.
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning:
            entry["reasoning_content"] = reasoning
        if tool_calls:
            entry["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ]
        messages.append(entry)

        if not tool_calls:
            self.speaker.say(message.content or "好的。")
            return True

        screen_changed = False
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "finish":
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "ok"})
                self.speaker.say(args.get("summary", "完成了。"))
                return True

            print(f"  -> {name}({json.dumps(args, ensure_ascii=False)})")
            self.status("acting", self._describe(name, args))
            result = self.actions.dispatch(name, args)
            print(f"     {result.splitlines()[0] if result else ''}")
            if name == "get_screen_elements":
                result = SCREEN_MARK.lstrip() + result
            screen_changed |= name not in READ_ONLY_TOOLS
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        if screen_changed:
            time.sleep(0.6)
            messages[-1]["content"] += SCREEN_MARK + self.screen.snapshot()
        _drop_stale_screens(messages)
        return False

    def _describe(self, name: str, args: dict) -> str:
        verb = TOOL_LABELS.get(name, name)
        if name == "click_element":
            element = self.screen.elements.get(args.get("id"))
            target = element.name or element.kind if element else ""
        else:
            target = next((str(args[k]) for k in ("name", "keyword", "text", "keys", "url", "path", "command")
                           if args.get(k)), "")
        return f"{verb} {target}".strip()


def _drop_stale_screens(messages: list[dict]) -> None:
    """Keeps only the latest screen snapshot in context to bound token usage."""
    marker = SCREEN_MARK.strip()
    seen_latest = False
    for msg in reversed(messages):
        content = msg.get("content")
        if not isinstance(content, str) or marker not in content:
            continue
        if not seen_latest:
            seen_latest = True
            continue
        msg["content"] = content.split(marker)[0].rstrip() + STALE_SCREEN
