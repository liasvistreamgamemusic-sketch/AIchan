#!/usr/bin/env python3
"""green screen の立ち絵素材を背景除去して透過PNGに変換するバッチツール。

入力: character/{id}/*.png   (nano banana 出力。単色グリーン背景, RGB)
出力: assets/characters/{id}/*.png (RGBA 透過)

手法はクロマキー(緑との距離でアルファを生成)。背景が均一グリーンのため、
u2net+alpha matting よりハロー/フリンジが出ず綺麗に抜ける。緑かぶり(spill)も
despill で除去する。原本(character/)は再処理のため残す。

使い方:
    uv run --python 3.12 --with pillow --with numpy \
        python tools/remove_bg.py --id sumire
    # 1枚だけ確認:
    uv run ... python tools/remove_bg.py --id sumire --only neutral
調整:
    --low / --high  … greenness(= G - max(R,B))のアルファ閾値。
                      low以下=完全不透明 / high以上=完全透明 / 間=なめらか。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent


def chroma_key(img: Image.Image, low: float, high: float) -> Image.Image:
    """緑スクリーンを抜いて RGBA を返す。

    greenness = G - max(R, B)。緑背景では大きな正の値、前景(肌・白服・紺髪・
    青目)ではほぼ0以下になる。これでアルファを作り、境界はなめらかに、
    緑かぶりは despill(G を max(R,B) まで引き下げ)で除去する。
    """
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx_rb = np.maximum(r, b)
    greenness = g - mx_rb

    # アルファ: greenness<=low -> 1.0(不透明), >=high -> 0.0(透明)
    alpha = np.clip((high - greenness) / max(high - low, 1e-6), 0.0, 1.0)

    # despill: 前景側に残る緑かぶりを抑える(G を max(R,B) までクランプ)
    g2 = np.minimum(g, mx_rb)
    out = np.stack([r, g2, b, alpha * 255.0], axis=-1)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def crop_to_alpha(img: Image.Image, pad: int = 8) -> Image.Image:
    """完全透明な余白をトリミング(任意・表示の取り回し用)。"""
    a = np.asarray(img)[..., 3]
    ys, xs = np.where(a > 8)
    if len(xs) == 0:
        return img
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, img.width)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, img.height)
    return img.crop((x0, y0, x1, y1))


def process(src: Path, dst: Path, low: float, high: float, do_crop: bool) -> None:
    cut = chroma_key(Image.open(src), low, high)
    if do_crop:
        cut = crop_to_alpha(cut)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cut.save(dst)
    a = np.asarray(cut)[..., 3]
    opaque = (a > 16).mean() * 100
    print(f"  {src.name:14s} -> {dst.relative_to(REPO)}  ({cut.width}x{cut.height}, 前景 {opaque:4.1f}%)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="sumire", help="character id (character/<id>/)")
    ap.add_argument("--only", default=None, help="この感情1枚だけ処理 (例: neutral)")
    ap.add_argument("--low", type=float, default=40.0, help="greenness アルファ閾値(下)")
    ap.add_argument("--high", type=float, default=120.0, help="greenness アルファ閾値(上)")
    ap.add_argument("--crop", action="store_true", help="透明余白をトリミング")
    args = ap.parse_args()

    src_dir = REPO / "character" / args.id
    dst_dir = REPO / "assets" / "characters" / args.id
    if not src_dir.is_dir():
        raise SystemExit(f"見つかりません: {src_dir}")

    files = sorted(src_dir.glob("*.png"))
    if args.only:
        files = [f for f in files if f.stem == args.only]
        if not files:
            raise SystemExit(f"{args.only}.png が {src_dir} にありません")

    print(f"chroma key  low={args.low} high={args.high}  {len(files)}枚")
    for f in files:
        process(f, dst_dir / f.name, args.low, args.high, args.crop)
    print(f"完了 -> {dst_dir.relative_to(REPO)}")


if __name__ == "__main__":
    main()
