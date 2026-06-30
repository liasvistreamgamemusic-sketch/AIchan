"""OpenAI互換 LLMクライアント(LMStudio / Gemma 3 12B, Vision兼用)。

openai SDK が無い / LMStudio に繋がらない場合は MockLLM にフォールバックして、
アプリ全体は動作し続ける(graceful degradation)。
"""
from __future__ import annotations

import base64
import logging

from ..settings import LLMConfig

log = logging.getLogger(__name__)

# OpenAI chat メッセージ型(緩く dict)
Message = dict


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    """テキスト/画像対応のチャットクライアント。"""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._client = None
        self._mock = False
        try:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.request_timeout
            )
        except ImportError:
            log.warning("openai SDK 未インストール → MockLLM で動作")
            self._mock = True

    # ---- 公開API ------------------------------------------------------
    def available(self) -> bool:
        return not self._mock and self._client is not None

    def chat(self, messages: list[Message], image_png: bytes | None = None) -> str:
        """1ターン生成。image_png があれば最後のユーザー発話に添付(Vision)。"""
        if self._mock or self._client is None:
            return _mock_reply(messages, image_png)

        msgs = list(messages)
        if image_png is not None:
            msgs = _attach_image(msgs, image_png)
        try:
            resp = self._client.chat.completions.create(
                model=self.cfg.model,
                messages=msgs,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # 接続不可・モデル無し等 → フォールバック
            log.warning("LLM呼び出し失敗(%s)→ MockLLM応答", e)
            return _mock_reply(messages, image_png)


def _attach_image(messages: list[Message], image_png: bytes) -> list[Message]:
    """最後の user メッセージへ image_url(base64 data URI)を付与。"""
    b64 = base64.b64encode(image_png).decode("ascii")
    data_uri = f"data:image/png;base64,{b64}"
    msgs = list(messages)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            text = msgs[i].get("content")
            if isinstance(text, str):
                msgs[i] = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            break
    return msgs


def _mock_reply(messages: list[Message], image_png: bytes | None) -> str:
    """LLM不在時のダミー応答(JSON形式)。開発・デモ用。"""
    import json
    import random

    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            last_user = m["content"]
            break

    if image_png is not None:
        speech = "画面、見てるよ。なにか作業してるんだね、楽しそう。"
        emotion = "smile"
    elif not last_user:
        speech = random.choice(
            ["ねえ、ちょっと休憩しない?", "今日はどんな一日だった?"]
        )
        emotion = "smile"
    else:
        speech = f"「{last_user[:20]}」のことだね。うん、わたしはちゃんと聞いてるよ。"
        emotion = random.choice(["smile", "happy", "thinking"])
    return json.dumps(
        {
            "speech": speech,
            "speech_tts": speech,
            "emotion": emotion,
            "emotion_intensity": 0.6,
            "tts": {"speed": 1.0},
            "actions": [],
            "memory_note": "",
        },
        ensure_ascii=False,
    )
