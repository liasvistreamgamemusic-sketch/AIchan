"""アプリ全体設定(config.yaml 読み込み)。

docs/specification.md §13 の設定項目。サブシステムごとに入れ子の dataclass。
config.yaml が無ければ既定値で動く。pyyaml が無ければ既定値のみ。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from .config import DATA_DIR, REPO_ROOT

CONFIG_FILE = REPO_ROOT / "config.yaml"
# pyyaml が無い環境でも設定を失わないための JSON フォールバック(ユーザーローカル)。
CONFIG_JSON_FALLBACK = DATA_DIR / "config.json"


@dataclass
class LLMConfig:
    base_url: str = "http://192.168.0.86:1234/v1"   # LMStudio OpenAI互換
    api_key: str = "lm-studio"                    # ダミーで可
    #model: str = "google/gemma-4-12b-qat"         # Vision兼用(正確なIDは /v1/models で確認)
    model: str = "google/gemma-4-e4b"        
    temperature: float = 0.8
    max_tokens: int = 1024            # 短いと回答途中で切れる(JSON込みで余裕を持たせる)
    request_timeout: float = 120.0
    autostart: bool = False           # LMStudioサーバをアプリ起動時に自動起動するか
    server_cmd: list[str] = field(default_factory=list)  # 例: ["lms","server","start"]


@dataclass
class TTSConfig:
    enabled: bool = True
    base_url: str = "http://127.0.0.1:8088/v1"    # Irodori-TTS-Server
    api_key: str = "irodori"
    model: str = "irodori-tts"
    voice: str = "sumire"                          # 登録ボイスID
    speed: float = 1.0
    cfg_scale_text: float = 1.0
    cfg_scale_speaker: float = 1.0
    response_format: str = "wav"
    autostart_server: bool = False                 # subprocessで自動起動するか
    server_cmd: list[str] = field(default_factory=list)  # 起動コマンド
    backend: str = "irodori"                       # irodori | aivis


@dataclass
class STTConfig:
    enabled: bool = True
    backend: str = "faster-whisper"                # faster-whisper | whispercpp
    model: str = "small"
    device: str = "auto"                           # auto | cuda | cpu | vulkan
    language: str = "ja"
    mode: str = "ptt"                              # ptt(押下中) | vad(常時)
    samplerate: int = 16000
    vad_aggressiveness: int = 2


@dataclass
class ScreenConfig:
    enabled: bool = False                          # プライバシー: 既定オフ
    interval_min_sec: int = 300
    interval_max_sec: int = 900
    monitor: int = 1                               # mss のモニタ番号(1=主)
    downscale_width: int = 1024
    save_screenshots: bool = False
    exclude_titles: list[str] = field(default_factory=lambda: [
        "パスワード", "password", "bank", "銀行", "private",
    ])


@dataclass
class ProactiveConfig:
    enabled: bool = True
    interval_min_sec: int = 600
    interval_max_sec: int = 1800
    quiet_start_hour: int = 23                     # 静音時間帯(夜)
    quiet_end_hour: int = 8
    cooldown_sec: int = 180


@dataclass
class MemoryConfig:
    short_window_turns: int = 12                   # 生で投入する直近ターン数
    rag_top_k: int = 4
    summarize_after_turns: int = 40                # 圧縮トリガ
    compress_interval_sec: int = 3600


@dataclass
class DiscordConfig:
    enabled: bool = False
    token: str = ""
    channel_ids: list[int] = field(default_factory=list)


@dataclass
class UserConfig:
    """ユーザー(あなた)の呼ばれ方。TTSは読み(かな)で発音矯正する。"""
    name: str = ""            # 表示名(漢字など)
    name_reading: str = ""    # 読み(かな)。TTSの発音矯正に使用。空なら name をそのまま
    honorific: str = "さん"   # さん/ちゃん/くん/様/(空=呼び捨て)

    @property
    def call_display(self) -> str:
        """字幕・プロンプト用の呼び方(表示名 + 敬称)。"""
        return (self.name + self.honorific) if self.name else ""

    @property
    def call_spoken(self) -> str:
        """TTS用の呼び方(読み + 敬称)。"""
        base = self.name_reading or self.name
        return (base + self.honorific) if base else ""


@dataclass
class ThemeConfig:
    """吹き出し・状態表示のテーマカラー。"""
    bubble_bg: str = "#fff2f8"
    bubble_bg2: str = "#ffffff"        # グラデ上側
    bubble_border: str = "#f6a8cb"
    bubble_text: str = "#3a3340"
    name_color: str = "#e36fa0"
    status_bg: str = "#7a6e96"
    status_text: str = "#ffffff"
    accent: str = "#e36fa0"            # マイク等のアクセント


@dataclass
class CharacterConfig:
    id: str = "sumire"
    name: str = "すみれ"
    persona: str = (
        "あなたは「すみれ」という名前の、優しくて少し恥ずかしがり屋な女の子のAIです。"
        "ユーザーのデスクトップに常駐し、親しみやすく寄り添う相棒として振る舞います。"
        "一人称は「わたし」。語尾はやわらかく、絵文字は控えめ。"
        "相手を気遣い、短めに自然な口調で話します。"
    )


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    character: CharacterConfig = field(default_factory=CharacterConfig)
    user: UserConfig = field(default_factory=UserConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or CONFIG_FILE
        data: dict[str, Any] = {}
        loaded = False
        if path.exists():
            try:
                import yaml  # 任意依存
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                loaded = True
            except ImportError:
                pass            # pyyaml 不在 → JSONフォールバックへ
            except Exception:
                loaded = True    # ファイルはあるが壊れている: 既定で続行
        if not loaded and CONFIG_JSON_FALLBACK.exists():
            try:
                data = json.loads(CONFIG_JSON_FALLBACK.read_text(encoding="utf-8")) or {}
            except (json.JSONDecodeError, OSError):
                pass
        return _from_dict(cls, data)

    def to_yaml_dict(self) -> dict[str, Any]:
        """設定ファイル用の dict。persona はファイル管理なので除外する。"""
        from dataclasses import asdict
        d = asdict(self)
        d.get("character", {}).pop("persona", None)
        return d

    def save(self, path: Path | None = None) -> bool:
        """設定を保存。pyyaml があれば config.yaml、無ければ JSON フォールバック。

        どちらかに必ず保存するので、設定が失われることはない。常に True。
        """
        path = path or CONFIG_FILE
        d = self.to_yaml_dict()
        try:
            import yaml
            path.write_text(
                yaml.safe_dump(d, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except ImportError:
            CONFIG_JSON_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_JSON_FALLBACK.write_text(
                json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return True


def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    """ネストした dataclass に dict を流し込む(未知キーは無視)。"""
    from typing import get_type_hints

    hints = get_type_hints(cls)  # __future__ annotations の文字列型を解決
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        val = data[f.name]
        ftype = hints.get(f.name, f.type)
        if is_dataclass(ftype) and isinstance(val, dict):
            kwargs[f.name] = _from_dict(ftype, val)
        else:
            kwargs[f.name] = val
    return cls(**kwargs)
