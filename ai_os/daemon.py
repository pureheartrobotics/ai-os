"""Background voice assistant that works without the DeepSeek Harness window.

Ctrl+Alt+Space (or the wake word, when one is configured) starts listening. Speech is recognized
locally with the SenseVoice model DeepSeek Harness already downloaded, the request runs through
`dsh --profile headless` with the ai-os desktop tools, and the answer is read aloud. The microphone
stays open for a few seconds afterwards for a follow-up in the same Session.

Normally started by `ai-os service start`, which also restarts it if it crashes.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import threading
import time
import traceback
import winsound
from ctypes import wintypes

from dotenv import load_dotenv

from . import hotkey
from .config import Config, load_config
from .dsh_brain import DshBrain, DshCancelled, DshError
from .overlay import Overlay, StatusFn, no_status
from .paths import DAEMON_MUTEX, STATE_DIR, STATE_FILE, STOP_FILE
from .voice import LocalSpeechToText, Microphone, Speaker, SpeechToText, sensevoice_dir
from .wake import create_spotter

FIRST_LISTEN_S = 8
FOLLOW_UP_S = 6
MAX_SPOKEN_CHARS = 240
EXIT_SETUP = 3

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE
ERROR_ALREADY_EXISTS = 183


class State:
    """What `ai-os service status` reports; written to daemon.json on every change."""

    def __init__(self):
        self.data = {
            "pid": os.getpid(),
            "startedAt": time.time(),
            "ready": False,
            "hotkey": "pending",
            "speech": None,
            "wakeWord": None,
            "problem": None,
            "lastTask": None,
            "lastError": None,
        }
        self._lock = threading.Lock()

    def update(self, **fields) -> None:
        with self._lock:
            self.data.update(fields, updatedAt=time.time())
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, STATE_FILE)


_MARKDOWN = re.compile(r"[*_`#>]+|\[([^\]]*)\]\([^)]*\)")


def spoken(text: str) -> str:
    """Markdown stripped and cut at a sentence end, since the reply is read aloud."""
    text = _MARKDOWN.sub(lambda m: m.group(1) or "", text)
    text = re.sub(r"^\s*(?:[-+]|\d+\.)\s+", "", text, flags=re.M)
    text = " ".join(text.split())
    if len(text) <= MAX_SPOKEN_CHARS:
        return text
    cut = max(text.rfind(p, 0, MAX_SPOKEN_CHARS) for p in "。！？；.!?")
    return text[:cut + 1] if cut > 40 else text[:MAX_SPOKEN_CHARS] + "……"


def assistant(cfg: Config, status: StatusFn, state: State, stop: threading.Event) -> None:
    brain = DshBrain(model=cfg.llm_model)
    model_dir = sensevoice_dir()
    if model_dir:
        stt, speech = LocalSpeechToText(model_dir), "local"
    elif cfg.stt_api_key:
        stt, speech = SpeechToText(cfg), "cloud"
    else:
        stt, speech = None, None
    problem = brain.problem() or (None if stt else
                                  "没有语音识别模型：在 DeepSeek Harness 的插件页启用「语音输入」并完成一次模型准备")
    state.update(speech=speech, problem=problem)
    if problem:
        print(f"[后台] 无法启动：{problem}", flush=True)
        stop.set()
        raise SystemExit(EXIT_SETUP)

    mic = Microphone(cfg)
    spotter = create_spotter(cfg)
    speaker = Speaker(cfg, status)
    keys = Keys()
    hotkey.start_for_daemon(keys.press, lambda ok: state.update(hotkey="ok" if ok else "busy"))
    stop_key = hotkey.start_stop_key(keys.stop)
    state.update(ready=True, stopKey=stop_key, wakeWord=cfg.wake_word if spotter else None)
    print(f"[后台] 已就绪：Ctrl+Alt+Space 开始说话，Ctrl+Alt+Esc 停止；"
          f"语音识别={speech}；唤醒词={cfg.wake_word if spotter else '无'}", flush=True)

    while not stop.is_set():
        status("idle")
        mic.flush()
        trigger = mic.wait_for_trigger(spotter, keys.pressed, stop)
        if trigger is None:
            break
        winsound.Beep(880, 80)
        keys.begin()
        try:
            converse(mic, stt, brain, speaker, status, state, keys, stop)
        except Exception as e:
            traceback.print_exc()
            state.update(lastError={"at": time.time(), "detail": f"{type(e).__name__}: {e}"})
            speaker.say_until("出错了，请再试一次。", keys.cancel)
        finally:
            keys.end()


class Keys:
    """Ctrl+Alt+Space starts listening, or interrupts and listens again; Ctrl+Alt+Esc stops everything."""

    def __init__(self):
        self.pressed = threading.Event()
        self.cancel = threading.Event()
        self.busy = False

    def press(self) -> None:
        if self.busy:
            self.cancel.set()
        self.pressed.set()

    def stop(self) -> None:
        self.pressed.clear()
        if self.busy:
            self.cancel.set()

    def begin(self) -> None:
        self.cancel.clear()
        self.busy = True

    def end(self) -> None:
        self.busy = False
        if self.cancel.is_set():
            winsound.Beep(440, 120)


def converse(mic: Microphone, stt, brain: DshBrain, speaker: Speaker, status: StatusFn, state: State,
             keys: Keys, stop: threading.Event) -> None:
    """One request plus follow-ups, until nobody speaks for a few seconds or a key interrupts."""
    cancel = keys.cancel
    timeout = FIRST_LISTEN_S
    while not stop.is_set() and not cancel.is_set():
        mic.flush()
        status("listening", "请说")
        wav = mic.listen(on_speech=lambda: status("listening", "正在听…"), timeout_s=timeout, cancel=cancel)
        if not wav or cancel.is_set():
            return
        status("recognizing")
        text = stt.transcribe(wav)
        if not text or cancel.is_set():
            return
        print(f"[你] {text}", flush=True)
        status("thinking", text)
        started = time.time()
        try:
            reply = brain.run(text, on_tool=lambda label: status("acting", label), cancel=cancel)
        except DshCancelled:
            print("[后台] 已取消", flush=True)
            return
        except DshError as e:
            print(f"[后台] 失败：{e}", flush=True)
            state.update(lastError={"at": time.time(), "detail": str(e)})
            speaker.say_until(f"没有完成：{e}", cancel)
            return
        state.update(lastTask={"at": started, "seconds": round(time.time() - started, 1),
                               "tools": reply.tools, "sessionId": reply.session_id}, lastError=None)
        if not speaker.say_until(spoken(reply.text) or "好了。", cancel):
            return
        timeout = FOLLOW_UP_S


def _watch_stop(stop: threading.Event) -> None:
    while not stop.wait(0.5):
        if STOP_FILE.exists():
            stop.set()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ai-os daemon", description="AI OS 后台语音助手（不需要打开 DeepSeek Harness）")
    parser.add_argument("--no-overlay", action="store_true", help="不显示屏幕顶部的状态条")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    kernel32.CreateMutexW(None, False, DAEMON_MUTEX)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        print("[后台] 已经有一个后台助手在运行", flush=True)
        raise SystemExit(EXIT_SETUP)

    load_dotenv(STATE_DIR / ".env")
    cfg = load_config()
    state = State()
    state.update()
    stop = threading.Event()
    threading.Thread(target=_watch_stop, args=(stop,), daemon=True).start()
    exit_code = 0

    def worker(status: StatusFn) -> None:
        nonlocal exit_code
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            try:
                assistant(cfg, status, state, stop)
            except SystemExit as e:
                exit_code = e.code or 0
            except Exception:
                traceback.print_exc()
                exit_code = 1

    if args.no_overlay:
        worker(no_status)
    else:
        overlay = Overlay(hide_when_idle=True)
        threading.Thread(target=lambda: (stop.wait(), overlay.close()), daemon=True).start()
        overlay.run(lambda: worker(overlay.status))
    state.update(ready=False)
    raise SystemExit(exit_code)
