import collections
import io
import os
import queue
import re
import threading
import time
import wave
import winsound
from typing import TYPE_CHECKING, Callable

import numpy as np
import pyttsx3
import sounddevice as sd
from openai import OpenAI

from .config import DEEPSEEK_BASE_URL, Config
from .deepseek import DeepSeekSpeech
from .overlay import StatusFn, no_status

if TYPE_CHECKING:
    from .wake import WakeWordSpotter

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
PRE_ROLL_MS = 300
MIN_SPEECH_FRAMES = 3
MIN_UTTERANCE_S = 0.4
MAX_UTTERANCE_S = 20

SVSF_ASYNC, SVSF_PURGE = 1, 2

# Whisper-style models tend to emit these on silence or noise.
HALLUCINATIONS = ("谢谢观看", "字幕", "点赞", "订阅", "明镜", "请不吝")


class Microphone:
    """One always-open input stream with energy-based voice activity detection.

    Audio keeps queueing while the assistant thinks or speaks; call flush() before listening for a new turn.
    """

    def __init__(self, cfg: Config):
        self.threshold = cfg.vad_threshold
        self.silence_ms = cfg.vad_silence_ms
        self.noise_floor: float | None = None
        self._frames: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                      blocksize=FRAME_SAMPLES, callback=self._on_audio)
        self._stream.start()

    def _on_audio(self, indata, _frames, _time, _status) -> None:
        self._frames.put(indata[:, 0].copy())

    def flush(self) -> None:
        while not self._frames.empty():
            self._frames.get_nowait()

    def wait_for_wake(self, spotter: "WakeWordSpotter") -> None:
        while True:
            frame = self._frames.get()
            self._track_noise(_rms(frame))
            if spotter.accept(frame):
                return

    def wait_for_trigger(self, spotter: "WakeWordSpotter | None", pressed: threading.Event,
                         stop: threading.Event) -> str | None:
        """Blocks until the hotkey is pressed or the wake word heard: "hotkey", "wake", or None on stop."""
        while not stop.is_set():
            if pressed.is_set():
                pressed.clear()
                return "hotkey"
            try:
                frame = self._frames.get(timeout=0.1)
            except queue.Empty:
                continue
            self._track_noise(_rms(frame))
            if spotter and spotter.accept(frame):
                return "wake"
        return None

    def listen(self, on_speech: Callable[[], None] | None = None,
               timeout_s: float | None = None, cancel: threading.Event | None = None) -> bytes | None:
        """Returns one utterance, or None if it was too short, nobody spoke within timeout_s, or cancel was set."""
        pre_roll = collections.deque(maxlen=PRE_ROLL_MS // FRAME_MS)
        voiced: list[np.ndarray] = []
        threshold = self._threshold()
        loud_frames = 0
        silence = 0
        waited_ms = 0

        while True:
            frame = self._frames.get()
            if cancel is not None and cancel.is_set():
                return None
            rms = _rms(frame)

            if not voiced:
                waited_ms += FRAME_MS
                if timeout_s is not None and waited_ms >= timeout_s * 1000:
                    return None
                pre_roll.append(frame)
                loud_frames = loud_frames + 1 if rms > threshold else 0
                if loud_frames >= MIN_SPEECH_FRAMES:
                    voiced.extend(pre_roll)
                    if on_speech:
                        on_speech()
                else:
                    self._track_noise(rms)
                    threshold = self._threshold()
                continue

            voiced.append(frame)
            silence = silence + FRAME_MS if rms < threshold else 0
            if silence >= self.silence_ms or len(voiced) * FRAME_MS >= MAX_UTTERANCE_S * 1000:
                break

        audio = np.concatenate(voiced)
        if len(audio) / SAMPLE_RATE < MIN_UTTERANCE_S:
            return None
        return _to_wav(audio)


    def _track_noise(self, rms: float) -> None:
        self.noise_floor = rms if self.noise_floor is None else 0.95 * self.noise_floor + 0.05 * rms

    def _threshold(self) -> float:
        return max(self.threshold, (self.noise_floor or 0) * 3)


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


def _to_wav(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.astype(np.int16).tobytes())
    return buf.getvalue()


class SpeechToText:
    def __init__(self, cfg: Config):
        self.deepseek = (DeepSeekSpeech(cfg.stt_api_key, DEEPSEEK_BASE_URL)
                         if cfg.stt_provider == "deepseek" else None)
        self.client = None if self.deepseek else OpenAI(api_key=cfg.stt_api_key, base_url=cfg.stt_base_url)
        self.model = cfg.stt_model
        self.language = cfg.stt_language

    def transcribe(self, wav: bytes) -> str:
        if self.deepseek:
            text = self.deepseek.transcribe(wav)
        else:
            kwargs = {"language": self.language} if self.language else {}
            result = self.client.audio.transcriptions.create(
                model=self.model, file=("speech.wav", wav, "audio/wav"), **kwargs)
            text = (result.text or "").strip()
        if len(text) < 12 and any(h in text for h in HALLUCINATIONS):
            return ""
        return text


def sensevoice_dir() -> str | None:
    """The SenseVoice model DeepSeek Harness downloads for its Voice Input plugin, if present."""
    candidates = [os.environ.get("SENSEVOICE_MODEL_DIR", "")]
    dsh_home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
    candidates.append(os.path.join(dsh_home, "speech-to-text", "sensevoice", "models", "sensevoice-onnx"))
    for path in candidates:
        if path and os.path.exists(os.path.join(path, "model.int8.onnx")):
            return path
    return None


class LocalSpeechToText:
    """Offline recognition with SenseVoice through sherpa-onnx; audio never leaves the machine."""

    def __init__(self, model_dir: str):
        import sherpa_onnx

        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=os.path.join(model_dir, "model.int8.onnx"),
            tokens=os.path.join(model_dir, "tokens.txt"),
            language="auto",
            use_itn=True,
            num_threads=2,
        )

    def transcribe(self, wav: bytes) -> str:
        with wave.open(io.BytesIO(wav)) as w:
            rate = w.getframerate()
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        stream = self.recognizer.create_stream()
        stream.accept_waveform(rate, samples.astype(np.float32) / 32768)
        self.recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        # Noise decodes to a lone filler or punctuation.
        return text if len(_PUNCT.sub("", text)) >= 2 else ""


