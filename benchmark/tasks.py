import os
import shutil
import subprocess
import time
import winreg
from dataclasses import dataclass
from typing import Callable

import pyautogui
import uiautomation as auto

from .webform import URL, FormServer
from .workbench import Workbench

BENCH_DIR = os.path.join(os.path.expanduser("~"), "aios-bench")
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
SCRIPTED_AGENTS = ("powershell", "curl", "python", "wget", "httpie", "go-http", "node")

Check = tuple[bool, str]


@dataclass
class Task:
    id: str
    title: str
    prompt: str
    verify: Callable[[], Check]
    setup: Callable[[], None] = lambda: None
    teardown: Callable[[], None] = lambda: None


def _calculator() -> auto.WindowControl | None:
    window = auto.WindowControl(searchDepth=1, RegexName="^(计算器|Calculator)$")
    return window if window.Exists(2) else None


def _close_calculator() -> None:
    subprocess.run(["taskkill", "/im", "CalculatorApp.exe", "/f"], capture_output=True)
    time.sleep(0.5)


def _calculator_text(automation_id: str) -> str:
    window = _calculator()
    if window is None:
        return ""
    control = window.Control(AutomationId=automation_id)
    return control.Name if control.Exists(2) else ""


def _calc_standard_mode() -> None:
    _close_calculator()
    os.startfile("calc")
    time.sleep(2.5)
    window = _calculator()
    if window:
        window.SetActive()
        time.sleep(0.3)
        pyautogui.hotkey("alt", "1")
        time.sleep(0.5)
    _close_calculator()


def _verify_multiply() -> Check:
    text = _calculator_text("CalculatorResults")
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits == "7006652", f"计算器显示：{text or '（未找到计算器）'}"


def _verify_scientific() -> Check:
    header = _calculator_text("Header")
    return ("科学" in header or "Scientific" in header), f"计算器模式：{header or '（未找到计算器）'}"


class _Theme:
    def __init__(self):
        self.saved: dict[str, int] = {}

    def setup(self) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                try:
                    self.saved[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    pass
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1)
        subprocess.run(["taskkill", "/im", "SystemSettings.exe", "/f"], capture_output=True)

    def verify(self) -> Check:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE) as key:
            value = winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
        return value == 0, f"AppsUseLightTheme={value}（0 表示深色）"

    def teardown(self) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE, 0, winreg.KEY_WRITE) as key:
            for name, value in self.saved.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


class _Form:
    def __init__(self):
        self.server = FormServer()

    def setup(self) -> None:
        self.server = FormServer()
        self.server.start()

    def verify(self) -> Check:
        if not self.server.submissions:
            return False, "没有收到提交"
        s = self.server.submissions[-1]
        ua = s.get("user_agent", "")
        problems = []
        if s.get("name") != "张三":
            problems.append(f"姓名={s.get('name')!r}")
        if s.get("city") != "杭州":
            problems.append(f"城市={s.get('city')!r}")
        if s.get("agree") != "yes":
            problems.append("未勾选同意条款")
        if s.get("token") not in self.server.tokens:
            problems.append("令牌无效（不是从页面提交的）")
        if "Mozilla" not in ua or any(a in ua.lower() for a in SCRIPTED_AGENTS):
            problems.append(f"不是浏览器提交（User-Agent: {ua[:60]}）")
        return not problems, "；".join(problems) or "表单内容正确，且来自浏览器"

    def teardown(self) -> None:
        self.server.stop()


def _reset_bench_dir() -> None:
    os.makedirs(BENCH_DIR, exist_ok=True)
    shutil.rmtree(os.path.join(BENCH_DIR, "测试报告"), ignore_errors=True)
    note = os.path.join(BENCH_DIR, "note.txt")
    if os.path.exists(note):
        os.remove(note)


def _open_explorer_paths() -> list[str]:
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "(New-Object -ComObject Shell.Application).Windows() | "
              "ForEach-Object { try { $_.Document.Folder.Self.Path } catch {} }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)
    return [p.strip() for p in out.stdout.decode("utf-8", "replace").splitlines() if p.strip()]


def _verify_folder() -> Check:
    created = os.path.isdir(os.path.join(BENCH_DIR, "测试报告"))
    paths = [p.lower().rstrip("\\") for p in _open_explorer_paths()]
    in_explorer = any(p in (BENCH_DIR.lower(), os.path.join(BENCH_DIR, "测试报告").lower()) for p in paths)
    detail = f"文件夹{'已' if created else '未'}创建；资源管理器{'已' if in_explorer else '未'}打开该目录"
    return created and in_explorer, detail


