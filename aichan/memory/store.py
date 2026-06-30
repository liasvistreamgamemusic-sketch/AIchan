"""記憶の高レベルAPI(プロンプト用コンテキスト構築 + 圧縮の起動)。

RAG(関連記憶検索)は軽量なキーワード重なりスコアを既定とし、依存を増やさない。
将来 sqlite-vec / 埋め込みに差し替え可能なように retrieve() を分離。
"""
from __future__ import annotations

import logging
import re

from ..settings import CharacterConfig, MemoryConfig
from . import summarize
from .db import MemoryDB

log = logging.getLogger(__name__)


class Memory:
    def __init__(self, db: MemoryDB, mem_cfg: MemoryConfig, char_cfg: CharacterConfig):
        self.db = db
        self.cfg = mem_cfg
        self.char = char_cfg
        self._ensure_persona()

    def _ensure_persona(self) -> None:
        if self.db.get_persona(self.char.id) is None:
            self.db.set_persona(self.char.id, self._resolve_persona())

    def _resolve_persona(self) -> str:
        # 優先順位: キャラ別ファイル(character/<id>/persona.txt)→ 設定の既定。
        from .. import config
        return config.load_persona(self.char.id) or self.char.persona

    @property
    def persona(self) -> str:
        # ファイルがあれば常にそれを最優先(編集が即反映され、キャラごとに管理しやすい)。
        from .. import config
        return config.load_persona(self.char.id) or \
            self.db.get_persona(self.char.id) or self.char.persona

    # ---- 記録 ---------------------------------------------------------
    def record_user(self, text: str, source: str = "text") -> None:
        self.db.add_message("user", text, source=source)

    def record_assistant(self, reply, source: str = "text") -> None:
        self.db.add_message(
            "assistant", reply.speech, source=source, emotion=reply.emotion,
            meta={"speech_tts": reply.speech_tts, "actions": reply.actions},
        )
        note = getattr(reply, "memory_note", "")
        if note:
            self._maybe_store_note(note)

    def _maybe_store_note(self, note: str) -> None:
        # memory_note は salience 高めの level0 サマリとして残す(要約に埋もれさせない)
        self.db.add_summary(note, level=0, salience=0.8, topic="note")

    # ---- プロンプト用コンテキスト ------------------------------------
    def context(self, user_input: str, source: str) -> dict:
        recent = self.db.recent_messages(self.cfg.short_window_turns)
        recent_turns = [(m.role, m.text) for m in recent]
        return {
            "persona": self.persona,
            "long_term_summary": self._long_term_summary(),
            "related_memories": self.retrieve(user_input),
            "user_profile": self.db.get_profile(),
            "recent_turns": recent_turns,
        }

    def _long_term_summary(self) -> str:
        # 上位レベルの要約を優先して数件。
        parts: list[str] = []
        for lvl in (2, 1):
            for r in self.db.summaries(level=lvl, limit=3):
                parts.append(r["summary"])
        return "\n".join(parts)

    def retrieve(self, query: str) -> list[str]:
        """関連記憶 top-k(キーワード重なりスコア)。"""
        if not query.strip():
            return []
        q_tokens = _tokens(query)
        if not q_tokens:
            return []
        scored: list[tuple[float, str]] = []
        for r in self.db.summaries(level=0, limit=200):
            text = r["summary"]
            overlap = len(q_tokens & _tokens(text))
            if overlap:
                score = overlap * (0.5 + r["salience"])
                scored.append((score, text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[: self.cfg.rag_top_k]]

    # ---- 圧縮 ---------------------------------------------------------
    def maybe_compress(self, llm) -> int:
        """未要約の(直近を除く)メッセージが閾値を超えていれば圧縮。"""
        pending = self.db.unsummarized_messages(before_recent=self.cfg.short_window_turns)
        if len(pending) < self.cfg.summarize_after_turns:
            return 0
        return self.compress_now(llm)

    def compress_now(self, llm) -> int:
        return summarize.compress(
            self.db, llm, keep_recent=self.cfg.short_window_turns
        )


def _tokens(text: str) -> set[str]:
    # 日本語も拾えるよう: 英数字語 + 2gram(かな・漢字)
    text = text.lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    jp = re.findall(r"[ぁ-んァ-ヶ一-龠]", text)
    words |= {"".join(pair) for pair in zip(jp, jp[1:])}
    return {w for w in words if len(w) >= 2}
