"""設定ダイアログ(右クリック→設定…)。

タブ: キャラ/ペルソナ・感情ごとの立ち絵・テーマカラー・機能オンオフ・接続/ボット。
保存先:
- ペルソナ → assets/characters/<id>/persona.md
- 感情の立ち絵差し替え → assets/characters/<id>/emotions.json
- それ以外 → config.yaml(pyyaml が必要)
テーマ・字幕・クリックスルー・立ち絵は即時反映。接続/音声/スケジュール系は再起動で反映。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import config
from ..config import EMOTIONS


class ColorButton(QPushButton):
    """色を表示し、クリックで色選択するボタン。"""

    def __init__(self, color: str, on_change=None) -> None:
        super().__init__()
        self._color = color
        self._on_change = on_change
        self.setFixedSize(64, 24)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self) -> None:
        self.setStyleSheet(
            f"background:{self._color}; border:1px solid #888; border-radius:5px;"
        )
        self.setText(self._color)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "色を選ぶ")
        if c.isValid():
            self._color = c.name()
            self._refresh()
            if self._on_change:
                self._on_change(self._color)

    def color(self) -> str:
        return self._color


class SettingsDialog(QDialog):
    def __init__(self, window, cfg) -> None:
        super().__init__(window)
        self.window = window
        self.cfg = cfg
        self.setWindowTitle("AIちゃん 設定")
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._tab_character(), "キャラ")
        self.tabs.addTab(self._tab_user(), "あなた")
        self.tabs.addTab(self._tab_emotions(), "立ち絵")
        self.tabs.addTab(self._tab_theme(), "テーマ")
        self.tabs.addTab(self._tab_features(), "機能")
        self.tabs.addTab(self._tab_connection(), "接続/ボット")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Close, self
        )
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Close).setText("閉じる")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(buttons)

    # ---- キャラ / ペルソナ -------------------------------------------
    def _tab_character(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.cb_char = QComboBox()
        chars = config.list_characters() or [self.cfg.character.id]
        self.cb_char.addItems(chars)
        self.cb_char.setCurrentText(self.cfg.character.id)
        self.cb_char.currentTextChanged.connect(self._on_char_changed)
        self.ed_name = QLineEdit(self.cfg.character.name)
        self.ed_persona = QPlainTextEdit(config.load_persona(self.cfg.character.id) or "")
        self.ed_persona.setMinimumHeight(220)
        form.addRow("キャラID", self.cb_char)
        form.addRow("表示名", self.ed_name)
        form.addRow(QLabel("ペルソナ (Markdown)"))
        form.addRow(self.ed_persona)
        return w

    # ---- あなた(ユーザーの呼ばれ方) --------------------------------
    def _tab_user(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        u = self.cfg.user
        self.ed_user_name = QLineEdit(u.name)
        self.ed_user_reading = QLineEdit(u.name_reading)
        self.ed_user_reading.setPlaceholderText("かな(TTSの発音矯正用)")
        self.cb_honorific = QComboBox()
        self.cb_honorific.setEditable(True)
        self.cb_honorific.addItems(["さん", "ちゃん", "くん", "様", "(呼び捨て)"])
        self.cb_honorific.setCurrentText(u.honorific if u.honorific else "(呼び捨て)")
        self.lbl_call = QLabel()
        form.addRow("あなたの名前", self.ed_user_name)
        form.addRow("読み(かな)", self.ed_user_reading)
        form.addRow("敬称", self.cb_honorific)
        form.addRow("呼び方プレビュー", self.lbl_call)
        for wdg in (self.ed_user_name, self.ed_user_reading):
            wdg.textChanged.connect(self._update_call_preview)
        self.cb_honorific.currentTextChanged.connect(self._update_call_preview)
        self._update_call_preview()
        return w

    def _honorific_value(self) -> str:
        h = self.cb_honorific.currentText().strip()
        return "" if h in ("(呼び捨て)", "呼び捨て", "") else h

    def _update_call_preview(self) -> None:
        name = self.ed_user_name.text().strip()
        reading = self.ed_user_reading.text().strip()
        hon = self._honorific_value()
        disp = (name + hon) if name else "(未設定 → 「あなた」)"
        spoken = ((reading or name) + hon) if name else ""
        self.lbl_call.setText(f"表示: {disp}    発音: {spoken}")

    def _on_char_changed(self, cid: str) -> None:
        self.ed_persona.setPlainText(config.load_persona(cid) or "")
        self._emotion_overrides = config.load_emotion_overrides(cid)
        self._rebuild_emotion_rows(cid)

    # ---- 感情ごとの立ち絵 --------------------------------------------
    def _tab_emotions(self) -> QWidget:
        w = QWidget()
        self._emo_form = QFormLayout(w)
        self._emotion_overrides = config.load_emotion_overrides(self.cfg.character.id)
        self._emo_rows: dict[str, QLabel] = {}
        self._rebuild_emotion_rows(self.cfg.character.id)
        return w

    def _rebuild_emotion_rows(self, cid: str) -> None:
        while self._emo_form.rowCount():
            self._emo_form.removeRow(0)
        self._emo_rows = {}
        for emo in EMOTIONS:
            row = QWidget()
            h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
            thumb = QLabel()
            path = config.emotion_path(cid, emo)
            if path.exists():
                pm = QPixmap(str(path)).scaledToHeight(34, Qt.SmoothTransformation)
                thumb.setPixmap(pm)
            state = QLabel("差し替え" if emo in self._emotion_overrides else "")
            btn = QPushButton("変更")
            btn.clicked.connect(lambda _=False, e=emo, c=cid: self._pick_emotion_img(e, c))
            clr = QPushButton("既定")
            clr.clicked.connect(lambda _=False, e=emo, c=cid: self._clear_emotion_img(e, c))
            h.addWidget(thumb); h.addWidget(state, 1); h.addWidget(btn); h.addWidget(clr)
            self._emo_rows[emo] = state
            self._emo_form.addRow(emo, row)

    def _pick_emotion_img(self, emo: str, cid: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"{emo} の立ち絵", "", "PNG (*.png)")
        if path:
            self._emotion_overrides[emo] = path
            self._rebuild_emotion_rows(cid)

    def _clear_emotion_img(self, emo: str, cid: str) -> None:
        self._emotion_overrides.pop(emo, None)
        self._rebuild_emotion_rows(cid)

    # ---- テーマ -------------------------------------------------------
    def _tab_theme(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        t = self.cfg.theme
        self._color_btns: dict[str, ColorButton] = {}
        fields = [
            ("bubble_bg", "吹き出し背景(下)"), ("bubble_bg2", "吹き出し背景(上)"),
            ("bubble_border", "吹き出し枠"), ("bubble_text", "本文文字"),
            ("name_color", "名前の色"), ("status_bg", "状態の背景"),
            ("status_text", "状態の文字"), ("accent", "アクセント(マイク等)"),
        ]
        for key, label in fields:
            btn = ColorButton(getattr(t, key), on_change=lambda c, k=key: self._preview_theme(k, c))
            self._color_btns[key] = btn
            form.addRow(label, btn)
        return w

    def _preview_theme(self, key: str, color: str) -> None:
        setattr(self.cfg.theme, key, color)
        self.window.apply_theme(self.cfg.theme)   # 即プレビュー

    # ---- 機能オンオフ -------------------------------------------------
    def _tab_features(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.ck_tts = QCheckBox(); self.ck_tts.setChecked(self.cfg.tts.enabled)
        self.ck_stt = QCheckBox(); self.ck_stt.setChecked(self.cfg.stt.enabled)
        self.ck_screen = QCheckBox(); self.ck_screen.setChecked(self.cfg.screen.enabled)
        self.ck_proactive = QCheckBox(); self.ck_proactive.setChecked(self.cfg.proactive.enabled)
        self.ck_subtitle = QCheckBox(); self.ck_subtitle.setChecked(self.window.state.show_subtitle)
        self.ck_movable = QCheckBox(); self.ck_movable.setChecked(self.window.state.movable)
        self.ck_click = QCheckBox(); self.ck_click.setChecked(self.window.state.click_through)
        self.sp_height = QSpinBox(); self.sp_height.setRange(200, 1000)
        self.sp_height.setValue(self.window.state.height_px)
        self.sp_short = QSpinBox(); self.sp_short.setRange(2, 60)
        self.sp_short.setValue(self.cfg.memory.short_window_turns)
        self.sp_sum = QSpinBox(); self.sp_sum.setRange(10, 500)
        self.sp_sum.setValue(self.cfg.memory.summarize_after_turns)
        form.addRow("音声で話す(TTS)", self.ck_tts)
        form.addRow("音声を聞く(STT)", self.ck_stt)
        form.addRow("画面読み取り", self.ck_screen)
        form.addRow("自発発話", self.ck_proactive)
        form.addRow("字幕を表示", self.ck_subtitle)
        form.addRow("ドラッグで移動", self.ck_movable)
        form.addRow("クリックスルー", self.ck_click)
        form.addRow("立ち絵の高さ(px)", self.sp_height)
        form.addRow("短期記憶ターン数", self.sp_short)
        form.addRow("要約する閾値", self.sp_sum)
        return w

    # ---- 接続 / ボット ------------------------------------------------
    def _tab_connection(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.ed_llm_url = QLineEdit(self.cfg.llm.base_url)
        self.ed_llm_model = QLineEdit(self.cfg.llm.model)
        self.sp_temp = QDoubleSpinBox(); self.sp_temp.setRange(0, 2); self.sp_temp.setSingleStep(0.1)
        self.sp_temp.setValue(self.cfg.llm.temperature)
        self.sp_maxtok = QSpinBox(); self.sp_maxtok.setRange(128, 8192)
        self.sp_maxtok.setValue(self.cfg.llm.max_tokens)
        self.ck_llm_auto = QCheckBox(); self.ck_llm_auto.setChecked(self.cfg.llm.autostart)
        self.ed_llm_cmd = QLineEdit(" ".join(self.cfg.llm.server_cmd))
        self.ed_llm_cmd.setPlaceholderText("例: lms server start")
        self.ed_tts_url = QLineEdit(self.cfg.tts.base_url)
        self.ed_tts_voice = QLineEdit(self.cfg.tts.voice)
        self.ck_tts_auto = QCheckBox(); self.ck_tts_auto.setChecked(self.cfg.tts.autostart_server)
        self.ed_tts_cmd = QLineEdit(" ".join(self.cfg.tts.server_cmd))
        self.ed_tts_cmd.setPlaceholderText("例: uv run python -m irodori_openai_tts --port 8088")
        self.cb_stt_model = QComboBox(); self.cb_stt_model.addItems(["tiny", "base", "small", "medium", "large-v3"])
        self.cb_stt_model.setCurrentText(self.cfg.stt.model)
        self.cb_stt_device = QComboBox(); self.cb_stt_device.addItems(["auto", "cuda", "cpu", "vulkan"])
        self.cb_stt_device.setCurrentText(self.cfg.stt.device)
        self.cb_stt_mode = QComboBox(); self.cb_stt_mode.addItems(["ptt", "vad"])
        self.cb_stt_mode.setCurrentText(self.cfg.stt.mode)
        self.ck_discord = QCheckBox(); self.ck_discord.setChecked(self.cfg.discord.enabled)
        self.ed_discord_token = QLineEdit(self.cfg.discord.token)
        self.ed_discord_token.setEchoMode(QLineEdit.Password)
        self.ed_discord_ch = QLineEdit(",".join(str(c) for c in self.cfg.discord.channel_ids))
        for label, wdg in [
            ("LLM URL", self.ed_llm_url), ("LLM モデル", self.ed_llm_model),
            ("temperature", self.sp_temp), ("max_tokens", self.sp_maxtok),
            ("LMStudio 自動起動", self.ck_llm_auto), ("LMStudio 起動コマンド", self.ed_llm_cmd),
            ("TTS URL", self.ed_tts_url), ("TTS 声(voice)", self.ed_tts_voice),
            ("TTSサーバ 自動起動", self.ck_tts_auto), ("TTSサーバ 起動コマンド", self.ed_tts_cmd),
            ("Whisper モデル", self.cb_stt_model), ("STT デバイス", self.cb_stt_device),
            ("音声入力モード", self.cb_stt_mode),
            ("Discord 有効", self.ck_discord), ("Discord トークン", self.ed_discord_token),
            ("Discord チャンネルID(,区切り)", self.ed_discord_ch),
        ]:
            form.addRow(label, wdg)
        return w

    # ---- 保存 ---------------------------------------------------------
    def _save(self) -> None:
        c = self.cfg
        cid = self.cb_char.currentText()
        char_changed = cid != c.character.id

        # キャラ / ペルソナ
        c.character.id = cid
        c.character.name = self.ed_name.text().strip() or cid
        config.save_persona(cid, self.ed_persona.toPlainText())

        # あなた(呼ばれ方)
        c.user.name = self.ed_user_name.text().strip()
        c.user.name_reading = self.ed_user_reading.text().strip()
        c.user.honorific = self._honorific_value()

        # 立ち絵差し替え
        config.save_emotion_overrides(cid, self._emotion_overrides)

        # 機能
        c.tts.enabled = self.ck_tts.isChecked()
        c.stt.enabled = self.ck_stt.isChecked()
        c.screen.enabled = self.ck_screen.isChecked()
        c.proactive.enabled = self.ck_proactive.isChecked()
        c.memory.short_window_turns = self.sp_short.value()
        c.memory.summarize_after_turns = self.sp_sum.value()
        self.window.state.show_subtitle = self.ck_subtitle.isChecked()
        self.window.state.movable = self.ck_movable.isChecked()
        self.window.state.click_through = self.ck_click.isChecked()
        self.window.state.height_px = self.sp_height.value()

        # 接続 / ボット
        c.llm.base_url = self.ed_llm_url.text().strip()
        c.llm.model = self.ed_llm_model.text().strip()
        c.llm.temperature = self.sp_temp.value()
        c.llm.max_tokens = self.sp_maxtok.value()
        c.llm.autostart = self.ck_llm_auto.isChecked()
        c.llm.server_cmd = self.ed_llm_cmd.text().split()
        c.tts.base_url = self.ed_tts_url.text().strip()
        c.tts.voice = self.ed_tts_voice.text().strip()
        c.tts.autostart_server = self.ck_tts_auto.isChecked()
        c.tts.server_cmd = self.ed_tts_cmd.text().split()
        c.stt.model = self.cb_stt_model.currentText()
        c.stt.device = self.cb_stt_device.currentText()
        c.stt.mode = self.cb_stt_mode.currentText()
        c.discord.enabled = self.ck_discord.isChecked()
        c.discord.token = self.ed_discord_token.text().strip()
        c.discord.channel_ids = _parse_ids(self.ed_discord_ch.text())

        # 永続化(pyyaml が無くても JSON フォールバックで必ず保存される)
        self.window.state.save()
        c.save()

        # 即時反映
        self.window.apply_theme(c.theme)
        self.window._toggle_movable(self.window.state.movable)   # カーソル反映
        self.window._apply_click_through(self.window.state.click_through)
        if not self.window.state.show_subtitle:
            self.window._hide_bubble()
        if char_changed:
            self.window.reload_character(cid, c.character.name)
        else:
            self.window.reload_pixmaps()

        msg = ("保存しました。\n"
               "接続・音声・スケジュール・Discord の変更は再起動で反映されます。")
        QMessageBox.information(self, "設定", msg)
        self.accept()


def _parse_ids(text: str) -> list[int]:
    out = []
    for part in text.replace("、", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out
