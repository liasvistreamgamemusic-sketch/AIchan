"""PyInstaller 用エントリポイント。

aichan/main.py を直接エントリにすると __main__ 実行になり相対importが壊れるため、
パッケージとして絶対importするこのランチャーを exe のエントリにする。
"""
import os
import sys

# 非凍結(素の python 実行)時はリポジトリ直下を import パスに追加。
# 凍結(exe)時は PyInstaller が aichan を同梱するので不要。
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aichan.main import main

if __name__ == "__main__":
    raise SystemExit(main())