def _verify_note() -> Check:
    path = os.path.join(BENCH_DIR, "note.txt")
    if not os.path.exists(path):
        return False, "note.txt 不存在"
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        lines = [line.strip() for line in f.read().splitlines() if line.strip()]
    return lines == ["你好", "AI OS"], f"文件内容：{lines}"


class _WorkbenchTask:
    def __init__(self, scenario: str, verify: Callable[[Workbench], Check]):
        self.bench = Workbench(scenario)
        self._verify = verify

    def setup(self) -> None:
        self.bench.start()

    def verify(self) -> Check:
        return self._verify(self.bench)

    def teardown(self) -> None:
        self.bench.stop()


def _verify_dialog(bench: Workbench) -> Check:
    if bench.last("cleared"):
        return True, "已在确认框中确认清空"
    if bench.last("cancelled"):
        return False, "确认框里选了“否”"
    return False, "没有触发清空"


def _verify_tabs(bench: Workbench) -> Check:
    saved = bench.last("saved")
    if not saved:
        return False, "没有点击保存"
    expected = {"user": "lisi", "role": "编辑", "twofa": True, "timeout": 30}
    wrong = [f"{k}={saved.get(k)!r}" for k, v in expected.items() if saved.get(k) != v]
    return not wrong, "；".join(wrong) or "四个字段全部正确并已保存"


def _verify_list(bench: Workbench) -> Check:
    done = bench.last("done")
    if not done:
        return False, "没有在详情窗口中标记完成"
    return done.get("item") == "项目 237", f"标记完成的是：{done.get('item')}"


_theme = _Theme()
_form = _Form()
_dialog = _WorkbenchTask("dialog", _verify_dialog)
_tabs = _WorkbenchTask("tabs_form", _verify_tabs)
_list = _WorkbenchTask("long_list", _verify_list)

TASKS = [
    Task("calc_multiply", "计算器乘法",
         "打开计算器，用它计算 1234 × 5678，把结果留在计算器屏幕上。",
         _verify_multiply, setup=_close_calculator, teardown=_close_calculator),
    Task("calc_scientific", "计算器切换科学模式",
         "打开计算器，把它切换到“科学”模式。",
         _verify_scientific, setup=_calc_standard_mode, teardown=_close_calculator),
    Task("dark_mode", "设置里切换深色模式",
         "打开 Windows 设置，在“个性化 > 颜色”里把应用的颜色模式改成“深色”。",
         _theme.verify, setup=_theme.setup, teardown=_theme.teardown),
    Task("web_form", "浏览器填写表单",
         f"在浏览器中打开 {URL} ，姓名填“张三”，城市选择“杭州”，勾选“我同意条款”，然后点击“提交”按钮。",
         _form.verify, setup=_form.setup, teardown=_form.teardown),
    Task("explorer_folder", "资源管理器新建文件夹",
         f"在文件资源管理器中打开文件夹 {BENCH_DIR} ，在里面新建一个名为“测试报告”的文件夹。",
         _verify_folder, setup=_reset_bench_dir),
    Task("notepad_save", "记事本写入并保存",
         f"用记事本新建一个文档，写两行：第一行“你好”，第二行“AI OS”，保存为 {os.path.join(BENCH_DIR, 'note.txt')} 。"
         "不要修改记事本里其他已打开的标签页。",
         _verify_note, setup=_reset_bench_dir),
    Task("dialog_confirm", "确认弹窗",
         "在“AI OS 测试工作台”窗口里点击“清空记录”，并在弹出的确认框中确认。",
         _dialog.verify, setup=_dialog.setup, teardown=_dialog.teardown),
    Task("tabs_form", "多标签页表单",
         "在“AI OS 测试工作台”窗口里：用户名填 lisi，角色选“编辑”；切到“高级”页，勾选“启用双重验证”，"
         "把超时改成 30 分钟；最后点击“保存”。",
         _tabs.verify, setup=_tabs.setup, teardown=_tabs.teardown),
    Task("long_list", "长列表与详情窗口",
         "在“AI OS 测试工作台”窗口的列表里找到“项目 237”并选中，点击“打开”，然后在弹出的详情窗口中点击“标记完成”。",
         _list.verify, setup=_list.setup, teardown=_list.teardown),
]
HARD_TASKS = ["dialog_confirm", "tabs_form", "long_list"]
