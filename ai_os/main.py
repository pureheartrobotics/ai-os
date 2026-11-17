import argparse
import sys
import winsound

from .actions import Actions, is_yes
from .agent import Agent
from .config import Config, load_config
from .overlay import Overlay, StatusFn, no_status
from .screen import ScreenReader
from .voice import Microphone, Speaker, SpeechToText, WakeWordGate
from .wake import create_spotter

EXIT_PHRASES = ("退出助手", "关闭助手", "退出程序")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI OS - 用语音控制电脑")
    parser.add_argument("--text", action="store_true", help="用键盘输入指令（调试用，不需要麦克风）")
    parser.add_argument("--once", metavar="指令", help="执行一条指令后退出")
    parser.add_argument("--no-overlay", action="store_true", help="不显示屏幕顶部的状态悬浮窗")
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.llm_api_key:
        sys.exit("请先复制 .env.example 为 .env 并填写 DEEPSEEK_API_KEY")

    voice_mode = not (args.text or args.once)
    if not voice_mode or args.no_overlay:
        session(cfg, args, voice_mode, no_status)
        return

    overlay = Overlay()

    def worker():
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            session(cfg, args, voice_mode, overlay.status)

    overlay.run(worker)


def session(cfg: Config, args: argparse.Namespace, voice_mode: bool, status: StatusFn) -> None:
    speaker = Speaker(cfg, status)
    mic = Microphone(cfg) if voice_mode else None
    stt = SpeechToText(cfg) if voice_mode else None
    spotter = create_spotter(cfg) if voice_mode else None
    gate = WakeWordGate(cfg)
    wake_hint = f"说“{cfg.wake_word}”唤醒我" if cfg.wake_word else ""

    def hear() -> str:
        if not voice_mode:
            return input("[你] ").strip()
        print("（聆听中…）")
        while True:
            mic.flush()
            if spotter and not gate.active:
                status("idle", wake_hint)
                mic.wait_for_wake(spotter)
                winsound.Beep(880, 80)
                gate.touch()
            if gate.active:
                status("listening", "请说")
            else:
                status("idle", wake_hint)
            wav = mic.listen(on_speech=lambda: status("listening", "正在听…"),
                             timeout_s=gate.remaining if spotter else None)
            if not wav:
                continue
            status("recognizing")
            text = stt.transcribe(wav)
            if text:
                print(f"[你] {text}")
                return text

    def ask(question: str) -> str:
        speaker.say(question)
        gate.touch()
        return hear()

    screen = ScreenReader()
    actions = Actions(cfg, screen, confirm=lambda q: is_yes(ask(q)), ask=ask)
    agent = Agent(cfg, speaker, actions, screen, status)

    if args.once:
        agent.run(args.once)
        return

    hint = f"{wake_hint}加指令" if voice_mode and wake_hint else "请说出指令"
    speaker.say(f"AI 助手已启动，{hint}。")

    while True:
        try:
            text = hear()
        except (KeyboardInterrupt, EOFError):
            break
        command = gate.filter(text) if voice_mode else text
        if command is None:
            continue
        if not command:
            speaker.say("我在。")
            continue
        if any(p in command for p in EXIT_PHRASES):
            break
        agent.run(command)
        gate.touch()

    speaker.say("再见。")
