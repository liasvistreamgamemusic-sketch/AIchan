"""記憶の階層的圧縮(docs/specification.md §8.3)。

会話の生ログをLLMで「三人称の事実記録」に要約する。キャラの口調は混ぜない
(キャラ崩壊防止 §8.3.1)。さらに下位要約を上位要約へ畳み込む。
"""
from __future__ import annotations

import logging
import time

from .db import MemoryDB, MessageRow

log = logging.getLogger(__name__)

# 要約はキャラの語り口を入れず、事実のみ。ペルソナは触らない。
_SUMMARY_SYSTEM = (
    "あなたは会話ログを圧縮する要約器です。以下の会話を、後で思い出すための"
    "『三人称・事実ベースの短いメモ』に要約してください。"
    "キャラクターの口調や演出は入れず、ユーザーに関する事実・出来事・好み・約束を"
    "簡潔な箇条書きで残します。重要度の低い雑談は省いて構いません。要約のみ出力。"
)
_ROLLUP_SYSTEM = (
    "次の複数の要約メモを、重複を除いて1つの短い要約に統合してください。"
    "事実・好み・約束を優先して残し、三人称・箇条書きで。要約のみ出力。"
)


def summarize_messages(llm, messages: list[MessageRow]) -> str:
    """生メッセージ群 → 事実要約テキスト。"""
    if not messages:
        return ""
    convo = "\n".join(f"{m.role}: {m.text}" for m in messages)
    out = llm.chat([
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user", "content": convo},
    ])
    return _clean(out)


def rollup_summaries(llm, summaries: list[str]) -> str:
    if not summaries:
        return ""
    joined = "\n\n".join(summaries)
    out = llm.chat([
        {"role": "system", "content": _ROLLUP_SYSTEM},
        {"role": "user", "content": joined},
    ])
    return _clean(out)


def compress(db: MemoryDB, llm, *, keep_recent: int, level1_threshold: int = 8) -> int:
    """圧縮を1回実行。要約した件数を返す。

    1) 直近 keep_recent を除く未要約メッセージを塊で要約 → level0 サマリ。
    2) level0 サマリが溜まったら level1 へ畳み込み(階層化)。
    """
    msgs = db.unsummarized_messages(before_recent=keep_recent)
    n = 0
    if msgs:
        text = summarize_messages(llm, msgs)
        if text:
            db.add_summary(
                text, level=0,
                period_start=msgs[0].ts, period_end=msgs[-1].ts,
                salience=0.5,
            )
            db.mark_summarized([m.id for m in msgs])
            n = len(msgs)
            log.info("compressed %d messages into a level0 summary", n)

    # 階層化: level0 が多すぎたら統合
    lvl0 = db.summaries(level=0, limit=100)
    if len(lvl0) >= level1_threshold:
        texts = [r["summary"] for r in reversed(lvl0)]
        merged = rollup_summaries(llm, texts)
        if merged:
            db.add_summary(merged, level=1, salience=0.6)
            db.delete_summaries([r["id"] for r in lvl0])
            log.info("rolled up %d level0 summaries into level1", len(lvl0))
    return n


def _clean(text: str) -> str:
    return (text or "").strip()
