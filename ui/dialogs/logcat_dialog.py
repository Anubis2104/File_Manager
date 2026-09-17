"""
ui/dialogs/logcat_dialog.py
Interactive, Real-time Desktop Logcat Diagnostic Window.
Features:
  - Real-time log streaming with ANSI / Color badge formatting.
  - Tag and Log Level filtering (Verbose, Debug, Info, Warn, Error).
  - Instant text search (Ctrl+F) with matching line highlights.
  - Auto-scroll toggle, Pause/Resume stream, and Export to file.
  - Main Thread Blocked / ANR alerts highlighted in distinct warning colors.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFont, QTextCursor, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QPlainTextEdit,
    QFileDialog, QMessageBox, QWidget, QFrame
)

from core.app_logcat import AppLogcat, LogRecord, LogLevel


class LogcatDialog(QDialog):
    """
    Live Logcat Inspector Dialog for FileManagerPro.
    Invoked via F12 or Toolbar Menu.
    """

    LEVEL_COLORS = {
        LogLevel.VERBOSE: "#8e8e93",
        LogLevel.DEBUG:   "#5ac8fa",
        LogLevel.INFO:    "#30d158",
        LogLevel.WARN:    "#ff9f0a",
        LogLevel.ERROR:   "#ff453a",
        LogLevel.FATAL:   "#bf5af2",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logcat = AppLogcat.instance()
        self.is_paused = False
        self._min_level = LogLevel.VERBOSE
        self._tag_filter = ""
        self._search_text = ""

        self.setWindowTitle("🛠️ FileManagerPro — Live Diagnostic Logcat (F12)")
        self.setMinimumSize(960, 580)
        self.resize(1120, 680)

        self._build_ui()
        self._load_history()
        self._connect_signals()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        # ── Control & Filter Toolbar ──
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(8)

        # Level filter
        ctrl_bar.addWidget(QLabel("Mức log:"))
        self.combo_level = QComboBox()
        self.combo_level.addItems([
            "1. Verbose (V)",
            "2. Debug (D)",
            "3. Info (I)",
            "4. Warn (W)",
            "5. Error (E)",
            "6. Fatal (F)",
        ])
        self.combo_level.currentIndexChanged.connect(self._on_level_changed)
        ctrl_bar.addWidget(self.combo_level)

        # Tag filter
        ctrl_bar.addWidget(QLabel("Tag:"))
        self.edit_tag = QLineEdit()
        self.edit_tag.setPlaceholderText("Lọc tag (vd: UI:Click, CORE:Metadata)...")
        self.edit_tag.setFixedWidth(180)
        self.edit_tag.textChanged.connect(self._on_tag_changed)
        ctrl_bar.addWidget(self.edit_tag)

        # Search query
        ctrl_bar.addWidget(QLabel("Tìm kiếm:"))
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("Từ khóa nội dung...")
        self.edit_search.setFixedWidth(200)
        self.edit_search.textChanged.connect(self._on_search_changed)
        ctrl_bar.addWidget(self.edit_search)

        # Auto scroll checkbox
        self.chk_autoscroll = QCheckBox("Tự cuộn")
        self.chk_autoscroll.setChecked(True)
        ctrl_bar.addWidget(self.chk_autoscroll)

        ctrl_bar.addStretch()

        # Pause button
        self.btn_pause = QPushButton("⏸ Tạm dừng")
        self.btn_pause.setFixedWidth(90)
        self.btn_pause.clicked.connect(self._toggle_pause)
        ctrl_bar.addWidget(self.btn_pause)

        # Clear button
        btn_clear = QPushButton("🗑 Xóa màn")
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._clear_view)
        ctrl_bar.addWidget(btn_clear)

        # Export button
        btn_export = QPushButton("💾 Xuất file")
        btn_export.setFixedWidth(80)
        btn_export.clicked.connect(self._export_logs)
        ctrl_bar.addWidget(btn_export)

        root_layout.addLayout(ctrl_bar)

        # ── Main Log Display Box ──
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Cascadia Code", 9) if QFont("Cascadia Code").exactMatch() else QFont("Consolas", 9.5))
        self.log_text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1a1a1c;
                color: #e5e5ea;
                border: 1px solid #3a3a3c;
                border-radius: 6px;
                padding: 6px;
                line-height: 1.35;
            }
        """)
        root_layout.addWidget(self.log_text)

        # ── Status Footer ──
        footer = QHBoxLayout()
        self.lbl_status = QLabel(f"File log: {self.logcat.log_file_path.name}")
        self.lbl_status.setStyleSheet("color: #8e8e93; font-size: 8pt;")
        footer.addWidget(self.lbl_status)
        footer.addStretch()

        lbl_hint = QLabel("Phím tắt: F12 để đóng/mở • Đỏ: Error/Freeze • Vàng: Warn • Xanh: Info")
        lbl_hint.setStyleSheet("color: #636366; font-size: 8pt;")
        footer.addWidget(lbl_hint)
        root_layout.addLayout(footer)

        # Shortcut to close with Esc or F12
        QShortcut(QKeySequence("F12"), self, activated=self.accept)
        QShortcut(QKeySequence("Esc"), self, activated=self.accept)

    def _connect_signals(self):
        self.logcat.new_log_record.connect(self._append_record)

    def _load_history(self):
        self.log_text.clear()
        records = self.logcat.get_recent_records()
        for rec in records:
            if self._matches_filter(rec):
                self._render_record(rec)

    def _matches_filter(self, rec: LogRecord) -> bool:
        if rec.level < self._min_level:
            return False
        if self._tag_filter and self._tag_filter.lower() not in rec.tag.lower():
            return False
        if self._search_text and self._search_text.lower() not in rec.message.lower():
            return False
        return True

    def _render_record(self, rec: LogRecord):
        color = self.LEVEL_COLORS.get(rec.level, "#e5e5ea")
        time_str = rec.timestamp.strftime("%H:%M:%S.%f")[:-3]
        thread_label = "Main" if rec.is_main_thread else rec.thread_name
        
        # HTML formatting with color-coded badges
        html = (
            f"<span style='color: #636366;'>{time_str}</span> "
            f"<b style='color: {color};'>[{rec.level.short_name}]</b> "
            f"<span style='color: #a1a1a6;'>[{thread_label:^6}]</span> "
            f"<b style='color: #0a84ff;'>[{rec.tag}]</b> "
            f"<span style='color: {color};'>{rec.message}</span>"
        )
        self.log_text.appendHtml(html)

    @pyqtSlot(object)
    def _append_record(self, rec: LogRecord):
        if self.is_paused:
            return
        if self._matches_filter(rec):
            self._render_record(rec)
            if self.chk_autoscroll.isChecked():
                self.log_text.moveCursor(QTextCursor.MoveOperation.End)

    def _on_level_changed(self, idx: int):
        self._min_level = LogLevel(idx + 1)
        self._load_history()

    def _on_tag_changed(self, text: str):
        self._tag_filter = text.strip()
        self._load_history()

    def _on_search_changed(self, text: str):
        self._search_text = text.strip()
        self._load_history()

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        self.btn_pause.setText("▶ Tiếp tục" if self.is_paused else "⏸ Tạm dừng")
        self.btn_pause.setStyleSheet("color: #30d158;" if self.is_paused else "")

    def _clear_view(self):
        self.log_text.clear()

    def _export_logs(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "Lưu file log", f"logcat_{Path(self.logcat.log_file_path).stem}.txt", "Text Files (*.txt);;All Files (*)"
        )
        if p:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(self.log_text.toPlainText())
                QMessageBox.information(self, "Thông báo", f"Đã xuất log thành công ra:\n{p}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể lưu file: {e}")
