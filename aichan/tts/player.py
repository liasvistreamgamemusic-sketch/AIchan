"""音声再生(sounddevice + soundfile、無ければ Windows winsound へフォールバック)。

再生は別スレッドでブロックし、完了/進捗のコールバックで口パク・字幕同期に使える。
"""
from __future__ import annotations

import io
import logging
import wave

log = logging.getLogger(__name__)


class AudioPlayer:
    def __init__(self) -> None:
        self._sd = None
        self._sf = None
        try:
            import sounddevice as sd
            import soundfile as sf
            self._sd = sd
            self._sf = sf
        except Exception:
            log.info("sounddevice/soundfile 不在 → winsound フォールバック(wavのみ)")

    def available(self) -> bool:
        return self._sd is not None or _has_winsound()

    def play(self, audio: bytes, volume: float = 1.0) -> None:
        """音声バイト列を再生(完了までブロック)。volume は倍率(1.0=そのまま)。"""
        if not audio:
            return
        if self._sd is not None and self._sf is not None:
            try:
                data, sr = self._sf.read(io.BytesIO(audio), dtype="float32")
                if volume != 1.0:
                    data = data * max(0.0, volume)
                self._sd.play(data, sr)
                self._sd.wait()
                return
            except Exception as e:
                log.warning("sounddevice 再生失敗(%s)→ フォールバック", e)
        self._play_winsound(audio)

    def stop(self) -> None:
        if self._sd is not None:
            try:
                self._sd.stop()
            except Exception:
                pass

    def _play_winsound(self, audio: bytes) -> None:
        if not _is_wav(audio) or not _has_winsound():
            return
        import tempfile
        import winsound  # type: ignore
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio)
            path = f.name
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME)
        finally:
            import os
            try:
                os.unlink(path)
            except OSError:
                pass


def _is_wav(audio: bytes) -> bool:
    try:
        wave.open(io.BytesIO(audio), "rb").close()
        return True
    except Exception:
        return audio[:4] == b"RIFF"


def _has_winsound() -> bool:
    try:
        import winsound  # noqa: F401
        return True
    except ImportError:
        return False
