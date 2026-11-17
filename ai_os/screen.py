import base64
import ctypes
import io
import os
import re
import time
from dataclasses import dataclass

import uiautomation as auto
from PIL import ImageGrab

INTERACTIVE_TYPES = {
    "ButtonControl", "EditControl", "HyperlinkControl", "MenuItemControl",
    "ListItemControl", "TabItemControl", "CheckBoxControl", "RadioButtonControl",
    "ComboBoxControl", "TreeItemControl", "DataItemControl", "SplitButtonControl",
    "MenuBarControl", "DocumentControl",
}
CONTEXT_TYPES = {"TextControl", "WindowControl", "TitleBarControl"}
IGNORED_WINDOW_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}
TRUNCATED_NOTE = "（控件过多，列表已截断；必要时使用 look_at_screen）"
# Zero-width/bidi marks and icon-font glyphs (Private Use Area) that apps embed in control names.
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\ue000-\uf8ff]")

user32 = ctypes.windll.user32


@dataclass
class Element:
    id: int
    kind: str
    name: str
    x: int
    y: int

    def describe(self) -> str:
        return f"[{self.id}] {self.kind} {self.name}" if self.name else f"[{self.id}] {self.kind}"


@dataclass
class Window:
    title: str
    handle: int
    process: str


def _process_name(hwnd: int) -> str:
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.c_ulong(len(buf))
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].removesuffix(".exe").lower()
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


class ScreenReader:
    """Lists the foreground window's controls.

    Ids are stable within one foreground window: the same control keeps its id across reads,
    so callers that keep earlier listings in context can be sent only what changed.
    """

    def __init__(self, max_elements: int = 150, time_budget_s: float = 3.0, max_name: int = 40):
        self.max_elements = max_elements
        self.time_budget_s = time_budget_s
        self.max_name = max_name
        self.elements: dict[int, Element] = {}
        self._window_handle: int | None = None
        self._title = ""
        self._truncated = False
        self._ids: dict[tuple, int] = {}

    def snapshot(self) -> str:
        """Full listing of the foreground window."""
        if not self._refresh()[0]:
            return "（无法获取前台窗口）"
        return self._full_listing()

    def changes(self) -> str:
        """Only what changed since the previous read; a full listing when the foreground window changed."""
        ok, window_changed, added, removed = self._refresh()
        if not ok:
            return "（无法获取前台窗口）"
        if window_changed:
            return "前台窗口已切换。\n" + self._full_listing()
        if not added and not removed:
            return f"前台窗口: {self._title}（控件无变化）"
        lines = [f"前台窗口: {self._title}"]
        if added:
            lines.append(f"新增 {len(added)} 个控件:")
            lines += [self.elements[i].describe() for i in added]
        if removed:
            lines.append(f"消失 {len(removed)} 个控件: " + ",".join(map(str, removed)))
        if self._truncated:
            lines.append(TRUNCATED_NOTE)
        return "\n".join(lines)

    def _full_listing(self) -> str:
        lines = [f"前台窗口: {self._title}"] + [e.describe() for e in self.elements.values()]
        if self._truncated:
            lines.append(TRUNCATED_NOTE)
        return "\n".join(lines)

    def _refresh(self) -> tuple[bool, bool, list[int], list[int]]:
        """Rescans; returns (ok, window_changed, added_ids, removed_ids)."""
        window = auto.GetForegroundControl()
        if window is None:
            return False, False, [], []
        handle = window.NativeWindowHandle
        window_changed = handle != self._window_handle
        if window_changed:
            self._window_handle = handle
            self._ids = {}
            self.elements = {}
        self._title = window.Name or "(无标题)"

        previous = set(self.elements)
        self.elements = {}
        for kind, name, x, y in self._scan(window):
            key = (kind, name, x, y)
            element_id = self._ids.setdefault(key, len(self._ids) + 1)
            self.elements[element_id] = Element(element_id, kind, name, x, y)

        current = set(self.elements)
        return True, window_changed, sorted(current - previous), sorted(previous - current)

    def _scan(self, window: auto.Control):
        self._truncated = False
        count = 0
        deadline = time.monotonic() + self.time_budget_s
        for control, _depth in auto.WalkControl(window, includeTop=False, maxDepth=25):
            if time.monotonic() > deadline or count >= self.max_elements:
                self._truncated = True
                return
            try:
                kind = control.ControlTypeName
                if kind not in INTERACTIVE_TYPES and kind not in CONTEXT_TYPES:
                    continue
                name = _INVISIBLE.sub("", control.Name or "").strip().replace("\n", " ")
                if kind in CONTEXT_TYPES and not name:
                    continue
                rect = control.BoundingRectangle
                if rect.width() <= 0 or rect.height() <= 0 or control.IsOffscreen:
                    continue
                if kind == "ButtonControl" and control.GetParentControl().ControlTypeName == "ScrollBarControl":
                    continue
                if kind == "TextControl" and control.GetParentControl().ControlTypeName == "ButtonControl":
                    continue
            except Exception:
                continue
            if len(name) > self.max_name:
                name = name[:self.max_name] + "…"
            count += 1
            yield kind.removesuffix("Control"), name, rect.xcenter(), rect.ycenter()

    def list_windows(self) -> list[Window]:
        windows = []
        for control in auto.GetRootControl().GetChildren():
            try:
                if (control.ClassName in IGNORED_WINDOW_CLASSES or not control.Name
                        or control.ProcessId == os.getpid()):
                    continue
                hwnd = control.NativeWindowHandle
                windows.append(Window(control.Name, hwnd, _process_name(hwnd)))
            except Exception:
                continue
        return windows

    @staticmethod
    def focus(window: Window) -> None:
        hwnd = window.handle
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        # Tapping Alt lets SetForegroundWindow bypass Windows' foreground lock.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)


def screenshot_base64(max_width: int = 1280) -> tuple[str, float, tuple[int, int]]:
    """Returns (jpeg base64, scale from screen to image, image size)."""
    image = ImageGrab.grab()
    scale = min(1.0, max_width / image.width)
    if scale < 1.0:
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode(), scale, image.size
