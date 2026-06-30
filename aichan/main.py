"""エントリポイント。全サブシステムを組み立てて起動する。

    uv run --no-project --python 3.12 --with PySide6 python -m aichan.main
    # 会話/音声/TTS まで使うには追加依存:
    #   --with openai --with requests --with sounddevice --with soundfile
    #   --with faster-whisper --with mss --with pillow --with pyyaml --with discord.py

各サブシステムは依存やサービスが無くても graceful に無効化され、最低限「立ち絵表示
+ テキスト会話(LLM不在ならモック応答)」は常に動く。
"""
from __future__ import annotations

import logging
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import config
from .llm.client import LLMClient
from .memory.db import MemoryDB
from .memory.store import Memory
from .orchestrator import Orchestrator
from .scheduler.jobs import Scheduler
from .settings import AppConfig
from .tts.manager import TTSManager
from .ui.character_window import CharacterWindow

log = logging.getLogger(__name__)


def _install_sigint(app: QApplication) -> None:
    """Ctrl+C(SIGINT)で終了できるように(QtのC++ループ対策)。"""
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer(app)
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = AppConfig.load()

    app = QApplication(sys.argv)
    app.setApplicationName("AIちゃん")
    app.setQuitOnLastWindowClosed(False)
    _install_sigint(app)

    # 立ち絵チェック
    cdir = config.character_dir(cfg.character.id)
    if not cdir.is_dir() or not any(cdir.glob("*.png")):
        sys.stderr.write(
            f"立ち絵が見つかりません: {cdir}\n"
            "先に背景除去を実行してください:\n"
            "  uv run --no-project --python 3.12 --with pillow --with numpy "
            "python tools/remove_bg.py --id sumire\n"
        )
        return 1

    # --- 外部サービス自動起動(任意) ---
    # TTSサーバは TTSManager.start() が自動起動する(tts.autostart_server)。
    # LMStudio は任意。llm.autostart=True かつ server_cmd 設定時のみ。
    llm_proc = None
    if cfg.llm.autostart and cfg.llm.server_cmd:
        from .services import ManagedProcess
        llm_proc = ManagedProcess(
            cfg.llm.server_cmd,
            ready_url=cfg.llm.base_url.rstrip("/") + "/models",
            name="LMStudio",
        )
        llm_proc.start()

    # --- コア構築 ---
    db = MemoryDB()
    memory = Memory(db, cfg.memory, cfg.character)
    llm = LLMClient(cfg.llm)
    tts = TTSManager(cfg.tts)

    state = config.WindowState.load()
    state.character_id = cfg.character.id
    window = CharacterWindow(
        state, controller=None, name=cfg.character.name, app_cfg=cfg
    )

    orch = Orchestrator(cfg, memory, llm, tts, hooks=window.make_hooks())
    window.controller = orch  # 入力欄 → orchestrator

    # STT(マイク)。numpy等の重い依存を最小構成で避けるため遅延 import。
    mic = recognizer = None
    if cfg.stt.enabled:
        try:
            from .stt.mic import MicListener
            from .stt.recognizer import Recognizer
            recognizer = Recognizer(cfg.stt)
            mic = MicListener(cfg.stt, recognizer, on_text=orch.handle_voice)
            orch.mic = mic  # window の PTT ボタンから参照
        except Exception as e:  # numpy/sounddevice 不在など
            log.warning("STT初期化スキップ: %s", e)

    scheduler = Scheduler(cfg, orch, memory, llm)

    # Discord(任意)
    discord_bot = None
    if cfg.discord.enabled:
        from .discord_bot.bot import DiscordBot
        discord_bot = DiscordBot(cfg.discord, orch)

    # --- 起動 ---
    tts.start()
    orch.start()
    scheduler.start()
    if discord_bot:
        discord_bot.start()
    if mic is not None and cfg.stt.mode == "vad":
        mic.start_vad()

    window.show()
    _log_status(cfg, llm, tts, recognizer)

    def shutdown() -> None:
        scheduler.stop()
        orch.stop()
        tts.stop()
        if mic is not None:
            mic.stop()
        if discord_bot:
            discord_bot.stop()
        if llm_proc is not None:
            llm_proc.stop()
        window.state.save()
        db.close()

    app.aboutToQuit.connect(shutdown)
    run_event_loop = app.exec
    return run_event_loop()


def _log_status(cfg: AppConfig, llm: LLMClient, tts: TTSManager, rec) -> None:
    log.info("LLM: %s", "接続" if llm.available() else "モック(LMStudio未接続)")
    log.info("TTS: %s", "有効" if cfg.tts.enabled else "無効")
    log.info("STT: %s", "有効" if (rec and rec.available()) else "無効")
    log.info("画面読み取り: %s / 自発発話: %s",
             "ON" if cfg.screen.enabled else "OFF",
             "ON" if cfg.proactive.enabled else "OFF")


if __name__ == "__main__":
    raise SystemExit(main())
