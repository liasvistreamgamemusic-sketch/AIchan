# 配布ビルド(任意)

個人で試すだけなら **`run.bat`(uvランチャー)** が最も確実。ここでは単体 `.exe` 化の手順を示す。

## 方針
- **推奨: uv ランチャー配布**(`run.bat`)。依存解決を uv に任せられ、ネイティブ依存のトラブルが少ない。
- **単体exe(PyInstaller)**: 配布物を1フォルダにまとめたい場合。Windows実機でのビルドと調整が前提。

## PyInstaller での exe 化(Windows)
```powershell
cd C:\dev\AIchan
uv run --extra full --with pyinstaller pyinstaller packaging/aichan.spec
# 出力: dist/AIchan/AIchan.exe
```

### 注意・つまずきどころ
- **faster-whisper / ctranslate2**: ネイティブDLLを含む。`collect_dynamic_libs` で拾えないものがあれば `binaries` に手動追加。
- **Whisperモデル**: 初回実行時にダウンロードされる(exeには含めない)。オフライン配布したいなら model フォルダを同梱し `STTConfig.model` にパス指定。
- **PySide6**: プラグイン(platforms/styles)が要る。PyInstaller の PySide6 フックで基本入るが、起動しない場合は `--collect-all PySide6`。
- **sounddevice**: PortAudio の DLL が要る。`collect_dynamic_libs("sounddevice")` で拾えなければ手動。
- **外部サービス**: LMStudio と Irodori-TTS-Server は別プロセス。exeには含めない。`config.yaml` の autostart で起動する運用にする。

### 配布物に含めるもの
- `dist/AIchan/`(exe一式)
- `config.yaml`(各自の環境用。`config.yaml.example` をコピーして編集)
- 必要なら Whisper モデル、TTS の voice 参照音声

> まずは run.bat で動作を固め、安定してから exe 化に進むのが安全。
