"""TTS高レベル管理: 合成→再生をワーカースレッドで直列化。

speak() は即時に戻り、再生開始/終了を on_start/on_end コールバックで通知する
(口パク・字幕同期に使用)。docs/specification.md §9.3。
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

from ..settings import TTSConfig
from .irodori import IrodoriTTS
from .player import AudioPlayer
from .server import TTSServerProcess

log = logging.getLogger(__name__)

OnStart = Callable[[], None]
OnEnd = Callable[[], None]


class TTSManager:
    def __init__(self, cfg: TTSConfig) -> None:
        self.cfg = cfg
        self.backend = IrodoriTTS(cfg)        # 将来 AivisSpeech 等に差し替え可
        self.player = AudioPlayer()
        self.server = TTSServerProcess(cfg)
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if not self.cfg.enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # サーバ自動起動はUIをブロックしないよう別スレッドで(health待ちが長いため)
        threading.Thread(target=self.server.start, daemon=True).start()

    def stop(self) -> None:
        self._running = False
        self.player.stop()
        if self._thread:
            self._q.put(None)  # sentinel
        self.server.stop()

    def speak(self, reply, on_start: OnStart | None = None,
              on_end: OnEnd | None = None) -> None:
        """reply.speech_tts を合成・再生(非ブロッキング)。"""
        if not self.cfg.enabled or not self._running:
            if on_end:
                on_end()
            return
        self._q.put((reply, on_start, on_end))

    def _loop(self) -> None:
        while self._running:
            item = self._q.get()
            if item is None:
                break
            reply, on_start, on_end = item
            try:
                audio = self.backend.synth(
                    reply.speech_tts,
                    speed=reply.tts.speed,
                    cfg_scale_text=reply.tts.cfg_scale_text,
                    cfg_scale_speaker=reply.tts.cfg_scale_speaker,
                )
                if audio:
                    if on_start:
                        on_start()
                    self.player.play(audio)
            except Exception as e:
                log.warning("TTS再生エラー: %s", e)
            finally:
                if on_end:
                    on_end()
