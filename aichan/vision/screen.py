"""スクリーンショット取得 + 除外判定(docs/specification.md §6)。

mss でキャプチャ → 縮小 → PNGバイト列。アクティブウィンドウのタイトルが除外語に
マッチする場合はキャプチャしない(プライバシー)。
"""
from __future__ import annotations

import io
import logging

from ..settings import ScreenConfig

log = logging.getLogger(__name__)


class ScreenCapturer:
    def __init__(self, cfg: ScreenConfig) -> None:
        self.cfg = cfg

    def capture_png(self) -> bytes | None:
        """除外チェック後にPNGバイト列を返す。不可/除外なら None。"""
        if self._is_excluded():
            log.info("画面読み取り: 除外ウィンドウのためスキップ")
            return None
        try:
            import mss
            from PIL import Image
        except ImportError:
            log.warning("mss / Pillow 不在 → 画面読み取り無効")
            return None
        try:
            with mss.mss() as sct:
                idx = min(self.cfg.monitor, len(sct.monitors) - 1)
                shot = sct.grab(sct.monitors[idx])
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            if img.width > self.cfg.downscale_width:
                h = int(img.height * self.cfg.downscale_width / img.width)
                img = img.resize((self.cfg.downscale_width, h), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()
            if self.cfg.save_screenshots:
                _save_debug(data)
            return data
        except Exception as e:
            log.warning("画面キャプチャ失敗: %s", e)
            return None

    def _is_excluded(self) -> bool:
        title = _active_window_title()
        if not title:
            return False
        low = title.lower()
        return any(x.lower() in low for x in self.cfg.exclude_titles)


def _active_window_title() -> str:
    """アクティブウィンドウのタイトル(Windows)。取得不可なら空。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def _save_debug(data: bytes) -> None:
    import time
    from ..config import DATA_DIR
    out = DATA_DIR / "screens"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{int(time.time())}.png").write_bytes(data)
