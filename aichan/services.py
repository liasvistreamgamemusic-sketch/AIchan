"""外部サービス(LMStudio / TTSサーバ等)の自動起動・停止。

依存を増やさないよう readiness 確認は urllib(標準ライブラリ)で行う。
"""
from __future__ import annotations

import logging
import subprocess
import time
import urllib.request

log = logging.getLogger(__name__)


class ManagedProcess:
    """コマンドで起動し、ready_url が応答するまで待ち、終了時に停止する。"""

    def __init__(self, cmd: list[str], ready_url: str | None = None,
                 name: str = "service") -> None:
        self.cmd = cmd
        self.ready_url = ready_url
        self.name = name
        self.proc: subprocess.Popen | None = None

    def _ready(self) -> bool:
        if not self.ready_url:
            return True
        try:
            with urllib.request.urlopen(self.ready_url, timeout=2) as r:
                return r.status < 500
        except Exception:
            return False

    def start(self, wait_sec: float = 40.0) -> bool:
        if not self.cmd:
            return False
        if self._ready():
            log.info("%s は既に起動済み", self.name)
            return True
        log.info("%s を自動起動: %s", self.name, " ".join(self.cmd))
        try:
            self.proc = subprocess.Popen(self.cmd)
        except Exception as e:
            log.warning("%s の起動に失敗: %s", self.name, e)
            return False
        deadline = wait_sec
        while deadline > 0:
            if self._ready():
                log.info("%s ready", self.name)
                return True
            time.sleep(1.0)
            deadline -= 1.0
        log.warning("%s の ready 待ちがタイムアウト(起動はしている可能性)", self.name)
        return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            log.info("%s を停止", self.name)
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
