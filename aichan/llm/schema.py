"""LLM構造化出力(セリフ + 感情 + TTSパラメータ)の定義とパーサ。

docs/specification.md §7.3。小型ローカルモデルでJSONが崩れる前提で、緩く抽出し
フォールバックする。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..config import resolve_emotion


@dataclass
class TTSParams:
    speed: float = 1.0
    cfg_scale_text: float | None = None
    cfg_scale_speaker: float | None = None


@dataclass
class Reply:
    """LLMの1応答。"""
    speech: str                       # 字幕用(絵文字なし)
    speech_tts: str                   # TTS用(感情絵文字入り)
    emotion: str = "neutral"          # 立ち絵ラベル(正規化済み)
    emotion_intensity: float = 0.6
    tts: TTSParams = field(default_factory=TTSParams)
    actions: list[str] = field(default_factory=list)
    memory_note: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.speech.strip()


# 出力フォーマットの指示(システムプロンプトに添付)。
# 絵文字は speech_tts(Irodori-TTSの感情制御用)にのみ使う。字幕用 speech は絵文字なし。
OUTPUT_FORMAT_INSTRUCTION = """
あなたは必ず次のJSON1つだけを返してください(前後に文章を付けない):
{
  "speech": "字幕用の発話テキスト。絵文字や顔文字は使わない。",
  "speech_tts": "音声合成用。speechと同じ内容に、感情を表す絵文字を文中へ少量だけ挿入する(例: 😊 嬉しい / 😢 悲しい / 😮 驚き / 😳 照れ)。これはTTSの感情制御用。",
  "emotion": "neutral|happy|smile|excited|laugh|surprise|sad|worried|angry|pout|shy|sleepy|thinking|wink のいずれか",
  "emotion_intensity": 0.0〜1.0,
  "tts": {"speed": 0.8〜1.3},
  "actions": [],
  "memory_note": "記憶に残すべき要点があれば一言。無ければ空文字。"
}
""".strip()


def _extract_json(text: str) -> dict[str, Any] | None:
    """テキストから最初の妥当なJSONオブジェクトを取り出す。"""
    # ```json ... ``` コードフェンス対応
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))
    # 最初の { から最後の } までを貪欲に
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _recover_fields(text: str) -> dict | None:
    """途中で切れたJSONから speech / speech_tts / emotion を正規表現で拾う。"""
    def grab(key: str) -> str | None:
        m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            try:
                return json.loads('"' + m.group(1) + '"')
            except json.JSONDecodeError:
                return m.group(1)
        return None

    speech = grab("speech")
    speech_tts = grab("speech_tts")
    emotion = grab("emotion")
    if speech is None and speech_tts is None:
        return None
    return {
        "speech": speech or _strip_emojis(speech_tts or ""),
        "speech_tts": speech_tts or speech or "",
        "emotion": emotion or "neutral",
    }


def parse_reply(raw: str) -> Reply:
    """LLM生出力を Reply に変換。失敗時は本文のみ・neutral でフォールバック。"""
    raw = (raw or "").strip()
    obj = _extract_json(raw)
    if obj is None:
        # JSONが壊れている(途中で切れた等)→ フィールドを正規表現で救出。
        recovered = _recover_fields(raw)
        if recovered is not None:
            obj = recovered
        else:
            # それも無理なら全文をセリフ扱い(speech_tts は絵文字を残してTTSへ)
            return Reply(speech=_strip_emojis(raw) or "…", speech_tts=raw or "…")

    # 字幕 speech は絵文字なし。speech_tts は絵文字を残す(Irodoriの感情制御)。
    raw_speech = str(obj.get("speech") or "").strip()
    speech_tts = str(obj.get("speech_tts") or raw_speech).strip()
    speech = _strip_emojis(raw_speech) or _strip_emojis(speech_tts)
    tts_obj = obj.get("tts") or {}
    tts = TTSParams(
        speed=_as_float(tts_obj.get("speed"), 1.0),
        cfg_scale_text=_opt_float(tts_obj.get("cfg_scale_text")),
        cfg_scale_speaker=_opt_float(tts_obj.get("cfg_scale_speaker")),
    )
    actions = obj.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    return Reply(
        speech=speech or "…",
        speech_tts=speech_tts or speech or "…",
        emotion=resolve_emotion(str(obj.get("emotion") or "neutral")),
        emotion_intensity=_as_float(obj.get("emotion_intensity"), 0.6),
        tts=tts,
        actions=[str(a) for a in actions],
        memory_note=str(obj.get("memory_note") or "").strip(),
    )


_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F000-\U0001F02F"
    "\U0000FE00-\U0000FE0F" "\U00002190-\U000021FF" "]",
    flags=re.UNICODE,
)


def _strip_emojis(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
