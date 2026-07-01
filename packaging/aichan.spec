# PyInstaller spec — 単体 .exe 化(任意・Windows実機でビルド)。
# 使い方(Windows):
#   uv run --extra full --with pyinstaller pyinstaller packaging/aichan.spec
#
# 注意: faster-whisper(ctranslate2)/sounddevice(portaudio)/PySide6 はネイティブ
# バイナリを含むため、環境により hiddenimports / binaries の追加調整が要ることがある。
# まずは uv ランチャー(run.bat)での配布を推奨。exe はその次のステップ。

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_all

root = Path(SPECPATH).parent

datas = [
    (str(root / "assets"), "assets"),       # 立ち絵・persona.md・emotions.json
    (str(root / "config.yaml.example"), "."),
]
binaries = []
hiddenimports = collect_submodules("aichan")  # 遅延import(settings_dialog/updater等)対策

# STT/音声などネイティブ依存はまるごと収集(datas+binaries+hiddenimports)。
# 特に faster-whisper は ctranslate2 / onnxruntime(VAD) / av / tokenizers が要る。
for mod in ("faster_whisper", "ctranslate2", "onnxruntime", "av",
            "tokenizers", "sounddevice", "soundfile", "webrtcvad", "mss"):
    try:
        d, b, h = collect_all(mod)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [str(root / "packaging" / "launcher.py")],   # 相対import対策: パッケージとして起動
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="AIchan",
    console=False,                 # GUIアプリ(コンソール非表示)
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name="AIchan",
)
