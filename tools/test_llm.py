#!/usr/bin/env python3
"""LMStudio(OpenAI互換)への疎通確認ツール。

  uv run --no-project --python 3.12 --with openai python tools/test_llm.py
  # Vision(画像入力)も試す:
  uv run --no-project --python 3.12 --with openai --with pillow python tools/test_llm.py --vision

config.yaml / settings.py の llm 設定を使う。モデルIDが分からない時はまず本ツールで
/v1/models を確認し、config.yaml の llm.model に合わせる。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aichan.llm.schema import parse_reply  # noqa: E402
from aichan.settings import AppConfig  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vision", action="store_true", help="画像入力もテスト")
    ap.add_argument("--message", default="はじめまして、すみれ。自己紹介して。")
    args = ap.parse_args()

    cfg = AppConfig.load().llm
    print(f"base_url = {cfg.base_url}")
    print(f"model    = {cfg.model}")

    try:
        from openai import OpenAI
    except ImportError:
        print("openai SDK が必要です: --with openai を付けて実行してください")
        return 1

    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.request_timeout)

    # 1) 利用可能モデル一覧
    print("\n--- /v1/models ---")
    try:
        models = client.models.list()
        ids = [m.id for m in models.data]
        for i in ids:
            print("  -", i)
        if cfg.model not in ids:
            print(f"\n⚠ config の model '{cfg.model}' は一覧に無い。"
                  f"上の正確なIDを config.yaml の llm.model に設定してください。")
    except Exception as e:
        print("モデル一覧取得失敗:", e)
        print("→ LMStudioのローカルサーバが起動しているか、base_url を確認。")
        return 1

    # 2) テキスト生成 + 構造化出力パース
    from aichan.llm import prompt
    msgs = prompt.build_messages(
        persona=AppConfig.load().character.persona,
        user_input=args.message, source=prompt.SRC_TEXT,
    )
    print("\n--- chat (text) ---")
    try:
        resp = client.chat.completions.create(
            model=cfg.model, messages=msgs,
            temperature=cfg.temperature, max_tokens=cfg.max_tokens,
        )
        raw = resp.choices[0].message.content or ""
        print("raw:", raw[:400])
        r = parse_reply(raw)
        print(f"\nパース結果: emotion={r.emotion} / speech={r.speech!r}")
        print(f"           speech_tts={r.speech_tts!r}")
    except Exception as e:
        print("生成失敗:", e)
        return 1

    # 3) Vision(任意)
    if args.vision:
        print("\n--- chat (vision) ---")
        img = _tiny_png()
        import base64
        uri = "data:image/png;base64," + base64.b64encode(img).decode()
        try:
            resp = client.chat.completions.create(
                model=cfg.model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "この画像に何色が見える?一言で。"},
                    {"type": "image_url", "image_url": {"url": uri}},
                ]}],
                max_tokens=64,
            )
            print("vision raw:", (resp.choices[0].message.content or "")[:200])
            print("→ 画像入力OK(このモデルはVision対応)")
        except Exception as e:
            print("画像入力でエラー:", e)
            print("→ このモデルはVision非対応かも。画面読み取り機能は使えない可能性。")

    print("\n✅ 疎通OK")
    return 0


def _tiny_png() -> bytes:
    from PIL import Image
    import io
    im = Image.new("RGB", (64, 64), (40, 160, 220))
    buf = io.BytesIO(); im.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
