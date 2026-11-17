"""Offline wake word spotting with sherpa-onnx, so only speech after the wake word goes to the cloud.

Run `python -m ai_os.wake` once to download the model (~33 MB).
"""
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

from .config import Config

SAMPLE_RATE = 16000
MODEL_NAME = "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{MODEL_NAME}.tar.bz2"
DEFAULT_MODEL_DIR = Path.home() / ".cache" / "ai-os" / MODEL_NAME
CHECKPOINT = "epoch-12-avg-2-chunk-16-left-64.int8.onnx"


class WakeWordSpotter:
    def __init__(self, wake_word: str, model_dir: Path, threshold: float):
        import sherpa_onnx

        tokens = model_dir / "tokens.txt"
        phones = sherpa_onnx.text2token([wake_word], tokens=str(tokens), tokens_type="ppinyin")[0]
        keywords = Path(tempfile.gettempdir()) / "ai-os-keywords.txt"
        keywords.write_text(f"{' '.join(phones)} @{wake_word}\n", encoding="utf-8")
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(tokens),
            encoder=str(model_dir / f"encoder-{CHECKPOINT}"),
            decoder=str(model_dir / f"decoder-{CHECKPOINT}"),
            joiner=str(model_dir / f"joiner-{CHECKPOINT}"),
            keywords_file=str(keywords),
            num_threads=1,
            keywords_threshold=threshold,
        )
        self.stream = self.spotter.create_stream()

    def accept(self, frame: np.ndarray) -> bool:
        """Feeds one int16 frame; returns True when the wake word was just heard."""
        self.stream.accept_waveform(SAMPLE_RATE, frame.astype(np.float32) / 32768)
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
        if self.spotter.get_result(self.stream):
            self.spotter.reset_stream(self.stream)
            return True
        return False


def create_spotter(cfg: Config) -> WakeWordSpotter | None:
    """Returns None (fall back to matching the wake word in cloud transcripts) when local spotting is unavailable."""
    if not cfg.wake_word or cfg.wake_engine != "local":
        return None
    model_dir = Path(cfg.wake_model_dir) if cfg.wake_model_dir else DEFAULT_MODEL_DIR
    if not (model_dir / "tokens.txt").exists():
        print("[唤醒] 未找到本地唤醒模型，改为云端识别唤醒词。运行 python -m ai_os.wake 下载模型。")
        return None
    try:
        return WakeWordSpotter(cfg.wake_word, model_dir, cfg.wake_threshold)
    except ImportError:
        print("[唤醒] 未安装 sherpa-onnx，改为云端识别唤醒词。运行 pip install \"ai-os-desktop[wake]\" 安装。")
    except Exception as e:
        print(f"[唤醒] 本地唤醒初始化失败，改为云端识别唤醒词：{e}")
    return None


def download(target: Path = DEFAULT_MODEL_DIR) -> None:
    if (target / "tokens.txt").exists():
        print(f"模型已存在：{target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载 {MODEL_URL}")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "model.tar.bz2"
        urllib.request.urlretrieve(MODEL_URL, archive)
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(target.parent, filter="data")
    print(f"已下载到 {target}")


if __name__ == "__main__":
    download()
