"""System-wide voice hotkey: brings DeepSeek Harness to the front and presses its in-app voice key (F8)."""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

from .screen import _process_name

user32 = ctypes.windll.user32

HOST_PROCESS = "deepseek harness"
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_SPACE, VK_F8, VK_CONTROL, VK_MENU = 0x20, 0x77, 0x11, 0x12
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xA105

_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _host_window() -> int:
    """The largest visible titled window of the DeepSeek Harness process, or 0."""
    best, best_area = 0, 0

    def visit(hwnd, _lparam):
        nonlocal best, best_area
        if not user32.IsWindowVisible(hwnd) or not user32.GetWindowTextLengthW(hwnd):
            return True
        if _process_name(hwnd) != HOST_PROCESS:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)
        if area > best_area:
            best, best_area = hwnd, area
        return True

    user32.EnumWindows(_EnumProc(visit), 0)
    return best


def _press(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)


def _trigger() -> None:
    hwnd = _host_window()
    if not hwnd:
        print("ai-os hotkey: DeepSeek Harness window not found", file=sys.stderr)
        return
    # Wait for the user to release Ctrl/Alt so the host sees a bare F8.
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_CONTROL, VK_MENU)):
        time.sleep(0.02)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if user32.GetForegroundWindow() != hwnd:
        # Tapping Alt lets SetForegroundWindow bypass Windows' foreground lock.
        _press(VK_MENU)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.25)
    _press(VK_F8)


def _loop() -> None:
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE):
        # Another AI OS instance (or another app) already owns it.
        return
    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                try:
                    _trigger()
                except Exception as e:
                    print(f"ai-os hotkey: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        user32.UnregisterHotKey(None, HOTKEY_ID)


def start() -> None:
    """Listen for Ctrl+Alt+Space in a daemon thread; AI_OS_HOTKEY=off disables it."""
    if os.environ.get("AI_OS_HOTKEY", "").lower() in {"off", "0", "false", "no"}:
        return
    threading.Thread(target=_loop, name="ai-os-hotkey", daemon=True).start()
