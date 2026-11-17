import ctypes


def enable_dpi_awareness() -> None:
    """Must run before pyautogui/uiautomation are imported so screen coordinates are physical pixels."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
