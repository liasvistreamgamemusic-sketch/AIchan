"""音声→テキスト。faster-whisper を既定、無ければ無効(graceful)。

docs/specification.md §10。device は auto/cuda/cpu。Vulkanで動かす場合は
whisper.cpp バックエンド(別実装)を選ぶ。
"""
from __future__ import annotations

import logging

import numpy as np

from ..settings import STTConfig

log = logging.getLogger(__name__)


class Recognizer:
    def __init__(self, cfg: STTConfig) -> None:
        self.cfg = cfg
        self._model = None
        if not cfg.enabled:
            return
        try:
            from faster_whisper import WhisperModel

            device = cfg.device
            compute = "float16" if device in ("cuda",) else "int8"
            if device == "auto":
                device, compute = "cpu", "int8"
            self._model = WhisperModel(cfg.model, device=device, compute_type=compute)
            log.info("faster-whisper ready (model=%s, device=%s)", cfg.model, device)
        except Exception as e:
            log.warning("faster-whisper 初期化失敗(%s)→ STT無効", e)

    def available(self) -> bool:
        return self._model is not None

    def transcribe(self, audio: np.ndarray, samplerate: int) -> str:
        """float32 mono [-1,1] の音声を文字起こし。"""
        if self._model is None or audio.size == 0:
            return ""
        try:
            if samplerate != 16000:
                audio = _resample(audio, samplerate, 16000)
            segments, _ = self._model.transcribe(
                audio, language=self.cfg.language, vad_filter=True
            )
            return "".join(s.text for s in segments).strip()
        except Exception as e:
            log.warning("文字起こし失敗: %s", e)
            return ""


def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return audio
    n = int(round(len(audio) * dst / src))
    if n <= 0:
        return audio
    x_old = np.linspace(0, 1, len(audio), endpoint=False)
    x_new = np.linspace(0, 1, n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)
