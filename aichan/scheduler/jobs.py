"""自発発話・画面読み取り・記憶圧縮の定期実行(docs/specification.md §11, §6, §8.3.2)。

外部依存を避け、デーモンスレッド + ランダム間隔で実装。各ジョブは設定でオン/オフ。
"""
from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime

from ..settings import AppConfig

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, cfg: AppConfig, orchestrator, memory, llm) -> None:
        self.cfg = cfg
        self.orch = orchestrator
        self.memory = memory
        self.llm = llm
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_proactive = 0.0

    def start(self) -> None:
        if self.cfg.proactive.enabled:
            self._spawn(self._proactive_loop, "proactive")
        if self.cfg.screen.enabled:
            self._spawn(self._screen_loop, "screen")
        self._spawn(self._compress_loop, "compress")

    def stop(self) -> None:
        self._stop.set()

    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=target, daemon=True, name=f"sched-{name}")
        t.start()
        self._threads.append(t)

    # ---- 自発発話 -----------------------------------------------------
    def _proactive_loop(self) -> None:
        p = self.cfg.proactive
        while not self._stop.is_set():
            wait = random.randint(p.interval_min_sec, p.interval_max_sec)
            if self._sleep(wait):
                return
            now = time.time()
            if self._in_quiet_hours():
                continue
            if now - self._last_proactive < p.cooldown_sec:
                continue
            self._last_proactive = now
            log.info("proactive talk")
            self.orch.handle_proactive()

    def _in_quiet_hours(self) -> bool:
        h = datetime.now().hour
        s, e = self.cfg.proactive.quiet_start_hour, self.cfg.proactive.quiet_end_hour
        if s == e:
            return False
        if s < e:
            return s <= h < e
        return h >= s or h < e  # 日跨ぎ(例: 23〜8)

    # ---- 画面読み取り -------------------------------------------------
    def _screen_loop(self) -> None:
        s = self.cfg.screen
        while not self._stop.is_set():
            wait = random.randint(s.interval_min_sec, s.interval_max_sec)
            if self._sleep(wait):
                return
            if self._in_quiet_hours():
                continue
            log.info("screen read")
            self.orch.handle_screen()

    # ---- 記憶圧縮 -----------------------------------------------------
    def _compress_loop(self) -> None:
        interval = self.cfg.memory.compress_interval_sec
        while not self._stop.is_set():
            if self._sleep(interval):
                return
            try:
                n = self.memory.maybe_compress(self.llm)
                if n:
                    log.info("scheduled compression: %d msgs", n)
            except Exception as e:
                log.warning("圧縮ジョブ失敗: %s", e)

    def _sleep(self, seconds: float) -> bool:
        """中断可能なスリープ。停止要求が来たら True。"""
        return self._stop.wait(seconds)
