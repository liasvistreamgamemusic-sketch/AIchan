"""透過・最前面・ドラッグ可能なキャラクターウィンドウ。

docs/specification.md §4。
- 枠なし / 背景透過 / 常に最前面 / ドラッグ移動 / 画面下に密着
- 立ち絵の感情差し替え + 可愛い吹き出し(名前タグ + 影)
- 体に重なる常設マイクボタン(長押しで録音 = PTT)
- テキスト入力欄(ダブルクリックで開閉)
- 固定アンカー方式: ドラッグで決めた足元位置を記憶し、吹き出し/入力欄で高さが
  変わっても常にそこへ戻す(ガタつき・ずり下がり防止)
- Orchestrator からの通知(別スレッド)を Qtシグナル経由でスレッド安全にUI反映
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import config


class SpeechBubble(QFrame):
    """名前タグ付き・角丸・影付きの可愛い吹き出し(テーマカラー対応)。"""

    def __init__(self, name: str, theme=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bubble")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 11)
        lay.setSpacing(2)
        self.name_label = QLabel(name, self)
        self.name_label.setObjectName("name")
        self.text_label = QLabel(self)
        self.text_label.setObjectName("text")
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.PlainText)
        self.text_label.setMaximumWidth(340)
        lay.addWidget(self.name_label)
        lay.addWidget(self.text_label)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(180, 120, 150, 110))
        self.setGraphicsEffect(shadow)
        self.apply_theme(theme)
        self.hide()

    def apply_theme(self, theme) -> None:
        from ..settings import ThemeConfig
        t = theme or ThemeConfig()
        self.setStyleSheet(
            "#bubble {"
            f"  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"    stop:0 {t.bubble_bg2}, stop:1 {t.bubble_bg});"
            f"  border: 2.5px solid {t.bubble_border}; border-radius: 18px;"
            "}"
            f"QLabel#name {{ color:{t.name_color}; font-weight:bold; font-size:12px;"
            "  font-family:'Meiryo','Yu Gothic UI',sans-serif; }"
            f"QLabel#text {{ color:{t.bubble_text}; font-size:14px;"
            "  font-family:'Meiryo','Yu Gothic UI',sans-serif; }"
        )

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)


class MicButton(QPushButton):
    """体に重なるマイク。長押し(押下中)で録音。絵文字を使わず描画する。"""

    def __init__(self, parent: QWidget | None = None, accent: str = "#e36fa0") -> None:
        super().__init__(parent)
        self.setFixedSize(46, 46)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("長押しで話す")
        self._active = False
        self._accent = accent
        self.setStyleSheet("border:none; background:transparent;")

    def set_accent(self, color: str) -> None:
        self._accent = color
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        s = r.height()
        accent = QColor(self._accent)
        # 背景円
        bg = accent if self._active else QColor(255, 255, 255, 235)
        p.setBrush(bg)
        p.setPen(QPen(accent, max(1.5, s * 0.05)))
        p.drawEllipse(r)
        # マイク本体(サイズ比で描画)
        mic = QColor("#ffffff") if self._active else accent
        cx = r.center().x()
        p.setPen(QPen(mic, max(1.5, s * 0.055)))
        p.setBrush(mic)
        head_w, head_h = s * 0.26, s * 0.40
        head_top = r.top() + s * 0.20
        p.drawRoundedRect(QRectF(cx - head_w / 2, head_top, head_w, head_h),
                          head_w / 2, head_w / 2)
        # 受け皿の弧 + 支柱 + 台
        p.setBrush(Qt.NoBrush)
        arc = s * 0.46
        p.drawArc(QRectF(cx - arc / 2, head_top + s * 0.06, arc, arc), 200 * 16, 140 * 16)
        stem_top = head_top + head_h + s * 0.07
        p.drawLine(int(cx), int(stem_top), int(cx), int(stem_top + s * 0.12))
        base = s * 0.16
        p.drawLine(int(cx - base), int(stem_top + s * 0.12),
                   int(cx + base), int(stem_top + s * 0.12))
        p.end()


class CharacterWindow(QWidget):
    sigReply = Signal(object, str)
    sigThinking = Signal(bool)
    sigSpeaking = Signal(bool)
    sigUserSaid = Signal(str, str)
    sigUpdate = Signal(object, bool)   # (info|None, manual)
    sigUpdateDone = Signal(bool)       # 更新適用の結果

    def __init__(self, state: config.WindowState | None = None, controller=None,
                 name: str = "すみれ", app_cfg=None) -> None:
        super().__init__()
        self.state = state or config.WindowState.load()
        self.controller = controller
        self.app_cfg = app_cfg
        self.theme = app_cfg.theme if app_cfg else None
        self.name = name
        self.on_stay_running = None       # 更新しない場合にサービスを起動するコールバック
        self._stayed = False
        self._pixmaps: dict[str, QPixmap] = {}
        self._drag_offset: QPoint | None = None
        self._anchor_bottom: int | None = None     # 足元の固定アンカー(画面座標)
        self._anchor_cx: int | None = None

        self._bubble_timer = QTimer(self); self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self._hide_bubble)
        self._mouth_timer = QTimer(self); self._mouth_timer.timeout.connect(self._mouth_tick)
        self._mouth_phase = 0

        self._init_window()
        self._init_layout()
        self.set_emotion(self.state.emotion, persist=False)
        self._restore_position()
        self._init_tray()
        self._apply_click_through(self.state.click_through)

        self.sigReply.connect(self._on_reply)
        self.sigThinking.connect(self._on_thinking)
        self.sigSpeaking.connect(self._on_speaking)
        self.sigUserSaid.connect(self._on_user_said)
        self.sigUpdate.connect(self._on_update)
        self.sigUpdateDone.connect(self._on_update_done)

    # ---- Orchestrator 連携 -------------------------------------------
    def make_hooks(self):
        from ..orchestrator import Hooks
        return Hooks(
            reply_ready=lambda reply, source: self.sigReply.emit(reply, source),
            user_said=lambda text, source: self.sigUserSaid.emit(text, source),
            thinking_changed=lambda busy: self.sigThinking.emit(busy),
            speaking_changed=lambda speaking: self.sigSpeaking.emit(speaking),
        )

    def _on_reply(self, reply, source: str) -> None:
        self.set_emotion(reply.emotion, persist=False)
        self.say(reply.speech)

    def _on_thinking(self, busy: bool) -> None:
        self._set_status("考え中…" if busy else "")

    def _on_speaking(self, speaking: bool) -> None:
        if speaking:
            self._mouth_phase = 0
            self._mouth_timer.start(110)
        else:
            self._mouth_timer.stop()
            self._apply_offset(0)

    def _on_user_said(self, text: str, source: str) -> None:
        self._set_status(f"きいてるよ: {text[:18]}")

    # ---- テーマ / リロード -------------------------------------------
    def _style_status(self) -> None:
        from ..settings import ThemeConfig
        t = self.theme or ThemeConfig()
        self.status.setStyleSheet(
            f"color:{t.status_text}; background:{t.status_bg}; border-radius:9px;"
            "padding:2px 10px; font-size:11px;"
        )

    def apply_theme(self, theme) -> None:
        """テーマカラーを即時反映(吹き出し・状態・マイク)。"""
        self.theme = theme
        self.bubble.apply_theme(theme)
        self._style_status()
        if theme is not None:
            self.mic.set_accent(theme.accent)

    def reload_character(self, character_id: str, name: str | None = None) -> None:
        """キャラ切替: 立ち絵を読み直す。"""
        self.state.character_id = character_id
        if name:
            self.name = name
            self.bubble.name_label.setText(name)
        self.reload_pixmaps()

    def reload_pixmaps(self) -> None:
        """立ち絵キャッシュを破棄して現在の感情を再描画(差し替え反映)。"""
        self._pixmaps.clear()
        self.set_emotion(self.state.emotion, persist=False)

    def open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        if self.app_cfg is None:
            from ..settings import AppConfig
            self.app_cfg = AppConfig.load()
            self.theme = self.app_cfg.theme
        dlg = SettingsDialog(self, self.app_cfg)
        dlg.exec()

    # ---- 起動の続行(更新しない場合にサービスを起動) -----------------
    def begin_running(self) -> None:
        """更新しないと決まったら一度だけサービスを起動する(冪等)。"""
        if self._stayed:
            return
        self._stayed = True
        if self.on_stay_running:
            self.on_stay_running()

    # ---- 自動アップデート --------------------------------------------
    def check_updates(self, manual: bool = False) -> None:
        """GitHub Releases を別スレッドで確認(結果は sigUpdate へ)。"""
        import threading
        repo = self.app_cfg.update.repo if self.app_cfg else ""

        def work() -> None:
            from .. import updater
            info = updater.check(repo) if repo else None
            self.sigUpdate.emit(info, manual)

        threading.Thread(target=work, daemon=True).start()

    def _on_update(self, info, manual: bool) -> None:
        from .. import updater
        if not info:
            if manual:
                QMessageBox.information(self, "アップデート", "最新版を使用しています。")
            self.begin_running()      # 更新なし → 通常起動
            return
        tag = info.get("tag", "")
        can_apply = updater.is_frozen() and bool(info.get("asset_url"))
        auto = self.app_cfg and self.app_cfg.update.auto_install
        if auto and can_apply:
            self.tray.showMessage("アップデート", f"{tag} をダウンロードして適用します",
                                  QSystemTrayIcon.Information, 4000)
            self._begin_update(info)  # サービスは起動せず、更新→再起動
            return
        notes = (info.get("notes") or "")[:400]
        ret = QMessageBox.question(
            self, "アップデートがあります",
            f"新しいバージョン {tag} があります。更新しますか?\n\n{notes}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            self.begin_running()      # 見送り → 通常起動
            return
        if can_apply:
            self._begin_update(info)  # サービスは起動せず、更新→再起動
        else:
            import webbrowser
            webbrowser.open(info.get("html_url") or "")
            self.begin_running()      # 開発実行等はブラウザを開いて通常起動

    def _begin_update(self, info) -> None:
        """更新のDL+適用を別スレッドで(UIを固めない)。完了で終了 or 失敗表示。"""
        import threading
        self._set_status("更新をダウンロード中…そのままお待ちください")

        def work() -> None:
            ok = False
            try:
                from .. import updater
                ok = updater.apply(info.get("asset_url", ""))
            finally:
                self.sigUpdateDone.emit(bool(ok))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_done(self, ok: bool) -> None:
        if ok:
            QApplication.quit()   # 入れ替えバッチが終了を待って再起動する
        else:
            self._set_status("")
            QMessageBox.warning(
                self, "アップデート",
                "更新の適用に失敗しました。リリースページから手動で更新してください。\n"
                "(詳細ログ: data フォルダの update.log)",
            )
            self.begin_running()  # 失敗時はそのまま通常起動

    # ---- セットアップ -------------------------------------------------
    def _init_window(self) -> None:
        self.setWindowTitle(f"AIちゃん — {self.name}")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def _init_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.bubble = SpeechBubble(self.name, self.theme, self)
        self.status = QLabel(self)
        self.status.setAlignment(Qt.AlignCenter)
        self._style_status()
        self.status.hide()

        self.char_label = QLabel(self)
        self.char_label.setAttribute(Qt.WA_TranslucentBackground, True)
        self.char_label.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)

        layout.addWidget(self.bubble, 0, Qt.AlignHCenter)
        layout.addWidget(self.status, 0, Qt.AlignHCenter)
        layout.addWidget(self.char_label, 0, Qt.AlignHCenter)

        # 体の内部に重なる操作オーバーレイ(レイアウト外なので、表示してもキャラは動かない)。
        # [入力ボックス][マイク] を同じ高さで横並び。ホバー時のみ表示。
        bar_h = 36
        self.overlay = QWidget(self)
        ov = QHBoxLayout(self.overlay)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(6)

        self.input_edit = QLineEdit(self.overlay)
        self.input_edit.setPlaceholderText("話しかける…")
        self.input_edit.setFixedHeight(bar_h)
        self.input_edit.setMinimumWidth(168)
        self.input_edit.setStyleSheet(
            "background:rgba(255,255,255,248); border:2px solid #f6a8cb;"
            "border-radius:13px; padding:3px 10px; font-size:13px;"
        )
        self.input_edit.returnPressed.connect(self._send_input)

        accent = self.theme.accent if self.theme else "#e36fa0"
        self.mic = MicButton(self.overlay, accent=accent)
        self.mic.setFixedSize(bar_h, bar_h)        # 入力ボックスと同じ高さ
        self.mic.pressed.connect(self._ptt_press)
        self.mic.released.connect(self._ptt_release)

        ov.addWidget(self.input_edit)
        ov.addWidget(self.mic)
        self.overlay.hide()

        # ホバー解除時に少し待ってから隠す(子へのホバーで誤って隠さないため)
        self._hide_overlay_timer = QTimer(self)
        self._hide_overlay_timer.setSingleShot(True)
        self._hide_overlay_timer.timeout.connect(self._maybe_hide_overlays)

    def _init_tray(self) -> None:
        icon_pix = self._scaled_pixmap(config.DEFAULT_EMOTION) or QPixmap(32, 32)
        self.tray = QSystemTrayIcon(icon_pix, self)
        self.tray.setToolTip(f"AIちゃん — {self.name}")
        # トレイのメニューは表示直前に作り直す(クリックスルー時の確実な復帰口)
        self._tray_menu = QMenu()
        self._tray_menu.aboutToShow.connect(self._repopulate_tray_menu)
        self.tray.setContextMenu(self._tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    # ---- 立ち絵 -------------------------------------------------------
    def _scaled_pixmap(self, emotion: str) -> QPixmap | None:
        emotion = config.resolve_emotion(emotion)
        if emotion in self._pixmaps:
            return self._pixmaps[emotion]
        path = config.emotion_path(self.state.character_id, emotion)
        if not path.exists():
            return None
        pm = QPixmap(str(path))
        if pm.isNull():
            return None
        dpr = self.devicePixelRatioF() if self.windowHandle() else 1.0
        scaled = pm.scaledToHeight(int(self.state.height_px * dpr), Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self._pixmaps[emotion] = scaled
        return scaled

    def set_emotion(self, emotion: str, *, persist: bool = True) -> None:
        emotion = config.resolve_emotion(emotion)
        pm = self._scaled_pixmap(emotion)
        if pm is None:
            return
        self.char_label.setPixmap(pm)
        self.char_label.setFixedSize(pm.size() / pm.devicePixelRatio())
        self.state.emotion = emotion
        self._reanchor()
        if persist:
            self.state.save()

    def _mouth_tick(self) -> None:
        self._mouth_phase = (self._mouth_phase + 1) % 4
        self._apply_offset(-2 if self._mouth_phase in (1, 3) else 0)

    def _apply_offset(self, dy: int) -> None:
        self.char_label.setContentsMargins(0, max(0, -dy), 0, max(0, dy))

    # ---- 字幕・状態 ---------------------------------------------------
    def say(self, text: str, msec: int | None = None) -> None:
        if not self.state.show_subtitle or not text:
            return
        self.bubble.set_text(text)
        self.bubble.show()
        self._reanchor()
        if msec is None:
            msec = max(3000, min(11000, 2600 + 75 * len(text)))  # 長文ほど長く表示
        if msec > 0:
            self._bubble_timer.start(msec)

    def _hide_bubble(self) -> None:
        self.bubble.hide()
        self._reanchor()

    def _set_status(self, text: str) -> None:
        self.status.setVisible(bool(text))
        if text:
            self.status.setText(text)
        self._reanchor()

    # ---- 固定アンカー(足元を動かさない) -----------------------------
    def _set_anchor_from_current(self) -> None:
        self._anchor_bottom = self.y() + self.height()
        self._anchor_cx = self.x() + self.width() // 2

    def _reanchor(self) -> None:
        """中身が変わってもアンカー(足元・中心X)を保って再配置。"""
        self.adjustSize()
        hint = self.sizeHint()
        if self._anchor_bottom is None or self._anchor_cx is None:
            self.resize(hint)
        else:
            self.setGeometry(
                self._anchor_cx - hint.width() // 2,
                self._anchor_bottom - hint.height(),
                hint.width(), hint.height(),
            )
        self._position_overlays()

    def _position_overlays(self) -> None:
        """操作オーバーレイ(入力欄+マイク)を立ち絵の下部内側に重ねる。"""
        self.overlay.adjustSize()
        cg = self.char_label.geometry()
        x = cg.center().x() - self.overlay.width() // 2
        y = cg.bottom() - self.overlay.height() - 14
        self.overlay.move(x, y)
        self.overlay.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_overlays()

    # ---- 入力 ---------------------------------------------------------
    def _send_input(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        self.input_edit.clear()
        if self.controller is not None:
            self.controller.handle_text(text)
        else:
            self.say(f"(エコー) {text}")

    def toggle_input_bar(self) -> None:
        vis = not self.overlay.isVisible()
        self.overlay.setVisible(vis)
        if vis:
            self._position_overlays()
            self.input_edit.setFocus()

    def _ptt_press(self) -> None:
        mic = getattr(self.controller, "mic", None)
        if mic is not None and getattr(mic, "available", lambda: False)():
            mic.start_recording()
            self.mic.set_active(True)
            self._set_status("…録音中(離すと送信)")
        else:
            self._set_status("音声入力は未設定")

    def _ptt_release(self) -> None:
        mic = getattr(self.controller, "mic", None)
        self.mic.set_active(False)
        if mic is not None and getattr(mic, "available", lambda: False)():
            mic.stop_recording()
            self._set_status("")

    # ---- メニュー -----------------------------------------------------
    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        self._fill_menu(menu)
        return menu

    def _fill_menu(self, menu: QMenu) -> None:
        """メニュー項目を(現在の状態を反映して)詰める。トレイ/右クリック共通。"""
        emo_menu = menu.addMenu("表情")
        for emo in config.available_emotions(self.state.character_id):
            act = QAction(emo, self, checkable=True)
            act.setChecked(emo == self.state.emotion)
            act.triggered.connect(lambda _=False, e=emo: self.set_emotion(e))
            emo_menu.addAction(act)

        menu.addSeparator()
        menu.addAction(self._toggle_action("ドラッグで移動", self.state.movable,
                                           self._toggle_movable))
        menu.addAction(self._toggle_action("入力欄", self.overlay.isVisible(),
                                           lambda c: self.toggle_input_bar()))
        menu.addAction(self._toggle_action("字幕を表示", self.state.show_subtitle,
                                           self._toggle_subtitle))
        menu.addAction(self._toggle_action("クリックスルー", self.state.click_through,
                                           self._toggle_click_through))
        test = QAction("テスト発話", self)
        test.triggered.connect(lambda: self.say("こんにちは、すみれだよ。今日もよろしくね。"))
        menu.addAction(test)
        menu.addSeparator()
        settings_act = QAction("設定…", self)
        settings_act.triggered.connect(self.open_settings)
        menu.addAction(settings_act)
        upd_act = QAction("アップデートを確認", self)
        upd_act.triggered.connect(lambda: self.check_updates(manual=True))
        menu.addAction(upd_act)
        quit_act = QAction("終了", self)
        quit_act.triggered.connect(QApplication.quit)
        menu.addAction(quit_act)

    def _repopulate_tray_menu(self) -> None:
        """トレイ表示直前に作り直してチェック状態を最新化(クリックスルー復帰用)。"""
        self._tray_menu.clear()
        self._fill_menu(self._tray_menu)

    def _toggle_action(self, label: str, checked: bool, slot) -> QAction:
        a = QAction(label, self, checkable=True); a.setChecked(checked)
        a.triggered.connect(slot)
        return a

    def _toggle_movable(self, checked: bool) -> None:
        self.state.movable = checked
        self.setCursor(Qt.SizeAllCursor if checked else Qt.ArrowCursor)
        self.state.save()

    def _toggle_subtitle(self, checked: bool) -> None:
        self.state.show_subtitle = checked
        if not checked:
            self._hide_bubble()
        self.state.save()

    def _toggle_click_through(self, checked: bool) -> None:
        self.state.click_through = checked
        self._apply_click_through(checked)
        self.state.save()

    def _apply_click_through(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowTransparentForInput, enabled)
        self.show()
        if enabled and hasattr(self, "tray"):
            # 本体がクリックを受けなくなるので、解除口(トレイ)を案内する
            self.tray.showMessage(
                "クリックスルー ON",
                "キャラはクリックを透過します。解除はトレイアイコンを右クリック→「クリックスルー」。",
                QSystemTrayIcon.Information, 5000,
            )

    # ---- ホバーでマイク/入力欄を表示 ---------------------------------
    def enterEvent(self, event) -> None:  # noqa: ARG002
        self._hide_overlay_timer.stop()
        self._show_overlays()

    def leaveEvent(self, event) -> None:  # noqa: ARG002
        self._hide_overlay_timer.start(220)

    def _show_overlays(self) -> None:
        self.overlay.show()
        self._position_overlays()       # レイアウト外なのでキャラは動かない

    def _maybe_hide_overlays(self) -> None:
        # カーソルがウィンドウ上 or 入力中なら隠さない
        if self.input_edit.hasFocus():
            return
        if self.geometry().contains(QCursor.pos()):
            self._hide_overlay_timer.start(220)
            return
        self.overlay.hide()

    # ---- マウス -------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.state.movable:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
        elif event.button() == Qt.RightButton:
            self._build_menu().popup(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self._set_anchor_from_current()       # 足元アンカー更新 + 保存
            self.state.anchor_cx = self._anchor_cx
            self.state.anchor_bottom = self._anchor_bottom
            self.state.save()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.setVisible(not self.isVisible())

    # ---- 位置 ---------------------------------------------------------
    def _restore_position(self) -> None:
        self.adjustSize()
        if self.state.anchor_cx is not None and self.state.anchor_bottom is not None:
            # 足元アンカーから配置(高さが変わっても足元が動かない)
            self._anchor_cx = self.state.anchor_cx
            self._anchor_bottom = self.state.anchor_bottom
            self._reanchor()
            return
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.right() - self.width() + 1 - self.state.side_margin
            y = geo.bottom() - self.height() + 1 - self.state.bottom_margin
            self.move(x, y)
        self._set_anchor_from_current()
        self._position_overlays()

    def closeEvent(self, event) -> None:
        self.state.save()
        super().closeEvent(event)
