import os
import subprocess
import time
import webbrowser
from typing import Callable

import pyautogui
import pyperclip
import uiautomation as auto
from openai import OpenAI

from .config import Config
from .screen import ScreenReader, screenshot_base64

pyautogui.PAUSE = 0.05
# Moving the mouse to the top-left corner aborts any running action.
pyautogui.FAILSAFE = True

APP_ALIASES = {
    "记事本": "notepad", "notepad": "notepad",
    "计算器": "calc", "calculator": "calc",
    "画图": "mspaint",
    "命令提示符": "cmd", "cmd": "cmd",
    "终端": "wt", "terminal": "wt", "powershell": "powershell",
    "资源管理器": "explorer", "文件管理器": "explorer", "此电脑": "explorer",
    "设置": "ms-settings:", "系统设置": "ms-settings:",
    "任务管理器": "taskmgr", "控制面板": "control",
}
KEY_ALIASES = {
    "回车": "enter", "return": "enter", "escape": "esc", "退出键": "esc",
    "control": "ctrl", "windows": "win", "空格": "space", "删除": "delete",
    "退格": "backspace", "上": "up", "下": "down", "左": "left", "右": "right",
}
APP_WAIT_S = 8.0
SHELL_PROCESSES = {"searchhost", "startmenuexperiencehost", "shellexperiencehost", "textinputhost"}
YES_WORDS = ("确认", "确定", "是", "好", "可以", "执行", "对", "没问题", "yes", "ok")

ConfirmFn = Callable[[str], bool]
AskFn = Callable[[str], str]


def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


TOOLS = [
    _fn("get_screen_elements", "重新读取前台窗口的可交互控件列表（带编号和坐标）。"),
    _fn("click_element", "点击屏幕控件列表中编号为 id 的控件。",
        {"id": {"type": "integer"},
         "double": {"type": "boolean", "description": "是否双击"},
         "right": {"type": "boolean", "description": "是否右键"}},
        ["id"]),
    _fn("click_xy", "按 look_at_screen 截图中的像素坐标点击。仅在控件列表里找不到目标时使用。",
        {"x": {"type": "integer"}, "y": {"type": "integer"},
         "double": {"type": "boolean"}, "right": {"type": "boolean"}},
        ["x", "y"]),
    _fn("type_text", "在当前焦点处输入文字（支持中文）。输入前确保已点击目标输入框。",
        {"text": {"type": "string"},
         "press_enter": {"type": "boolean", "description": "输入后是否按回车"}},
        ["text"]),
    _fn("press_keys", "按下快捷键或单个按键，例如 'ctrl+s'、'alt+tab'、'enter'、'win+d'。",
        {"keys": {"type": "string"}, "times": {"type": "integer", "description": "重复次数，默认 1"}},
        ["keys"]),
    _fn("scroll", "在鼠标当前位置或指定控件上滚动。",
        {"direction": {"type": "string", "enum": ["up", "down"]},
         "amount": {"type": "integer", "description": "滚动格数，默认 5"},
         "element_id": {"type": "integer", "description": "可选，滚动包含该控件的列表或区域"}},
        ["direction"]),
    _fn("open_app", "打开应用程序，例如 '记事本'、'微信'、'Chrome'、'设置'。",
        {"name": {"type": "string"}}, ["name"]),
    _fn("open_url", "用默认浏览器打开网址。搜索时可构造搜索引擎网址。",
        {"url": {"type": "string"}}, ["url"]),
    _fn("open_path", "用默认程序打开本地文件或文件夹。",
        {"path": {"type": "string"}}, ["path"]),
    _fn("list_windows", "列出所有已打开的窗口标题和所属进程。这就是完整的窗口清单，无需补充。"),
    _fn("focus_window", "切换到标题包含关键字的窗口。",
        {"keyword": {"type": "string"}}, ["keyword"]),
    _fn("look_at_screen", "截图并让视觉模型回答关于屏幕内容的问题，可要求返回目标的像素坐标供 click_xy 使用。",
        {"question": {"type": "string"}}, ["question"]),
    _fn("run_powershell", "执行 PowerShell 命令并返回输出。会先向用户语音确认。",
        {"command": {"type": "string"}, "reason": {"type": "string", "description": "用一句话向用户说明要做什么"}},
        ["command", "reason"]),
    _fn("wait", "等待界面加载。", {"seconds": {"type": "number"}}, ["seconds"]),
    _fn("ask_user", "当指令有歧义或缺少信息时，语音询问用户并获得回答。",
        {"question": {"type": "string"}}, ["question"]),
    _fn("finish", "任务完成或无法继续时调用，summary 会被朗读给用户，应简短口语化。",
        {"summary": {"type": "string"}}, ["summary"]),
]

