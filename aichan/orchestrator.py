"""対話制御コア(docs/specification.md §3.1)。

すべての入力(テキスト/音声/画面/自発/Discord)を受け取り、記憶からプロンプトを
構築 → LLM → 構造化出力をパース → 記憶へ保存 → UI更新(感情/字幕)+ TTS、を一貫制御。

LLM呼び出しは1つのワーカースレッドで直列化し、UIをブロックしない。UI更新は hooks
経由(UI側でスレッド安全にマーシャリングする)。
"""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .llm import prompt
from .llm.client import LLMClient
from .llm.schema import Reply, parse_reply
from .memory.store import Memory
from .settings import AppConfig
from .tts.manager import TTSManager
from .vision.screen import ScreenCapturer

log = logging.getLogger(__name__)


@dataclass
class Hooks:
    """UIなどへの通知口。既定は no-op。UI側でQtシグナルへつなぐとスレッドセーフになる。"""
    reply_ready: Callable[[Reply, str], None] = lambda reply, source: None
    user_said: Callable[[str, str], None] = lambda text, source: None
    thinking_changed: Callable[[bool], None] = lambda busy: None
    speaking_changed: Callable[[bool], None] = lambda speaking: None


class Orchestrator:
    def __init__(self, cfg: AppConfig, memory: Memory, llm: LLMClient,
                 tts: TTSManager, hooks: Hooks | None = None) -> None:
        self.cfg = cfg
        self.memory = memory
        self.llm = llm
        self.tts = tts
        self.hooks = hooks or Hooks()
        self.screen = ScreenCapturer(cfg.screen)
        self._q: "queue.Queue[tuple | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False

    # ---- ライフサイクル ----------------------------------------------
    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="orchestrator")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._q.put(None)

    # ---- 入力の入口(どこから呼んでも良い) --------------------------
    def handle_text(self, text: str) -> None:
        if text.strip():
            self._submit(text.strip(), prompt.SRC_TEXT)

    def handle_voice(self, text: str) -> None:
        if text.strip():
            self._submit(text.strip(), prompt.SRC_VOICE)

    def handle_discord(self, text: str, reply_cb: Callable[[Reply], None] | None = None) -> None:
        if text.strip():
            self._submit(text.strip(), prompt.SRC_DISCORD, reply_cb=reply_cb)

    def handle_proactive(self) -> None:
        self._submit("", prompt.SRC_PROACTIVE)

    def handle_screen(self) -> None:
        image = self.screen.capture_png()
        if image is None:
            return
        self._submit("", prompt.SRC_SCREEN, image=image)

    # ---- 内部 ---------------------------------------------------------
    def _submit(self, user_input: str, source: str, image: bytes | None = None,
                reply_cb: Callable[[Reply], None] | None = None) -> None:
        self._q.put((user_input, source, image, reply_cb))

    def _loop(self) -> None:
        while self._running:
            item = self._q.get()
            if item is None:
                break
            user_input, source, image, reply_cb = item
            try:
                self._process(user_input, source, image, reply_cb)
            except Exception as e:
                log.exception("生成処理でエラー: %s", e)
                self.hooks.thinking_changed(False)

    def _correct_tts_reading(self, reply) -> None:
        """TTSが正しく発音するよう、ユーザー名(漢字)を読み(かな)に置換する。

        字幕用 speech は表示名のまま。speech_tts のみ矯正。
        """
        u = self.cfg.user
        if u.name and u.name_reading and u.name != u.name_reading:
            reply.speech_tts = reply.speech_tts.replace(u.name, u.name_reading)

    def _process(self, user_input: str, source: str, image: bytes | None,
                 reply_cb: Callable[[Reply], None] | None = None) -> None:
        # ユーザー発話の表示・記録(自発/画面はユーザー発話なし)
        if user_input and source in (prompt.SRC_TEXT, prompt.SRC_VOICE, prompt.SRC_DISCORD):
            self.hooks.user_said(user_input, source)
            self.memory.record_user(user_input, source=source)

        self.hooks.thinking_changed(True)
        ctx = self.memory.context(user_input, source)
        messages = prompt.build_messages(
            persona=ctx["persona"],
            long_term_summary=ctx["long_term_summary"],
            related_memories=ctx["related_memories"],
            user_profile=ctx["user_profile"],
            recent_turns=ctx["recent_turns"],
            user_input=user_input,
            source=source,
            user_address=self.cfg.user.call_display,
        )
        raw = self.llm.chat(messages, image_png=image)
        reply = parse_reply(raw)
        self._correct_tts_reading(reply)
        self.hooks.thinking_changed(False)

        if reply.is_empty:
            return
        self.memory.record_assistant(reply, source=source)

        # UI更新(感情+字幕)
        self.hooks.reply_ready(reply, source)

        # 要求元への返信(Discord等)
        if reply_cb is not None:
            try:
                reply_cb(reply)
            except Exception as e:
                log.warning("reply_cb 失敗: %s", e)

        # 発話(TTS)。再生中は speaking_changed で口パク・状態表示。
        self.tts.speak(
            reply,
            on_start=lambda: self.hooks.speaking_changed(True),
            on_end=lambda: self.hooks.speaking_changed(False),
        )

        # 低優先で記憶圧縮(肥大化対策)
        try:
            self.memory.maybe_compress(self.llm)
        except Exception as e:
            log.warning("記憶圧縮スキップ: %s", e)
