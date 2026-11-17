"""System-wide voice hotkey (Ctrl+Alt+Space).

Inside the MCP server it brings DeepSeek Harness to the front and presses its in-app voice key (F8).
The background assistant registers the same hotkey to listen without any window.
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable

from .paths import DAEMON_MUTEX
from .screen import _process_name

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.OpenMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
SYNCHRONIZE = 0x100000

HOST_PROCESS = "deepseek harness"
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_SPACE, VK_F8, VK_CONTROL, VK_MENU, VK_ESCAPE = 0x20, 0x77, 0x11, 0x12, 0x1B
WM_HOTKEY = 0x0312
WM_TIMER = 0x0113
YIELD_CHECK_MS = 2000
HOTKEY_ID = 0xA105
STOP_HOTKEY_ID = 0xA106

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


def daemon_running() -> bool:
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, DAEMON_MUTEX)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


def _loop(on_press: Callable[[], None], on_state: Callable[[bool], None] | None = None,
          retry_s: float | None = None, yield_to_daemon: bool = False) -> None:
    # Hotkeys belong to the registering thread's message queue, so register and pump here.
    while not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE):
        # Another AI OS instance (or another app) already owns it.
        if on_state:
            on_state(False)
        if retry_s is None:
            return
        time.sleep(retry_s)
    if on_state:
        on_state(True)
    if yield_to_daemon:
        user32.SetTimer(None, 0, YIELD_CHECK_MS, None)
    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_TIMER and daemon_running():
                return
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                try:
                    on_press()
                except Exception as e:
                    print(f"ai-os hotkey: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        user32.UnregisterHotKey(None, HOTKEY_ID)


def start() -> None:
    """Listen for Ctrl+Alt+Space in a daemon thread; AI_OS_HOTKEY=off disables it.

    The background assistant owns the hotkey while it runs, since it works without the window.
    """
    if os.environ.get("AI_OS_HOTKEY", "").lower() in {"off", "0", "false", "no"}:
        return
    threading.Thread(target=_host_loop, name="ai-os-hotkey", daemon=True).start()


def _host_loop() -> None:
    """Holds the hotkey whenever the background assistant doesn't, and hands it over when it starts."""
    while True:
        while daemon_running():
            time.sleep(YIELD_CHECK_MS / 1000)
        _loop(_trigger, yield_to_daemon=True)
        time.sleep(YIELD_CHECK_MS / 1000)


def start_for_daemon(on_press: Callable[[], None], on_state: Callable[[bool], None]) -> None:
    """Like start(), but keeps retrying while DeepSeek Harness's copy of the tools holds the hotkey."""
    threading.Thread(target=_loop, args=(on_press, on_state, 5.0), name="ai-os-hotkey", daemon=True).start()


def start_stop_key(on_stop: Callable[[], None]) -> bool:
    """Ctrl+Alt+Esc for the background assistant: stop listening, working or speaking."""
    registered = threading.Event()
    ok = [False]

    def loop() -> None:
        ok[0] = bool(user32.RegisterHotKey(None, STOP_HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_ESCAPE))
        registered.set()
        if not ok[0]:
            return
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == STOP_HOTKEY_ID:
                    on_stop()
        finally:
            user32.UnregisterHotKey(None, STOP_HOTKEY_ID)

    threading.Thread(target=loop, name="ai-os-stop-key", daemon=True).start()
    registered.wait(2)
    return ok[0]
