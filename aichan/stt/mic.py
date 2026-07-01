"""マイク入力 + 発話区間検出 → 文字起こし(docs/specification.md §10)。

2モード:
- PTT(push-to-talk): start_recording()/stop_recording() で囲んだ区間を認識。
- VAD(常時): webrtcvad で無音区切りし、発話のたびに認識。
認識結果は on_text(text) コールバックで通知。マイク/依存が無ければ no-op。
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

from ..settings import STTConfig
from .recognizer import Recognizer

log = logging.getLogger(__name__)

OnText = Callable[[str], None]


class MicListener:
    def __init__(self, cfg: STTConfig, recognizer: Recognizer, on_text: OnText) -> None:
        self.cfg = cfg
        self.rec = recognizer
        self.on_text = on_text
        self._sd = None
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._recording = False
        self._lock = threading.Lock()
        try:
            import sounddevice as sd
            self._sd = sd
        except Exception:
            log.info("sounddevice 不在 → マイク入力無効")

    def available(self) -> bool:
        return self._sd is not None and self.rec.available()

    # ---- PTT ----------------------------------------------------------
    def start_recording(self) -> None:
        if not self.available() or self._recording:
            return
        with self._lock:
            self._frames = []
            self._recording = True
        self._stream = self._sd.InputStream(
            samplerate=self.cfg.samplerate, channels=1, dtype="float32",
            callback=self._on_audio,
        )
        self._stream.start()

    def stop_recording(self) -> None:
        if not self._recording:
            return
        with self._lock:
            self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        audio = (
            np.concatenate(self._frames) if self._frames else np.array([], dtype="float32")
        )
        # 認識は別スレッドで(UIブロック回避)
        threading.Thread(target=self._recognize, args=(audio,), daemon=True).start()

    def _on_audio(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if self._recording:
            self._frames.append(indata[:, 0].copy())

    def _recognize(self, audio: np.ndarray) -> None:
        dur = len(audio) / self.cfg.samplerate if audio.size else 0.0
        log.info("録音 %.1f秒 を文字起こし中…", dur)
        text = self.rec.transcribe(audio, self.cfg.samplerate)
        log.info("文字起こし結果: %r", text)
        if text:
            self.on_text(text)

    # ---- VAD(常時) --------------------------------------------------
    def start_vad(self) -> None:
        """常時リスニング。webrtcvad があれば区切り、無ければ単純無音検出。"""
        if not self.available():
            return
        threading.Thread(target=self._vad_loop, daemon=True).start()

    def _vad_loop(self) -> None:
        try:
            import webrtcvad
            vad = webrtcvad.Vad(self.cfg.vad_aggressiveness)
        except Exception:
            vad = None
        sr = 16000
        frame_ms = 30
        frame_len = int(sr * frame_ms / 1000)
        buf: list[np.ndarray] = []
        silence = 0
        speaking = False
        self._recording = True
        with self._sd.InputStream(samplerate=sr, channels=1, dtype="float32") as stream:
            while self._recording:
                block, _ = stream.read(frame_len)
                mono = block[:, 0]
                is_speech = _is_speech(mono, vad, sr)
                if is_speech:
                    buf.append(mono.copy())
                    speaking = True
                    silence = 0
                elif speaking:
                    silence += 1
                    buf.append(mono.copy())
                    if silence > 20:  # ~0.6s 無音で区切り
                        audio = np.concatenate(buf)
                        buf, speaking, silence = [], False, 0
                        threading.Thread(
                            target=self._recognize, args=(audio,), daemon=True
                        ).start()

    def stop(self) -> None:
        self._recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


def _is_speech(mono: np.ndarray, vad, sr: int) -> bool:
    if vad is not None:
        pcm16 = (np.clip(mono, -1, 1) * 32767).astype(np.int16).tobytes()
        try:
            return vad.is_speech(pcm16, sr)
        except Exception:
            pass
    # フォールバック: 音量しきい値
    return float(np.sqrt(np.mean(mono ** 2))) > 0.015
