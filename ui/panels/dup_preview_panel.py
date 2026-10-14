"""
ui/panels/dup_preview_panel.py
Duplicate Group Preview Panel.
Shows all files in each duplicate group as thumbnail grids with action buttons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt, QSize, pyqtSignal
from PyQt6.QtGui   import QPixmap, QFont, QColor, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QToolButton, QSpacerItem,
    QButtonGroup,
)


from duplicate.dup_manager import DupFileItem, DupGroup
from ui.widgets.progress_dialog import TaskProgressDialog
from ui.theme import style, tok


class ThumbnailCard(QFrame):
    """A single file thumbnail card within a duplicate group."""

    action_changed = pyqtSignal(Path, str)   # (path, action)

    THUMB_W = 130
    THUMB_H = 110

    def __init__(self, item: DupFileItem, parent=None):
        super().__init__(parent)
        self.item = item
        self._current_action = item.action
        self.setObjectName("thumbFrame")
        self.setFixedWidth(self.THUMB_W + 20)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # ── Thumbnail image ──
        self.thumb_lbl = QLabel()
        self.thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_lbl.setFixedSize(self.THUMB_W, self.THUMB_H)
        style(self.thumb_lbl, 
            "background: @bg_base; border-radius: 6px; color: @text_tertiary; font-size: 8pt;"
        )
        self._load_thumb()
        layout.addWidget(self.thumb_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        # ── Badges row ──
        badge_row = QHBoxLayout()
        badge_row.setSpacing(4)

        engine_badge = QLabel(self.item.engine)
        engine_badge.setObjectName("badgePHash" if self.item.engine == "pHash" else "badgeDINO")
        badge_row.addWidget(engine_badge)

        sim_pct = int(self.item.similarity * 100)
        sim_badge = QLabel(f"{sim_pct}%")
        sim_badge.setObjectName("badgeSimilarity")
        badge_row.addWidget(sim_badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)

        # ── File name ──
        name_lbl = QLabel(self.item.path.name)
        name_lbl.setWordWrap(True)
        name_lbl.setMaximumWidth(self.THUMB_W + 8)
        style(name_lbl, "color: @text_secondary; font-size: 8pt;")
        name_lbl.setToolTip(str(self.item.path))
        layout.addWidget(name_lbl)

        # ── Size / date ──
        if self.item.size_bytes:
            sz = self.item.size_bytes
            sz_str = f"{sz/1024:.1f} KB" if sz < 1048576 else f"{sz/1048576:.2f} MB"
        else:
            sz_str = ""
        res = f"{self.item.width}×{self.item.height}" if self.item.width else ""
        meta_str = "  ".join(filter(None, [res, sz_str, self.item.created or ""]))
        meta_lbl = QLabel(meta_str)
        style(meta_lbl, "color: @text_tertiary; font-size: 7.5pt;")
        meta_lbl.setWordWrap(True)
        layout.addWidget(meta_lbl)

        # ── Action buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.btn_keep   = QPushButton("✔ Giữ")
        self.btn_delete = QPushButton("✖ Xóa")
        self.btn_keep.setObjectName("btnKeep")
        self.btn_delete.setObjectName("btnDanger")

        for btn in (self.btn_keep, self.btn_delete):
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                btn.styleSheet() +
                "font-size: 8pt; padding: 2px 6px; border-radius: 5px;"
            )

        self.btn_keep.clicked.connect(lambda: self._set_action("keep"))
        self.btn_delete.clicked.connect(lambda: self._set_action("delete"))

        btn_row.addWidget(self.btn_keep)
        btn_row.addWidget(self.btn_delete)
        layout.addLayout(btn_row)

    def _load_thumb(self):
        """Load thumbnail safely from memory buffer without holding file locks."""
        try:
            with open(self.item.path, "rb") as f:
                data = f.read()
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                scaled = pix.scaled(
                    self.THUMB_W, self.THUMB_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb_lbl.setPixmap(scaled)
                return
        except Exception:
            pass
        # Fallback icon for video / other
        ext = self.item.path.suffix.lower()
        icon = "🎬" if ext in {".mp4", ".avi", ".mkv", ".mov", ".webm"} else "📄"
        self.thumb_lbl.setText(f"{icon}\n{self.item.path.suffix}")

    def _set_action(self, action: str):
        self._current_action = action
        self.item.action = action
        # Update border color
        if action == "keep":
            self.setObjectName("thumbFrameKeep")
        elif action == "delete":
            self.setObjectName("thumbFrameDelete")
        else:
            self.setObjectName("thumbFrame")
        # Re-apply stylesheet
        self.style().unpolish(self)
        self.style().polish(self)
        self.action_changed.emit(self.item.path, action)

    def mark_auto_keep(self):
        self._set_action("keep")


class DupGroupWidget(QFrame):
    """Collapsible widget showing one duplicate group with all its thumbnails."""

    def __init__(self, group: DupGroup, parent=None):
        super().__init__(parent)
        self.group = group
        self.setObjectName("dupGroupFrame")
        self._build_ui()

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 8, 10, 8)
        self.main_layout.setSpacing(8)

        # ── Header row ──
        hdr = QHBoxLayout()

        title = QLabel(
            f"<b>Nhóm #{self.group.group_id}</b>  "
            f"<span style='color:{tok('text_secondary')};font-size:8.5pt;'>"
            f"{len(self.group.files)} file trùng lặp</span>"
        )
        hdr.addWidget(title)
        hdr.addStretch()

        self.collapse_btn = QToolButton()
        self.collapse_btn.setText("▾")
        style(self.collapse_btn, 
            "background: transparent; border: none; color: @text_secondary; font-size: 10.5pt;"
        )
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        hdr.addWidget(self.collapse_btn)

        self.main_layout.addLayout(hdr)

        # ── Thumbnails area ──
        self.thumbs_widget = QWidget()
        thumbs_layout = QHBoxLayout(self.thumbs_widget)
        thumbs_layout.setContentsMargins(0, 0, 0, 0)
        thumbs_layout.setSpacing(8)
        thumbs_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        best_idx = self._find_best_file()
        for i, file_item in enumerate(self.group.files):
            card = ThumbnailCard(file_item)
            if i == best_idx:
                card.mark_auto_keep()
            thumbs_layout.addWidget(card)

        thumbs_layout.addStretch()
        self.main_layout.addWidget(self.thumbs_widget)

        # ── Summary footer ──
        total_size = sum(f.size_bytes for f in self.group.files)
        sz_mb = total_size / 1048576
        footer = QLabel(
            f"<span style='color:{tok('text_tertiary')};font-size:8pt;'>"
            f"Tổng dung lượng nhóm: {sz_mb:.2f} MB</span>"
        )
        self.main_layout.addWidget(footer)

    def _find_best_file(self) -> int:
        """Find index of file to auto-mark as Keep (highest resolution)."""
        best = 0
        best_px = 0
        for i, f in enumerate(self.group.files):
            px = f.width * f.height
            if px > best_px:
                best_px = px
                best = i
        return best

    def _toggle_collapse(self):
        self.group.collapsed = not self.group.collapsed
        self.thumbs_widget.setVisible(not self.group.collapsed)
        self.collapse_btn.setText("▸" if self.group.collapsed else "▾")


class DupPreviewPanel(QWidget):
    """
    Full Duplicate Preview Panel.
    Shows all duplicate groups in a scrollable list.
    Each group shows all files with thumbnails, similarity badges, and action buttons.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: list[DupGroup] = []
        self._thread = None
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top bar ──
        top_bar = QWidget()
        style(top_bar, 
            "background: @fill_hover; border-bottom: 1px solid @stroke_control;"
        )
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)

        # Summary stats
        self.lbl_summary = QLabel("Chưa quét. Nhấn 'Bắt đầu quét' để tìm file trùng lặp.")
        style(self.lbl_summary, "color: @text_secondary; font-size: 9pt;")
        top_layout.addWidget(self.lbl_summary)
        top_layout.addStretch()

        # Engine selector
        from PyQt6.QtWidgets import QComboBox
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["pHash (Nhanh)", "DINOv2 (Chính xác)", "Cả hai"])
        self.engine_combo.setFixedWidth(160)
        top_layout.addWidget(QLabel("Engine:"))
        top_layout.addWidget(self.engine_combo)

        # Scan button
        self.btn_scan = QPushButton("🔍  Bắt đầu quét")
        self.btn_scan.setObjectName("btnPrimary")
        self.btn_scan.setFixedWidth(140)
        top_layout.addWidget(self.btn_scan)

        # Apply actions button
        self.btn_apply = QPushButton("🗑️  Áp dụng Xóa")
        self.btn_apply.setObjectName("btnDanger")
        self.btn_apply.setFixedWidth(120)
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._on_apply_actions)
        top_layout.addWidget(self.btn_apply)

        layout.addWidget(top_bar)

        # ── Scrollable groups area ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(12, 12, 12, 12)
        self.groups_layout.setSpacing(12)
        self.groups_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Placeholder when no scan done
        self.placeholder = QLabel(
            "🔍\n\nChưa có kết quả quét.\n"
            "Chọn thư mục và nhấn 'Bắt đầu quét'."
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style(self.placeholder, "color: @text_tertiary; font-size: 10.5pt;")
        self.groups_layout.addWidget(self.placeholder)

        scroll.setWidget(self.groups_container)
        layout.addWidget(scroll)

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    def load_groups(self, groups: list[DupGroup]):
        """Populate the panel with duplicate groups from the engine."""
        self._groups = groups
        self._clear_groups()

        if not groups:
            self.placeholder.show()
            self.lbl_summary.setText("Không tìm thấy file trùng lặp.")
            self.btn_apply.setEnabled(False)
            return

        self.placeholder.hide()
        total_files = sum(len(g.files) for g in groups)
        self.lbl_summary.setText(
            f"Tìm thấy <b>{len(groups)}</b> nhóm — "
            f"<b>{total_files}</b> file trùng lặp"
        )

        for group in groups:
            widget = DupGroupWidget(group)
            self.groups_layout.addWidget(widget)

        self.btn_apply.setEnabled(True)

    def show_progress(self, current: int, total: int):
        """No-op kept for backwards compatibility; progress is handled by TaskProgressDialog."""
        pass

    def _on_apply_actions(self):
        """Execute deletion of all files marked as 'delete'."""
        from PyQt6.QtWidgets import QMessageBox
        from core.workers import DupDeleteWorker
        from PyQt6.QtCore import QThread

        to_delete = []
        total_bytes = 0
        for group in self._groups:
            for item in group.files:
                if item.action == "delete":
                    to_delete.append(item.path)
                    total_bytes += item.size_bytes

        if not to_delete:
            QMessageBox.information(
                self, "Thông báo",
                "Chưa có file nào được đánh dấu '✖ Xóa'.\n"
                "Vui lòng nhấn nút '✖ Xóa' dưới các file bạn muốn bỏ."
            )
            return

        sz_mb = total_bytes / 1048576
        reply = QMessageBox.question(
            self, "Xác nhận xóa file trùng lặp",
            f"Chuyển {len(to_delete)} file trùng lặp vào Thùng rác (Recycle Bin)?\n\n"
            f"Dung lượng ước tính giải phóng: {sz_mb:.2f} MB\n"
            f"(Bạn vẫn có thể khôi phục lại từ Recycle Bin nếu cần).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.btn_apply.setEnabled(False)
        self.btn_scan.setEnabled(False)

        # Standardized Modal Progress Dialog with Cancel button
        self._progress_dlg = TaskProgressDialog("Đang xóa file trùng lặp...", parent=self.window())
        self._progress_dlg.set_task("Đang đưa file trùng lặp vào Thùng rác...", total=len(to_delete), icon="🗑")

        self._worker = DupDeleteWorker(to_delete)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)

        self._progress_dlg.attach_worker(self._worker)
        self._progress_dlg.cancelled.connect(self._worker.cancel, Qt.ConnectionType.DirectConnection)
        self._worker.progress.connect(self._progress_dlg.update_progress)
        self._worker.finished.connect(self._on_delete_finished)
        self._worker.cancelled.connect(self._on_delete_cancelled)
        self._worker.error.connect(self._on_delete_error)

        self._progress_dlg.show_centered()
        self._thread.start()

    def _on_delete_finished(self, results: list):
        from PyQt6.QtWidgets import QMessageBox
        if self._thread:
            self._thread.quit()
            self._thread.wait(300)
            self._thread = None

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.finish_task("Đã hoàn tất xóa file!")

        self.btn_scan.setEnabled(True)
        self.btn_apply.setEnabled(True)

        deleted_paths = {r["path"] for r in results if r["success"]}

        # Update groups model: remove deleted files
        updated_groups = []
        for g in self._groups:
            remaining_files = [f for f in g.files if f.path not in deleted_paths]
            if len(remaining_files) > 1:
                g.files = remaining_files
                updated_groups.append(g)

        self.load_groups(updated_groups)

        ok_count = len(deleted_paths)
        fail_count = len(results) - ok_count
        msg = f"Đã chuyển {ok_count} file trùng lặp vào Thùng rác."
        if fail_count > 0:
            msg += f"\n({fail_count} file gặp lỗi không thể xóa)."

        QMessageBox.information(self, "Hoàn tất xóa trùng lặp", msg)

    def _on_delete_cancelled(self):
        from PyQt6.QtWidgets import QMessageBox
        if self._thread:
            self._thread.quit()
            self._thread.wait(300)
            self._thread = None

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.cancel_task("Đã dừng xóa file.")

        self.btn_scan.setEnabled(True)
        self.btn_apply.setEnabled(True)
        QMessageBox.information(self, "Đã hủy", "Đã dừng thao tác xóa file trùng lặp.")

    def _on_delete_error(self, err_msg: str):
        from PyQt6.QtWidgets import QMessageBox
        if self._thread:
            self._thread.quit()
            self._thread.wait(300)
            self._thread = None

        if hasattr(self, "_progress_dlg") and self._progress_dlg:
            self._progress_dlg.reject()

        self.btn_scan.setEnabled(True)
        self.btn_apply.setEnabled(True)
        QMessageBox.critical(self, "Lỗi", err_msg)

    # ─────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────

    def _clear_groups(self):
        """Remove all group widgets."""
        while self.groups_layout.count() > 1:   # keep placeholder at index 0
            item = self.groups_layout.takeAt(1)
            if item and item.widget():
                item.widget().deleteLater()