READ_ONLY_TOOLS = {"get_screen_elements", "list_windows", "look_at_screen", "ask_user", "finish", "wait"}


class Actions:
    def __init__(self, cfg: Config, screen: ScreenReader, confirm: ConfirmFn, ask: AskFn):
        self.screen = screen
        self.confirm = confirm
        self.ask = ask
        self.vision_model = cfg.vision_model
        self.vision_client = (OpenAI(api_key=cfg.vision_api_key, base_url=cfg.vision_base_url)
                              if cfg.vision_model else None)
        self.screenshot_scale = 1.0

    def dispatch(self, name: str, args: dict) -> str:
        handler = getattr(self, f"do_{name}", None)
        if handler is None:
            return f"错误：未知工具 {name}"
        try:
            return handler(**args)
        except pyautogui.FailSafeException:
            raise
        except Exception as e:
            return f"错误：{type(e).__name__}: {e}"

    def do_get_screen_elements(self) -> str:
        return self.screen.snapshot()

    def do_click_element(self, id: int, double: bool = False, right: bool = False) -> str:
        element = self.screen.elements.get(id)
        if element is None:
            return f"错误：控件 {id} 不存在，请先调用 get_screen_elements 刷新。"
        self._click(element.x, element.y, double, right)
        return f"已点击 [{id}] {element.kind} \"{element.name}\""

    def do_click_xy(self, x: int, y: int, double: bool = False, right: bool = False) -> str:
        sx, sy = int(x / self.screenshot_scale), int(y / self.screenshot_scale)
        self._click(sx, sy, double, right)
        return f"已点击屏幕坐标 ({sx},{sy})"

    @staticmethod
    def _click(x: int, y: int, double: bool, right: bool) -> None:
        pyautogui.click(x, y, clicks=2 if double else 1, interval=0.08,
                        button="right" if right else "left")

    def do_type_text(self, text: str, press_enter: bool = False) -> str:
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)
        if previous is not None:
            pyperclip.copy(previous)
        if press_enter:
            pyautogui.press("enter")
        return f"已输入：{text[:50]}"

    def do_press_keys(self, keys: str, times: int = 1) -> str:
        parts = [KEY_ALIASES.get(k.strip().lower(), k.strip().lower()) for k in keys.split("+")]
        unknown = [k for k in parts if k not in pyautogui.KEYBOARD_KEYS]
        if unknown:
            return f"错误：无法识别的按键 {unknown}"
        for _ in range(max(1, times)):
            pyautogui.hotkey(*parts)
            time.sleep(0.05)
        return f"已按下 {'+'.join(parts)}" + (f" ×{times}" if times > 1 else "")

    def do_scroll(self, direction: str, amount: int = 5, element_id: int | None = None) -> str:
        label = f"已向{'上' if direction == 'up' else '下'}滚动 {amount} 格"
        if element_id is not None and element_id in self.screen.elements:
            element = self.screen.elements[element_id]
            if _uia_scroll(element.x, element.y, direction, amount):
                return label
            pyautogui.moveTo(element.x, element.y)
        pyautogui.scroll(120 * amount * (1 if direction == "up" else -1))
        return label

    def do_open_app(self, name: str) -> str:
        existing = {w.handle for w in self.screen.list_windows()}
        target = APP_ALIASES.get(name.strip()) or APP_ALIASES.get(name.strip().lower())
        if target:
            os.startfile(target)
            how = "已启动"
        else:
            pyautogui.press("win")
            time.sleep(0.8)
            pyperclip.copy(name)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(1.2)
            pyautogui.press("enter")
            how = "已通过开始菜单搜索并启动"

        window = self._wait_for_new_window(existing)
        if window:
            self.screen.focus(window)
            time.sleep(0.5)
            return f"{how} {name}，已切换到窗口：{window.title}"
        # Single-instance apps (e.g. Notepad adding a tab) reuse their existing window.
        focused = self.do_focus_window(name)
        if not focused.startswith("错误"):
            return f"{how} {name}，{focused}"
        return f"{how} {name}，但 {APP_WAIT_S:.0f} 秒内没有出现新窗口，请用 list_windows 检查是否打开成功。"

    def _wait_for_new_window(self, existing: set[int]):
        deadline = time.monotonic() + APP_WAIT_S
        while time.monotonic() < deadline:
            time.sleep(0.5)
            for window in self.screen.list_windows():
                if window.handle not in existing and window.process not in SHELL_PROCESSES:
                    return window
        return None

    def do_open_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        time.sleep(2.0)
        return f"已打开 {url}"

    def do_open_path(self, path: str) -> str:
        path = os.path.expandvars(os.path.expanduser(path))
        if not os.path.exists(path):
            return f"错误：路径不存在 {path}"
        os.startfile(path)
        time.sleep(1.0)
        return f"已打开 {path}"

    def do_list_windows(self) -> str:
        windows = self.screen.list_windows()
        return "\n".join(f"- {w.title}  ({w.process})" for w in windows) or "没有找到窗口"

    def do_focus_window(self, keyword: str) -> str:
        keyword_lower = keyword.strip().lower()
        process = APP_ALIASES.get(keyword.strip(), keyword_lower)
        for window in self.screen.list_windows():
            if keyword_lower in window.title.lower() or process == window.process:
                self.screen.focus(window)
                time.sleep(0.5)
                return f"已切换到窗口：{window.title}"
        return f"错误：没有标题包含“{keyword}”的窗口，可调用 list_windows 查看。"

    def do_look_at_screen(self, question: str) -> str:
        if self.vision_client is None:
            return "错误：未配置视觉模型（VISION_MODEL），请改用 get_screen_elements。"
        image_b64, self.screenshot_scale, (w, h) = screenshot_base64()
        prompt = (f"这是用户电脑的屏幕截图，尺寸 {w}x{h} 像素。{question}\n"
                  "如果涉及要点击的目标，请给出其中心点在这张图片中的像素坐标 (x, y)。")
        response = self.vision_client.chat.completions.create(
            model=self.vision_model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]}],
        )
        return response.choices[0].message.content or "（视觉模型无返回）"

    def do_run_powershell(self, command: str, reason: str) -> str:
        if not self.confirm(f"我需要执行一条系统命令：{reason}。确认执行吗？"):
            return "用户拒绝执行该命令。"
        script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + command
        result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                capture_output=True, timeout=60)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
        return f"退出码 {result.returncode}\n{output[:3000]}"

    def do_wait(self, seconds: float) -> str:
        time.sleep(min(max(seconds, 0), 10))
        return f"已等待 {seconds} 秒"

    def do_ask_user(self, question: str) -> str:
        answer = self.ask(question)
        return f"用户回答：{answer}" if answer else "用户没有回答。"


def _uia_scroll(x: int, y: int, direction: str, amount: int) -> bool:
    """Scroll the nearest scrollable ancestor of the control at (x, y) without relying on mouse focus."""
    control = auto.ControlFromPoint(x, y)
    while control:
        pattern = control.GetPattern(auto.PatternId.ScrollPattern)
        if pattern and pattern.VerticallyScrollable:
            step = auto.ScrollAmount.SmallDecrement if direction == "up" else auto.ScrollAmount.SmallIncrement
            # One wheel notch scrolls three lines.
            for _ in range(3 * amount):
                pattern.Scroll(auto.ScrollAmount.NoAmount, step, waitTime=0)
            return True
        control = control.GetParentControl()
    return False


def is_yes(answer: str) -> bool:
    answer = answer.lower()
    return any(word in answer for word in YES_WORDS) and not any(n in answer for n in ("不", "别", "取消", "no"))
