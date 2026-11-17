"""DeepSeek standalone speech APIs: https://api-docs.deepseek.com/api/asr/ and /guides/tts/."""
import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com"


class DeepSeekSpeech:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, voice: str = "stella"):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )
        self.voice = voice

    def transcribe(self, wav: bytes) -> str:
        response = self.client.post("/v1/tools/asr", files={"file": ("speech.wav", wav, "audio/wav")})
        response.raise_for_status()
        return (response.json().get("text") or "").strip()

    def synthesize(self, text: str) -> bytes:
        response = self.client.post("/v1/tools/tts", json={
            "text": text, "voice_id": self.voice, "format": "wav", "filter_markdown": True,
        })
        response.raise_for_status()
        return response.content


def is_deepseek(base_url: str) -> bool:
    return "deepseek.com" in base_url
