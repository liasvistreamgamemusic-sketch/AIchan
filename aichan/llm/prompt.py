"""プロンプト構築(docs/specification.md §7.2)。

レイヤー: システム/ペルソナ → 長期記憶サマリ → 関連記憶(RAG) → ユーザープロファイル
→ 直近会話 → 現在の入力 → 出力フォーマット指示。
"""
from __future__ import annotations

from .schema import OUTPUT_FORMAT_INSTRUCTION

# 入力の種別(どこから来たか)。
SRC_TEXT = "text"
SRC_VOICE = "voice"
SRC_SCREEN = "screen"
SRC_PROACTIVE = "proactive"
SRC_DISCORD = "discord"


def build_messages(
    *,
    persona: str,
    long_term_summary: str = "",
    related_memories: list[str] | None = None,
    user_profile: dict[str, str] | None = None,
    recent_turns: list[tuple[str, str]] | None = None,
    user_input: str = "",
    source: str = SRC_TEXT,
    user_address: str = "",
) -> list[dict]:
    """OpenAI chat messages を組み立てる。

    recent_turns: [(role, text), ...] role は "user" | "assistant"。
    user_address: ユーザーの呼び方(例「鏡花さん」)。指定時は必ずこれで呼ぶ。
    """
    system_parts = [persona.strip()]

    if user_address.strip():
        system_parts.append(
            f"ユーザーのことは必ず「{user_address}」と呼んでください。"
            "他の呼び方(あなた・きみ等)は使わないこと。"
        )

    if long_term_summary.strip():
        system_parts.append("【これまでの記憶の要約】\n" + long_term_summary.strip())

    if related_memories:
        joined = "\n".join(f"- {m}" for m in related_memories)
        system_parts.append("【関連する過去の記憶】\n" + joined)

    if user_profile:
        prof = "\n".join(f"- {k}: {v}" for k, v in user_profile.items())
        system_parts.append("【ユーザー情報】\n" + prof)

    # 入力種別ごとの振る舞い指示
    system_parts.append(_source_directive(source))
    system_parts.append(OUTPUT_FORMAT_INSTRUCTION)

    messages: list[dict] = [{"role": "system", "content": "\n\n".join(system_parts)}]

    for role, text in (recent_turns or []):
        if role in ("user", "assistant") and text:
            messages.append({"role": role, "content": text})

    messages.append({"role": "user", "content": _user_content(user_input, source)})
    return messages


def _source_directive(source: str) -> str:
    if source == SRC_SCREEN:
        return (
            "今からユーザーのPC画面の画像が渡されます。画面の内容を見て、"
            "親しみを込めて短く一言コメントしてください(詮索しすぎない)。"
        )
    if source == SRC_PROACTIVE:
        return (
            "あなたから自発的に話しかけます。重くならない自然な一言を、"
            "状況や記憶を踏まえて選んでください。"
        )
    if source == SRC_VOICE:
        return "ユーザーが音声で話しかけてきました。自然に会話で応じてください。"
    return "ユーザーと自然に会話してください。"


def _user_content(user_input: str, source: str) -> str:
    if source == SRC_SCREEN:
        return user_input or "(画面を見て一言コメントして)"
    if source == SRC_PROACTIVE:
        return user_input or "(自発的に話しかけて)"
    return user_input
