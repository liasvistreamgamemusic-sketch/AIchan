"""アプリ設定と永続化(P1: 表示まわりのみ)。

将来は pydantic-settings + config.yaml へ移行予定(docs/specification.md §13)。
P1 では軽量に dataclass + JSON で扱う。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

def _bundle_root() -> Path:
    """読み取り専用リソース(assets等)の基準。PyInstaller凍結時はバンドル先。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _app_dir() -> Path:
    """ユーザーが編集する config.yaml の場所。凍結時は exe と同じフォルダ。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


REPO_ROOT = _bundle_root()          # 後方互換の名前(= バンドル/開発ルート)
APP_DIR = _app_dir()
ASSETS_ROOT = REPO_ROOT / "assets" / "characters"   # 同梱の既定アセット(読み取り)


def _default_data_dir() -> Path:
    """書き込みデータ(DB・ウィンドウ状態)の保存先。

    リポジトリが WSL共有(\\wsl.localhost)上だと SQLite のロックが壊れるため、
    既定では OS のユーザーローカル領域に置く。AICHAN_DATA_DIR で上書き可能。
    """
    override = os.environ.get("AICHAN_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "AIchan"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path(os.path.expanduser("~")) / ".local" / "share"
    return base / "aichan"


DATA_DIR = _default_data_dir()
STATE_FILE = DATA_DIR / "window_state.json"

# 立ち絵の感情ラベル(docs/specification.md §5.2)。ファイル名 = ラベル + .png。
EMOTIONS: tuple[str, ...] = (
    "neutral", "happy", "smile", "excited", "laugh", "surprise",
    "sad", "worried", "angry", "pout", "shy", "sleepy", "thinking", "wink",
)
DEFAULT_EMOTION = "neutral"

# LLMが想定外の感情語を返したときのフォールバック対応表(§5.2)。
EMOTION_ALIASES: dict[str, str] = {
    "surprised": "surprise",
    "joy": "happy",
    "sadness": "sad",
    "anger": "angry",
    "embarrassed": "shy",
    "calm": "smile",
    "tired": "sleepy",
    "think": "thinking",
}


def resolve_emotion(name: str) -> str:
    """感情ラベルを正規化。未知ならエイリアス→neutral にフォールバック。"""
    key = (name or "").strip().lower()
    if key in EMOTIONS:
        return key
    return EMOTION_ALIASES.get(key, DEFAULT_EMOTION)


@dataclass
class WindowState:
    """永続化するウィンドウ状態。"""
    character_id: str = "sumire"
    emotion: str = DEFAULT_EMOTION
    # 足元アンカー(画面座標)。左上ではなく「下端中央」を保存することで、
    # 入力欄/吹き出しで高さが変わっても足元がズレない。
    anchor_cx: int | None = None
    anchor_bottom: int | None = None
    height_px: int = 460          # 立ち絵の表示高さ(幅は比率追従)
    click_through: bool = False
    movable: bool = False         # ドラッグ移動を許可するか(既定=ロック)
    show_subtitle: bool = True
    # 初期配置(未ドラッグ時)。画面下に密着させるマスコット配置。
    bottom_margin: int = 0        # 画面下端(タスクバー上)からの余白。0で密着
    side_margin: int = 24         # 画面右端からの余白

    @classmethod
    def load(cls) -> "WindowState":
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                known = {k: data[k] for k in asdict(cls()).keys() if k in data}
                return cls(**known)
            except (json.JSONDecodeError, TypeError, OSError):
                pass
        return cls()

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )


SRC_CHARACTER_ROOT = REPO_ROOT / "character"   # 立ち絵原本(green screen)


def character_dir(character_id: str) -> Path:
    """同梱の既定アセット(読み取り)。"""
    return ASSETS_ROOT / character_id


def user_character_dir(character_id: str) -> Path:
    """ユーザー編集分(ペルソナ・立ち絵差し替え)の書き込み先。凍結exeでも書ける。"""
    return DATA_DIR / "characters" / character_id


def list_characters() -> list[str]:
    """同梱 + ユーザー追加 のキャラID一覧。"""
    ids = set()
    for root in (ASSETS_ROOT, DATA_DIR / "characters"):
        if root.is_dir():
            ids.update(d.name for d in root.iterdir() if d.is_dir())
    return sorted(ids)


# ---- ペルソナ(ユーザー編集=appdata 優先 / 既定=同梱 assets) ----------
def persona_path(character_id: str) -> Path:
    """保存先(ユーザー編集分)。"""
    return user_character_dir(character_id) / "persona.md"


def load_persona(character_id: str) -> str | None:
    """ユーザー編集(appdata)→ 同梱 assets の順で読む。"""
    for p in (persona_path(character_id), character_dir(character_id) / "persona.md"):
        if p.exists():
            text = p.read_text(encoding="utf-8").strip()
            if text:
                return text
    return None


def save_persona(character_id: str, text: str) -> None:
    p = persona_path(character_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


# ---- 感情→立ち絵 の差し替えマップ(任意) ---------------------------
def emotion_overrides_path(character_id: str) -> Path:
    return user_character_dir(character_id) / "emotions.json"


def load_emotion_overrides(character_id: str) -> dict[str, str]:
    """{emotion: filename or path}。ユーザー編集→同梱 の順で最初に見つかった方。"""
    for p in (emotion_overrides_path(character_id),
              character_dir(character_id) / "emotions.json"):
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def save_emotion_overrides(character_id: str, mapping: dict[str, str]) -> None:
    p = emotion_overrides_path(character_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")


def emotion_path(character_id: str, emotion: str) -> Path:
    """感情に対応する透過PNGのパス(差し替えマップ + フォールバック適用済み)。"""
    emo = resolve_emotion(emotion)
    overrides = load_emotion_overrides(character_id)
    if emo in overrides:
        ov = Path(overrides[emo])
        if ov.is_absolute():
            return ov
        # 相対指定: ユーザー編集ディレクトリ → 同梱 の順で探す
        for base in (user_character_dir(character_id), character_dir(character_id)):
            if (base / ov).exists():
                return base / ov
        return character_dir(character_id) / ov
    # 既定: ユーザーが appdata に置いた同名pngを優先、無ければ同梱
    user_png = user_character_dir(character_id) / f"{emo}.png"
    return user_png if user_png.exists() else character_dir(character_id) / f"{emo}.png"


def available_emotions(character_id: str) -> list[str]:
    """実際に表示可能な感情(既定ファイル or 差し替え)を順序どおり返す。"""
    overrides = load_emotion_overrides(character_id)
    cdir = character_dir(character_id)
    out = []
    for e in EMOTIONS:
        if e in overrides or (cdir / f"{e}.png").exists():
            out.append(e)
    return out
