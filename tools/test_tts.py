#!/usr/bin/env python3
"""Irodori-TTS-Server への疎通 + 再生の診断ツール。

  uv run --no-project --python 3.12 --with requests --with sounddevice \
      --with soundfile python tools/test_tts.py
  # 声を指定:
  ... python tools/test_tts.py --voice sumire --text "こんにちは、すみれです"

config.yaml / settings.py の tts 設定を使う。/health・声一覧・合成・再生を順に試す。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aichan.settings import AppConfig  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default=None)
    ap.add_argument("--text", default="こんにちは。すみれです。聞こえていますか?")
    args = ap.parse_args()

    cfg = AppConfig.load().tts
    if args.voice:
        cfg.voice = args.voice
    base = cfg.base_url.rstrip("/")
    health = base.rsplit("/v1", 1)[0] + "/health"
    print(f"base_url = {cfg.base_url}")
    print(f"voice    = {cfg.voice}")

    try:
        import requests
    except ImportError:
        print("✗ requests 未導入 → 起動コマンドに --with requests を追加してください")
        return 1

    # 1) health
    print("\n--- /health ---")
    try:
        r = requests.get(health, timeout=3)
        print("status:", r.status_code, r.text[:120])
    except Exception as e:
        print("✗ サーバに繋がりません:", e)
        print("→ Irodori-TTS-Server を起動してください(別プロセス・ROCm):")
        print("   uv run python -m irodori_openai_tts --host 0.0.0.0 --port 8088")
        return 1

    # 2) 声一覧
    print("\n--- /v1/audio/voices ---")
    try:
        r = requests.get(base + "/audio/voices", timeout=5)
        print(r.status_code, r.text[:300])
        if cfg.voice not in r.text:
            print(f"⚠ voice '{cfg.voice}' が一覧に無いかも。"
                  " /v1/audio/voices に参照音声を登録するか、設定の声を一覧の名前に。")
    except Exception as e:
        print("声一覧の取得に失敗:", e)

    # 3) 合成
    print("\n--- /v1/audio/speech 合成 ---")
    payload = {"model": cfg.model, "voice": cfg.voice, "input": args.text,
               "response_format": cfg.response_format, "speed": cfg.speed}
    try:
        r = requests.post(base + "/audio/speech", json=payload,
                          headers={"Authorization": f"Bearer {cfg.api_key}"}, timeout=60)
        if not r.ok:
            print("✗ 合成失敗 HTTP", r.status_code, r.text[:300])
            return 1
        audio = r.content
        print(f"✓ 合成OK: {len(audio)} bytes ({cfg.response_format})")
    except Exception as e:
        print("✗ 合成リクエスト失敗:", e)
        return 1

    # 4) 再生
    print("\n--- 再生 ---")
    try:
        import io
        import sounddevice as sd
        import soundfile as sf
        data, sr = sf.read(io.BytesIO(audio), dtype="float32")
        sd.play(data, sr); sd.wait()
        print("✓ 再生しました")
    except Exception as e:
        print("再生スキップ/失敗:", e)
        print("→ --with sounddevice --with soundfile が必要。WSLでは音声デバイスが無い場合あり")
        out = Path("tts_test_out." + cfg.response_format)
        out.write_bytes(audio)
        print(f"  音声を {out} に保存したので手動再生で確認できます")

    print("\n✅ 完了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
