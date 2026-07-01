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
import threading

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
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

_INSTANCE_KEY = "AIchan-single-instance"


def _install_sigint(app: QApplication) -> None:
    """Ctrl+C(SIGINT)で終了できるように(QtのC++ループ対策)。"""
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer(app)
    keepalive.start(200)
    keepalive.timeout.connect(lambda: None)


def _acquire_single_instance() -> QLocalServer | None:
    """多重起動防止。既に起動中なら None(そちらへ表示要求を送る)。"""
    probe = QLocalSocket()
    probe.connectToServer(_INSTANCE_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None
    QLocalServer.removeServer(_INSTANCE_KEY)  # 前回の残骸を掃除
    server = QLocalServer()
    server.listen(_INSTANCE_KEY)
    return server


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = AppConfig.load()

    app = QApplication(sys.argv)
    app.setApplicationName("AIちゃん")
    app.setQuitOnLastWindowClosed(False)
    _install_sigint(app)

    # 多重起動防止: 既に起動中なら、そのウィンドウを前面に出して終了する
    instance = _acquire_single_instance()
    if instance is None:
        log.info("すでに起動しています。二重起動を中止しました。")
        return 0

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

    # 二重起動を試みた別プロセスから通知が来たら前面表示
    instance.newConnection.connect(lambda: _raise_window(window))

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

    # LMStudio 自動起動(任意)。停止コマンドも用意(未指定なら lms を自動推定)。
    llm_proc = None
    if cfg.llm.autostart and cfg.llm.server_cmd:
        from .services import ManagedProcess
        llm_stop = list(cfg.llm.stop_cmd)
        if not llm_stop and "lms" in " ".join(cfg.llm.server_cmd):
            llm_stop = ["cmd", "/c", "lms server stop"]
        llm_proc = ManagedProcess(
            cfg.llm.server_cmd,
            ready_url=cfg.llm.base_url.rstrip("/") + "/models",
            name="LMStudio", stop_cmd=llm_stop,
        )

    # --- 先にウィンドウ表示(サーバ起動を待たせない) ---
    window.show()
    _raise_window(window)
    _log_status(cfg, llm, tts, recognizer)

    # --- サービス起動(UIをブロックしない) ---
    tts.start()                 # サーバ自動起動は内部で別スレッド
    orch.start()
    scheduler.start()
    if discord_bot:
        discord_bot.start()
    if mic is not None and cfg.stt.mode == "vad":
        mic.start_vad()
    if llm_proc is not None:     # health待ちが長いので別スレッドで
        threading.Thread(target=llm_proc.start, daemon=True).start()

    if cfg.update.auto_check:
        QTimer.singleShot(3000, lambda: window.check_updates(manual=False))

    def shutdown() -> None:
        log.info("終了処理: サーバ停止中…")
        scheduler.stop()
        orch.stop()
        tts.stop()               # TTSサーバも stop_cmd / wsl pkill で停止
        if mic is not None:
            mic.stop()
        if discord_bot:
            discord_bot.stop()
        if llm_proc is not None:
            llm_proc.stop()      # lms server stop 等
        window.state.save()
        db.close()

    app.aboutToQuit.connect(shutdown)
    run_event_loop = app.exec
    return run_event_loop()


def _raise_window(window: CharacterWindow) -> None:
    window.showNormal()
    window.raise_()
    window.activateWindow()


def _log_status(cfg: AppConfig, llm: LLMClient, tts: TTSManager, rec) -> None:
    log.info("LLM: %s", "接続" if llm.available() else "モック(LMStudio未接続)")
    log.info("TTS: %s", "有効" if cfg.tts.enabled else "無効")
    log.info("STT: %s", "有効" if (rec and rec.available()) else "無効")
    log.info("画面読み取り: %s / 自発発話: %s",
             "ON" if cfg.screen.enabled else "OFF",
             "ON" if cfg.proactive.enabled else "OFF")


if __name__ == "__main__":
    raise SystemExit(main())