class Speaker:
    """DeepSeek TTS by default; falls back to the offline Windows voice if the request fails."""

    def __init__(self, cfg: Config, status: StatusFn = no_status):
        self.rate = cfg.tts_rate
        self.deepseek = (DeepSeekSpeech(cfg.deepseek_api_key, DEEPSEEK_BASE_URL, cfg.tts_voice)
                         if cfg.tts_provider == "deepseek" and cfg.deepseek_api_key else None)
        self.status = status
        self._engine = None

    def say(self, text: str) -> None:
        if not text:
            return
        print(f"[AI] {text}")
        self.status("speaking", text)
        if self.deepseek:
            try:
                winsound.PlaySound(self.deepseek.synthesize(text), winsound.SND_MEMORY)
                return
            except Exception as e:
                print(f"[TTS] DeepSeek 语音合成失败，改用本地语音：{e}")
        engine = self._local_engine()
        engine.say(text)
        engine.runAndWait()

    def say_until(self, text: str, cancel: threading.Event) -> bool:
        """Like say(), but stops as soon as cancel is set; returns False if it was interrupted."""
        if not text:
            return True
        print(f"[AI] {text}", flush=True)
        self.status("speaking", text)
        if self.deepseek:
            try:
                audio = self.deepseek.synthesize(text)
            except Exception as e:
                print(f"[TTS] DeepSeek 语音合成失败，改用本地语音：{e}")
            else:
                return self._play_until(audio, cancel)
        return self._sapi_until(text, cancel)

    @staticmethod
    def _play_until(audio: bytes, cancel: threading.Event) -> bool:
        # PlaySound can't play memory asynchronously, so go through a file.
        path = os.path.join(os.environ.get("TEMP", "."), "ai-os-reply.wav")
        with open(path, "wb") as f:
            f.write(audio)
        with wave.open(io.BytesIO(audio)) as w:
            duration = w.getnframes() / w.getframerate()
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        if cancel.wait(duration + 0.2):
            winsound.PlaySound(None, 0)
            return False
        return True

    def _sapi_until(self, text: str, cancel: threading.Event) -> bool:
        voice = self._sapi_voice()
        voice.Speak(text, SVSF_ASYNC)
        while not voice.WaitUntilDone(100):
            if cancel.is_set():
                voice.Speak("", SVSF_ASYNC | SVSF_PURGE)
                return False
        return True

    def _sapi_voice(self):
        if getattr(self, "_sapi", None) is None:
            import comtypes.client

            self._sapi = comtypes.client.CreateObject("SAPI.SpVoice")
            # pyttsx3 counts words per minute around 200; SAPI rates run from -10 to 10 around 0.
            self._sapi.Rate = max(-10, min(10, round((self.rate - 200) / 20)))
            voices = self._sapi.GetVoices()
            for i in range(voices.Count):
                ident = voices.Item(i).GetDescription().lower()
                if "chinese" in ident or "huihui" in ident or "中文" in ident:
                    self._sapi.Voice = voices.Item(i)
                    break
        return self._sapi

    def _local_engine(self):
        if self._engine is None:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self.rate)
            for voice in self._engine.getProperty("voices"):
                ident = f"{voice.id} {voice.name}".lower()
                if "zh" in ident or "chinese" in ident or "huihui" in ident:
                    self._engine.setProperty("voice", voice.id)
                    break
        return self._engine


_PUNCT = re.compile(r"[\s,，。.!！?？、:：;；\"'“”‘’]+")


class WakeWordGate:
    """Passes utterances that start with the wake word, or any utterance during an active session."""

    def __init__(self, cfg: Config):
        self.wake_word = _PUNCT.sub("", cfg.wake_word)
        self.session_seconds = cfg.wake_session_seconds
        self.active_until = 0.0

    @property
    def active(self) -> bool:
        return not self.wake_word or time.monotonic() < self.active_until

    @property
    def remaining(self) -> float:
        return max(0.0, self.active_until - time.monotonic())

    def touch(self) -> None:
        self.active_until = time.monotonic() + self.session_seconds

    def filter(self, text: str) -> str | None:
        if not self.wake_word:
            return text
        normalized = _PUNCT.sub("", text)
        if normalized.startswith(self.wake_word):
            self.touch()
            return normalized[len(self.wake_word):]
        if time.monotonic() < self.active_until:
            self.touch()
            return text
        return None
