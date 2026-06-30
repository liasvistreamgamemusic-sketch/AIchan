# AIちゃん — デスクトップAIキャラクターコンパニオン

デスクトップに常駐する小さなキャラ(すみれ)。喋り、画面を見てコメントし、声を聞き取り、会話を記憶するローカル動作のAIコンパニオン。

- 仕様: [docs/specification.md](docs/specification.md)
- 立ち絵生成プロンプト: [docs/character-image-prompts.md](docs/character-image-prompts.md)

## 構成(技術)
- GUI: Python + PySide6(透過・最前面の常駐ウィンドウ)
- LLM: LMStudio(OpenAI互換) / Gemma 3 12B(Vision兼用) — *P2以降*
- TTS: Irodori-TTS v3(OpenAI互換サーバ, ROCm) — *P3以降*
- STT: whisper.cpp(Vulkan) — *P3以降*
- 記憶: SQLite + 階層的要約圧縮 — *P6以降*

## 実装状況
全フェーズ(P1〜P8)を実装済み。各サブシステムは**依存やローカルサービスが無くても
graceful に無効化**され、最低限「立ち絵表示 + テキスト会話(LLM不在ならモック応答)」は
常に動く。LMStudio / Irodori-TTS / Whisper を用意すると本機能が有効化される。

- 透過・最前面・ドラッグ・画面下密着のキャラ表示、14表情、字幕、口パク、トレイ
- テキスト/音声(Whisper)入力 → LLM(Gemma/LMStudio, Vision兼用)→ 構造化出力
  (セリフ + 感情 + 感情絵文字)→ 立ち絵差し替え + TTS(Irodori)発話
- 画面読み取りコメント、自発発話(スケジューラ)、記憶(SQLite)+ 階層的圧縮、Discord連携

### セットアップ & 起動
```bash
# 1) 立ち絵の背景除去(初回のみ。character/ の green screen → assets/ の透過PNG)
uv run --no-project --python 3.12 --with pillow --with numpy python tools/remove_bg.py --id sumire

# 2) 設定(任意): config.yaml.example をコピーして編集
cp config.yaml.example config.yaml

# 3a) 最小起動(表示 + テキスト会話のみ。WSL共有からでも可)
uv run --no-project --python 3.12 --with PySide6 python -m aichan.main

# 3b) フル機能(Windowsローカルにコピーして実行を推奨)
uv run --python 3.12 --extra full --with PySide6 python -m aichan.main
```

> Windowsローカル(例 `C:\dev\AIchan`)で `uv sync --extra full` 済みなら
> `uv run python -m aichan.main` だけで起動できる。

### 操作
- ドラッグ: 移動(足元位置を記憶)
- **ホバー**: キャラに乗せると入力欄+マイクが体の内側に表示(離すと隠れる)
- マイク**長押し**で音声入力。入力欄に打って Enter でも会話
- **右クリック → 「設定…」**: キャラ/ペルソナ・感情の立ち絵・テーマカラー・機能オンオフ・接続/ボットを GUI で設定
- 右クリック / トレイ: 表情・字幕・クリックスルー・テスト発話・設定・終了
- トレイ左クリック: 表示/非表示トグル / Ctrl+C: 終了

### 設定の保存先
- ペルソナ: `assets/characters/<id>/persona.md`(Markdown)
- 感情ごとの立ち絵差し替え: `assets/characters/<id>/emotions.json`
- その他(テーマ・機能・接続・ボット): `config.yaml`(GUI保存には `--with pyyaml` が必要)

## リリース相当で試す(おすすめ)
Windowsローカルにコピーして、**`run.bat` をダブルクリック**で起動できる。初回だけ依存を同期する。
```powershell
robocopy \\wsl.localhost\Ubuntu-24.04\home\tomoya\github\AIchan C:\dev\AIchan /E /XD .venv .git data __pycache__
cd C:\dev\AIchan
.\run.bat        # 依存を uv sync --extra full → 起動(2回目以降は速い)
```
- `uv` 未導入なら run.bat が案内する。
- 外部プロセスの自動起動: `config.yaml` で **TTSサーバ(`tts.autostart_server`)** と **LMStudio(`llm.autostart` + `llm.server_cmd`)** を有効にすると、アプリ起動時に一緒に立ち上がる(STT はアプリ内蔵なので起動不要)。
- 単体 `.exe` 配布(PyInstaller)は [packaging/](packaging/) を参照(任意・Windows実機でビルド)。

## 前提サービス(任意・揃うと本機能が有効)
- **LMStudio**: OpenAI互換APIを `localhost:1234` で起動、Gemma 3 12B(Vision対応)をロード
- **Irodori-TTS-Server**: `localhost:8088` で起動(ROCm)。声は `/v1/audio/voices` で登録
- **Whisper**: faster-whisper(または whisper.cpp/Vulkan)

## ディレクトリ
- `aichan/` — 本体: `ui/`(表示) `llm/` `tts/` `stt/` `vision/` `memory/` `scheduler/`
  `discord_bot/` `orchestrator.py`(対話制御コア) `settings.py`(config.yaml)
- `character/<id>/` — 立ち絵の原本(green screen)
- `assets/characters/<id>/` — 背景除去後の透過PNG(アプリが読む)
- `tools/remove_bg.py` — 背景除去バッチ
- `data/` — ローカル状態: ウィンドウ位置・SQLite DB(gitignore)
