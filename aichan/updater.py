"""自動アップデート。GitHub Releases を確認し、新版の exe を取得して入れ替える。

- check(): 最新リリースを取得し、現在版より新しければ情報を返す。
- apply(): 凍結(.exe)時のみ。zip をDL→展開→更新スクリプトを起動して自分を入れ替え再起動。
依存は標準ライブラリのみ(urllib)。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from . import __version__
from .config import APP_DIR

log = logging.getLogger(__name__)

UA = {"User-Agent": "AIchan-updater"}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _parse_ver(tag: str) -> tuple:
    nums = []
    for part in tag.lstrip("vV").split("."):
        s = "".join(c for c in part if c.isdigit())
        nums.append(int(s) if s else 0)
    return tuple(nums) or (0,)


def is_newer(remote_tag: str, current: str = __version__) -> bool:
    return _parse_ver(remote_tag) > _parse_ver(current)


def check(repo: str) -> dict | None:
    """最新リリースを確認。新しければ {tag, notes, html_url, asset_url} を返す。"""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log.info("更新確認に失敗: %s", e)
        return None
    tag = data.get("tag_name", "")
    if not tag or not is_newer(tag):
        return None
    # Windows用の zip アセットを探す
    asset_url = ""
    for a in data.get("assets", []):
        name = a.get("name", "").lower()
        if name.endswith(".zip") and ("win" in name or "windows" in name or "x64" in name):
            asset_url = a.get("browser_download_url", "")
            break
    return {
        "tag": tag,
        "notes": data.get("body", "") or "",
        "html_url": data.get("html_url", ""),
        "asset_url": asset_url,
    }


def apply(asset_url: str) -> bool:
    """新版 zip をDL→展開→更新スクリプトを起動。成功なら呼び出し側はアプリを終了する。

    凍結(.exe)時のみ動作。インストール先(exeフォルダ)を丸ごと置き換える。
    """
    if not is_frozen():
        log.info("開発実行のため自動適用はスキップ(リリースページからどうぞ)")
        return False
    if not asset_url:
        return False
    try:
        staging = Path(tempfile.mkdtemp(prefix="aichan_update_"))
        zip_path = staging / "update.zip"
        log.info("更新をダウンロード: %s", asset_url)
        req = urllib.request.Request(asset_url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r, open(zip_path, "wb") as f:
            f.write(r.read())
        extract_dir = staging / "new"
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)
        # zip 直下に exe があればそこを、無ければ単一サブフォルダを採用
        src = extract_dir
        entries = [p for p in extract_dir.iterdir()]
        if not any(p.name.lower() == "aichan.exe" for p in entries) and len(entries) == 1 and entries[0].is_dir():
            src = entries[0]
        return _spawn_swapper(src, APP_DIR)
    except Exception as e:
        log.warning("更新の適用に失敗: %s", e)
        return False


def _spawn_swapper(src: Path, install: Path) -> bool:
    """アプリ終了を待ってファイルを入れ替え、再起動するバッチを起動。"""
    exe = install / "AIchan.exe"
    bat = Path(tempfile.gettempdir()) / "aichan_update.bat"
    script = f"""@echo off
chcp 65001 >nul
echo 更新を準備しています...
:waitloop
tasklist /fi "imagename eq AIchan.exe" 2>nul | find /i "AIchan.exe" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto waitloop
)
robocopy "{src}" "{install}" /E /IS /IT /NFL /NDL /NJH /NJS >nul
start "" "{exe}"
rmdir /s /q "{src.parent}" 2>nul
del "%~f0"
"""
    bat.write_text(script, encoding="utf-8")
    log.info("更新スクリプトを起動して再起動します")
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags)
    return True
