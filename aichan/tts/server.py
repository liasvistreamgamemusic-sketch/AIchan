"""Irodori-TTS-Server の subprocess ライフサイクル管理(任意・autostart時)。

docs/specification.md §9.1。アプリ起動時に起動 → /health 待ち、終了時に停止。
"""
from __future__ import annotations

import logging
import subprocess
import time

from ..settings import TTSConfig
from .irodori import IrodoriTTS

log = logging.getLogger(__name__)


class TTSServerProcess:
    def __init__(self, cfg: TTSConfig) -> None:
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None

    def start(self, wait_sec: float = 30.0) -> bool:
        if not self.cfg.autostart_server or not self.cfg.server_cmd:
            return False
        client = IrodoriTTS(self.cfg)
        if client.health():
            log.info("TTSサーバは既に起動済み")
            return True
        log.info("TTSサーバ起動: %s", " ".join(self.cfg.server_cmd))
        try:
            self.proc = subprocess.Popen(self.cfg.server_cmd)
        except Exception as e:
            log.warning("TTSサーバ起動失敗: %s", e)
            return False
        # /health を待つ
        deadline = wait_sec
        while deadline > 0:
            if client.health():
                log.info("TTSサーバ ready")
                return True
            time.sleep(1.0)
            deadline -= 1.0
        log.warning("TTSサーバ ready 待ちタイムアウト")
        return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            log.info("TTSサーバ停止")
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
