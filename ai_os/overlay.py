import ctypes
import queue
import threading
import tkinter as tk
import traceback
from typing import Callable

StatusFn = Callable[..., None]

STATES = {
    "idle": ("待命", "#6b7280"),
    "listening": ("聆听", "#22c55e"),
    "recognizing": ("识别", "#eab308"),
    "thinking": ("思考", "#3b82f6"),
    "acting": ("执行", "#a855f7"),
    "speaking": ("说话", "#f97316"),
}
WIDTH, HEIGHT, TOP = 460, 60, 12
MAX_DETAIL = 36
POLL_MS = 50

GWL_EXSTYLE = -20
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x8000000


def no_status(state: str, detail: str = "") -> None:
    pass


class Overlay:
    """Always-on-top status pill that never takes focus and lets clicks pass through.

    Tk must own the main thread, so the voice loop runs in a worker via run().
    """

    def __init__(self, hide_when_idle: bool = False):
        self.hide_when_idle = hide_when_idle
        self._updates: queue.Queue[tuple[str, str] | None] = queue.Queue()
        user32 = ctypes.windll.user32
        previous = user32.GetForegroundWindow()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.88)
        self.root.configure(bg="#111827")
        x = (self.root.winfo_screenwidth() - WIDTH) // 2
        self.root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{TOP}")

        self.dot = tk.Canvas(self.root, width=14, height=14, bg="#111827", highlightthickness=0)
        self.dot.place(x=16, y=12)
        self.dot_id = self.dot.create_oval(1, 1, 13, 13, fill=STATES["idle"][1], outline="")
        self.state_label = tk.Label(self.root, fg="white", bg="#111827", font=("Microsoft YaHei UI", 11, "bold"))
        self.state_label.place(x=38, y=6)
        self.detail_label = tk.Label(self.root, fg="#d1d5db", bg="#111827", font=("Microsoft YaHei UI", 10),
                                     anchor="w", width=48)
        self.detail_label.place(x=38, y=31)
        self._apply("idle", "")

        self.root.update_idletasks()
        hwnd = self.hwnd = user32.GetParent(self.root.winfo_id())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        if not hide_when_idle:
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        # Tk activates its window while creating it; hand focus back to whatever the user was using.
        if previous and user32.GetForegroundWindow() == hwnd:
            user32.SetForegroundWindow(previous)
        self.root.report_callback_exception = self._on_callback_error

    def status(self, state: str, detail: str = "") -> None:
        """Thread-safe; may be called from the worker."""
        self._updates.put((state, detail))

    def close(self) -> None:
        self._updates.put(None)

    def run(self, worker: Callable[[], None]) -> None:
        def target():
            try:
                worker()
            except Exception:
                traceback.print_exc()
            finally:
                self.close()

        threading.Thread(target=target, daemon=True).start()
        self.root.after(POLL_MS, self._poll)
        self.root.mainloop()

    def _poll(self) -> None:
        latest = ...
        try:
            while True:
                latest = self._updates.get_nowait()
                if latest is None:
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        if latest is not ...:
            self._apply(*latest)
        self.root.after(POLL_MS, self._poll)

    def _apply(self, state: str, detail: str) -> None:
        label, color = STATES.get(state, (state, "#6b7280"))
        detail = " ".join(detail.split())
        if len(detail) > MAX_DETAIL:
            detail = detail[:MAX_DETAIL - 1] + "…"
        self.dot.itemconfigure(self.dot_id, fill=color)
        self.state_label.configure(text=label)
        self.detail_label.configure(text=detail)
        if self.hide_when_idle and hasattr(self, "hwnd"):
            ctypes.windll.user32.ShowWindow(self.hwnd, SW_HIDE if state == "idle" else SW_SHOWNOACTIVATE)

    def _on_callback_error(self, exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            self.root.destroy()
        else:
            traceback.print_exception(exc_type, exc, tb)
