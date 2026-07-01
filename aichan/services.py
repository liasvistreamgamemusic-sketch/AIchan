"""外部サービス(LMStudio / TTSサーバ等)の自動起動・停止。

依存を増やさないよう readiness 確認は urllib(標準ライブラリ)で行う。
"""
from __future__ import annotations

import logging
import subprocess
import time
import urllib.request

log = logging.getLogger(__name__)

# Windowsで子プロセス(cmd/lms等)のコンソール窓を出さない
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ManagedProcess:
    """コマンドで起動し、ready_url が応答するまで待ち、終了時に停止する。"""

    def __init__(self, cmd: list[str], ready_url: str | None = None,
                 name: str = "service", stop_cmd: list[str] | None = None) -> None:
        self.cmd = cmd
        self.ready_url = ready_url
        self.name = name
        self.stop_cmd = stop_cmd or []
        self.proc: subprocess.Popen | None = None
        self._started = False   # 自分で起動した時だけ停止する
        self._logf = None

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
            log.info("%s は既に起動済み(自動起動スキップ)", self.name)
            return True
        log.info("%s を自動起動: %s", self.name, " ".join(self.cmd))
        try:
            # 起動コマンドの出力(lms not found 等のエラー)をログに残す
            from .config import DATA_DIR
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._logf = open(DATA_DIR / f"{self.name.lower()}_autostart.log",
                              "w", encoding="utf-8", errors="replace")
            self.proc = subprocess.Popen(
                self.cmd, stdout=self._logf, stderr=subprocess.STDOUT,
                creationflags=_NO_WINDOW,
            )
            self._started = True
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
        # 自分で起動した時のみ停止(既存の常駐サーバは殺さない)。
        if self._started and self.stop_cmd:
            log.info("%s 停止コマンド: %s", self.name, " ".join(self.stop_cmd))
            try:
                subprocess.run(self.stop_cmd, timeout=15, creationflags=_NO_WINDOW)
            except Exception as e:
                log.warning("%s 停止コマンド失敗: %s", self.name, e)
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if self._logf:
            try:
                self._logf.close()
            except Exception:
                pass
            self._logf = None
