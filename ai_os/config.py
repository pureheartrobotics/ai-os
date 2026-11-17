import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Config:
    deepseek_api_key: str

    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_thinking: str

    vision_model: str
    vision_api_key: str
    vision_base_url: str

    stt_provider: str
    stt_api_key: str
    stt_base_url: str
    stt_model: str
    stt_language: str

    tts_provider: str
    tts_voice: str
    tts_rate: int

    wake_word: str
    wake_engine: str
    wake_threshold: float
    wake_model_dir: str
    wake_session_seconds: float
    vad_threshold: float
    vad_silence_ms: int
    max_steps: int


def load_config() -> Config:
    load_dotenv()
    deepseek_key = _get("DEEPSEEK_API_KEY")
    llm_key = _get("LLM_API_KEY") or deepseek_key
    llm_url = _get("LLM_BASE_URL", DEEPSEEK_BASE_URL)
    return Config(
        deepseek_api_key=deepseek_key,
        llm_api_key=llm_key,
        llm_base_url=llm_url,
        llm_model=_get("LLM_MODEL", "deepseek-flash"),
        llm_thinking=_get("LLM_THINKING", "disabled"),
        vision_model=_get("VISION_MODEL"),
        vision_api_key=_get("VISION_API_KEY") or llm_key,
        vision_base_url=_get("VISION_BASE_URL") or llm_url,
        stt_provider=_get("STT_PROVIDER", "deepseek").lower(),
        stt_api_key=_get("STT_API_KEY") or deepseek_key or llm_key,
        stt_base_url=_get("STT_BASE_URL", DEEPSEEK_BASE_URL),
        stt_model=_get("STT_MODEL", "whisper-1"),
        stt_language=_get("STT_LANGUAGE", "zh"),
        tts_provider=_get("TTS_PROVIDER", "deepseek").lower(),
        tts_voice=_get("TTS_VOICE", "stella"),
        tts_rate=int(_get("TTS_RATE", "200")),
        wake_word=_get("WAKE_WORD"),
        wake_engine=_get("WAKE_ENGINE", "local").lower(),
        wake_threshold=float(_get("WAKE_THRESHOLD", "0.25")),
        wake_model_dir=_get("WAKE_MODEL_DIR"),
        wake_session_seconds=float(_get("WAKE_SESSION_SECONDS", "30")),
        vad_threshold=float(_get("VAD_THRESHOLD", "500")),
        vad_silence_ms=int(_get("VAD_SILENCE_MS", "800")),
        max_steps=int(_get("MAX_STEPS", "25")),
    )
