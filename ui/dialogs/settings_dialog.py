"""
ui/dialogs/settings_dialog.py
Settings dialog for configuring application preferences, thresholds, and performance.
Saves to config/settings.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore  import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QSlider, QCheckBox,
    QGroupBox, QTabWidget, QWidget, QFileDialog, QMessageBox,
    QRadioButton, QButtonGroup,
)

from utils.cuda_helper import get_cuda_info, cuda_available
from utils.file_utils import get_app_dir
from core.background_manager import (
    load_appearance_settings, save_appearance_settings,
    import_background_file, resolve_background_file,
    IMAGE_BG_EXTS, VIDEO_BG_EXTS,
)
from ui.theme import style


SETTINGS_PATH = get_app_dir() / "config" / "settings.json"


def load_settings() -> dict:
    """Load settings from JSON file with defaults."""
    defaults = {
        "rename": {
            "default_date_format": "DDMMYY",
            "collision_digits": 3,
            "sanitize_spaces": True,
            "strip_metadata_on_rename": False,
        },
        "duplicate": {
            "default_engine": "both",
            "phash_threshold": 10,
            "embedding_threshold": 0.95,
            "dinov2_model": "dinov2_vits14",
            "batch_size": 128,
        },
        "performance": {
            "scanner_workers": 8,
            "use_cuda": True,
        },
        "tools": {
            "exiftool_path": "exiftool.exe",
        },
        "appearance": {
            "theme": "system",
            "blur_enabled": False,
            "background_type": "none",
            "background_file": "",
            "overlay_opacity": 0.82,
        }
    }
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            # Merge
            for k, v in user_cfg.items():
                if isinstance(v, dict) and k in defaults:
                    defaults[k].update(v)
                else:
                    defaults[k] = v
        except Exception:
            pass
    return defaults


# Sections this dialog edits; anything else in the file (e.g. Quick access pins under
# "navigation") belongs to other parts of the app and is left as it is on disk.
OWNED_SECTIONS = ("rename", "duplicate", "performance", "tools", "appearance", "general")


def save_settings(cfg: dict) -> bool:
    """Write this dialog's sections to settings.json atomically, keeping all other keys."""
    try:
        from utils.settings_store import update_settings
        update_settings(lambda disk: disk.update({k: cfg[k] for k in OWNED_SECTIONS if k in cfg}),
                        SETTINGS_PATH)
        return True
    except Exception:
        return False


class SettingsDialog(QDialog):
    """
    Application Settings Dialog.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt hệ thống")
        self.setMinimumSize(640, 480)
        self.cfg = load_settings()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ── Tab 1: Đổi tên (Rename) ──
        tab_rename = QWidget()
        r_layout = QVBoxLayout(tab_rename)

        g_rename = QGroupBox("Quy tắc đổi tên mặc định")
        gr_layout = QVBoxLayout(g_rename)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Định dạng ngày mặc định:"))
        self.combo_date_fmt = QComboBox()
        self.combo_date_fmt.addItems(["DDMMYY", "DDMMYYYY", "YYYYMMDD", "MMDDYY"])
        row1.addWidget(self.combo_date_fmt)
        gr_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Số chữ số hậu tố khi trùng tên (_001):"))
        self.spin_digits = QSpinBox()
        self.spin_digits.setRange(2, 6)
        row2.addWidget(self.spin_digits)
        gr_layout.addLayout(row2)

        self.chk_sanitize = QCheckBox("Tự động chuẩn hóa khoảng trắng & ký tự đặc biệt")
        gr_layout.addWidget(self.chk_sanitize)

        r_layout.addWidget(g_rename)
        r_layout.addStretch()
        self.tabs.addTab(tab_rename, "✏️ Đổi tên")

        # ── Tab 2: Trùng lặp (Duplicates & AI) ──
        tab_dup = QWidget()
        d_layout = QVBoxLayout(tab_dup)

        g_dup = QGroupBox("Cấu hình AI & Perceptual Hash")
        gd_layout = QVBoxLayout(g_dup)

        d_row1 = QHBoxLayout()
        d_row1.addWidget(QLabel("Engine mặc định:"))
        self.combo_dup_engine = QComboBox()
        self.combo_dup_engine.addItems(["Cả hai (Khuyên dùng)", "pHash (Nhanh)", "DINOv2 (Chính xác)"])
        d_row1.addWidget(self.combo_dup_engine)
        gd_layout.addLayout(d_row1)

        d_row2 = QHBoxLayout()
        d_row2.addWidget(QLabel("Ngưỡng pHash (Hamming distance):"))
        self.spin_phash = QSpinBox()
        self.spin_phash.setRange(1, 30)
        self.spin_phash.setToolTip("Càng nhỏ càng khắt khe (10 là tiêu chuẩn)")
        d_row2.addWidget(self.spin_phash)
        gd_layout.addLayout(d_row2)

        d_row3 = QHBoxLayout()
        d_row3.addWidget(QLabel("Ngưỡng tương đồng DINOv2 (%):"))
        self.spin_dino_thresh = QSpinBox()
        self.spin_dino_thresh.setRange(70, 99)
        self.spin_dino_thresh.setToolTip("Ví dụ 95% = 0.95 Cosine similarity")
        d_row3.addWidget(self.spin_dino_thresh)
        gd_layout.addLayout(d_row3)

        d_row4 = QHBoxLayout()
        d_row4.addWidget(QLabel("Mô hình DINOv2:"))
        self.combo_dino_model = QComboBox()
        self.combo_dino_model.addItems(["dinov2_vits14 (Nhẹ, nhanh)", "dinov2_vitb14 (Tiêu chuẩn)", "dinov2_vitl14 (Lớn)"])
        d_row4.addWidget(self.combo_dino_model)
        gd_layout.addLayout(d_row4)

        d_layout.addWidget(g_dup)
        d_layout.addStretch()
        self.tabs.addTab(tab_dup, "🔍 Trùng lặp & AI")

        # ── Tab 3: Hiệu năng & Phần cứng ──
        tab_perf = QWidget()
        p_layout = QVBoxLayout(tab_perf)

        g_perf = QGroupBox("Xử lý đa luồng & GPU")
        gp_layout = QVBoxLayout(g_perf)

        p_row1 = QHBoxLayout()
        p_row1.addWidget(QLabel("Số luồng quét thư mục (Workers):"))
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 32)
        p_row1.addWidget(self.spin_workers)
        gp_layout.addLayout(p_row1)

        self.chk_cuda = QCheckBox("Kích hoạt tăng tốc NVIDIA CUDA")
        gp_layout.addWidget(self.chk_cuda)

        # GPU Info label
        cuda_str = str(get_cuda_info())
        self.lbl_gpu = QLabel(f"<b>GPU hiện tại:</b> {cuda_str}")
        style(self.lbl_gpu, "color: @success; font-size: 11px;")
        gp_layout.addWidget(self.lbl_gpu)

        p_layout.addWidget(g_perf)

        # Tools group
        g_tools = QGroupBox("Đường dẫn công cụ hệ thống")
        gt_layout = QHBoxLayout(g_tools)
        gt_layout.addWidget(QLabel("ExifTool:"))
        self.edit_exiftool = QLineEdit()
        gt_layout.addWidget(self.edit_exiftool)
        btn_browse_exif = QPushButton("📁")
        btn_browse_exif.setFixedWidth(32)
        btn_browse_exif.clicked.connect(self._browse_exiftool)
        gt_layout.addWidget(btn_browse_exif)

        p_layout.addWidget(g_tools)
        p_layout.addStretch()
        self.tabs.addTab(tab_perf, "⚡ Hiệu năng & GPU")

        # ── Tab 4: Giao diện & Hiệu ứng (Aesthetics, Blur & Wallpaper) ──
        tab_appr = QWidget()
        a_layout = QVBoxLayout(tab_appr)
        a_layout.setSpacing(10)

        # 0. Color theme (like Windows Settings > Personalization > Colors)
        g_theme = QGroupBox("Chủ đề màu")
        gt_layout = QHBoxLayout(g_theme)
        gt_layout.addWidget(QLabel("Chế độ:"))
        self.combo_theme = QComboBox()
        for label, value in (("Theo hệ thống Windows", "system"), ("Sáng", "light"), ("Tối", "dark")):
            self.combo_theme.addItem(label, value)
        gt_layout.addWidget(self.combo_theme)
        gt_layout.addStretch()
        a_layout.addWidget(g_theme)

        # 1. Mode Selection Group
        g_mode = QGroupBox("Chế độ hình nền ứng dụng")
        gm_layout = QVBoxLayout(g_mode)
        gm_layout.setSpacing(8)

        self.btn_group_mode = QButtonGroup(self)

        self.radio_mode_default = QRadioButton("Nền mặc định (Giao diện chuẩn theo Windows, hiệu năng cao nhất)")
        self.radio_mode_blur = QRadioButton("Nền Blur & Trong suốt (Windows Acrylic / Pure Glass nhìn xuyên Desktop)")
        self.radio_mode_custom = QRadioButton("Nền Tùy chỉnh (Ảnh tĩnh & Video động Live Wallpaper)")

        self.btn_group_mode.addButton(self.radio_mode_default, 0)
        self.btn_group_mode.addButton(self.radio_mode_blur, 1)
        self.btn_group_mode.addButton(self.radio_mode_custom, 2)

        gm_layout.addWidget(self.radio_mode_default)
        gm_layout.addWidget(self.radio_mode_blur)
        gm_layout.addWidget(self.radio_mode_custom)
        a_layout.addWidget(g_mode)

        # 2. Windows Acrylic Blur Behind Options
        self.g_blur = QGroupBox("Tùy chỉnh Nền Blur & Độ trong suốt (Acrylic Glass)")
        gb_layout = QVBoxLayout(self.g_blur)

        lbl_blur_hint = QLabel(
            "💡 <b>Tính năng làm mờ & trong suốt:</b> Cho phép bạn nhìn xuyên qua ứng dụng xuống màn hình Desktop "
            "hoặc các cửa sổ phía sau. Kéo thanh trượt để chuyển từ chế độ <b>Trong suốt hoàn toàn (0%)</b> "
            "đến <b>Kính mờ đục (100%)</b>."
        )
        style(lbl_blur_hint, "color: @text_secondary; font-size: 8.5pt;")
        lbl_blur_hint.setWordWrap(True)
        gb_layout.addWidget(lbl_blur_hint)

        b_row = QHBoxLayout()
        b_row.addWidget(QLabel("Độ mờ / Độ trong suốt:"))
        self.slider_blur = QSlider(Qt.Orientation.Horizontal)
        self.slider_blur.setRange(0, 100)
        self.slider_blur.setValue(50)
        self.lbl_blur_val = QLabel("50% (Kính mờ tiêu chuẩn)")
        style(self.lbl_blur_val, "color: @accent; font-weight: 600; font-size: 8.5pt;")
        self.lbl_blur_val.setMinimumWidth(260)
        self.slider_blur.valueChanged.connect(self._on_blur_slider_changed)

        b_row.addWidget(self.slider_blur)
        b_row.addWidget(self.lbl_blur_val)
        gb_layout.addLayout(b_row)

        a_layout.addWidget(self.g_blur)

        # 3. Custom Wallpaper Options
        self.g_wall = QGroupBox("Tùy chỉnh Hình nền (Ảnh tĩnh & Video động)")
        gw_layout = QVBoxLayout(self.g_wall)

        w_row1 = QHBoxLayout()
        w_row1.addWidget(QLabel("Định dạng hình nền:"))
        self.combo_bg_type = QComboBox()
        self.combo_bg_type.addItems([
            "Ảnh tĩnh (JPG, PNG, WebP, BMP, GIF)",
            "Video động Live Wallpaper (MP4, WebM, AVI, MOV)"
        ])
        self.combo_bg_type.currentIndexChanged.connect(self._on_bg_type_changed)
        w_row1.addWidget(self.combo_bg_type)
        gw_layout.addLayout(w_row1)

        w_row2 = QHBoxLayout()
        w_row2.addWidget(QLabel("Tệp hình nền:"))
        self.edit_bg_file = QLineEdit()
        self.edit_bg_file.setPlaceholderText("Chưa chọn tệp hình nền...")
        self.edit_bg_file.setReadOnly(True)
        w_row2.addWidget(self.edit_bg_file)

        self.btn_browse_bg = QPushButton("📁 Chọn tệp...")
        self.btn_browse_bg.clicked.connect(self._browse_bg_file)
        w_row2.addWidget(self.btn_browse_bg)

        self.btn_clear_bg = QPushButton("↺ Xóa nền")
        self.btn_clear_bg.clicked.connect(self._clear_bg_file)
        w_row2.addWidget(self.btn_clear_bg)
        gw_layout.addLayout(w_row2)

        lbl_persist_note = QLabel(
            "🛡️ <b>Bộ nhớ ứng dụng an toàn:</b> Tệp được chọn sẽ tự động được sao chép vào "
            "phân vùng dữ liệu nội bộ của ứng dụng (assets/background/) để dù tệp gốc ngoài máy bị di chuyển "
            "hoặc xóa thì tính năng hình nền vẫn hoạt động vĩnh viễn!"
        )
        lbl_persist_note.setWordWrap(True)
        style(lbl_persist_note, "color: @success; font-size: 8.5pt; padding: 6px; background: @success_bg; border-radius: 4px;")
        gw_layout.addWidget(lbl_persist_note)

        # Opacity slider
        w_row3 = QHBoxLayout()
        w_row3.addWidget(QLabel("Độ tối lớp phủ bảo vệ chữ:"))
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(10, 95)
        self.slider_opacity.setValue(82)
        self.lbl_opacity_val = QLabel("82%")
        self.lbl_opacity_val.setFixedWidth(40)
        self.slider_opacity.valueChanged.connect(lambda v: self.lbl_opacity_val.setText(f"{v}%"))
        w_row3.addWidget(self.slider_opacity)
        w_row3.addWidget(self.lbl_opacity_val)
        gw_layout.addLayout(w_row3)

        a_layout.addWidget(self.g_wall)
        a_layout.addStretch()

        # Connect radio buttons to toggle options
        self.radio_mode_default.toggled.connect(self._update_mode_ui_state)
        self.radio_mode_blur.toggled.connect(self._update_mode_ui_state)
        self.radio_mode_custom.toggled.connect(self._update_mode_ui_state)

        self.tabs.addTab(tab_appr, "🎨 Giao diện & Hiệu ứng")

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("💾  Lưu cài đặt")
        btn_save.setObjectName("btnPrimary")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _on_blur_slider_changed(self, val: int):
        if val == 0:
            text = "0% (Trong suốt hoàn toàn - Pure Glass)"
        elif val <= 30:
            text = f"{val}% (Trong suốt cao - Nhìn xuyên thấu)"
        elif val <= 70:
            text = f"{val}% (Kính mờ tiêu chuẩn - Cân bằng)"
        else:
            text = f"{val}% (Mờ đục / Frosted Glass đậm)"
        self.lbl_blur_val.setText(text)

    def _update_mode_ui_state(self):
        is_blur = self.radio_mode_blur.isChecked()
        is_custom = self.radio_mode_custom.isChecked()

        self.g_blur.setEnabled(is_blur)
        self.g_wall.setEnabled(is_custom)

    def _load_values(self):
        r = self.cfg.get("rename", {})
        self.combo_date_fmt.setCurrentText(r.get("default_date_format", "DDMMYY"))
        self.spin_digits.setValue(r.get("collision_digits", 3))
        self.chk_sanitize.setChecked(r.get("sanitize_spaces", True))

        d = self.cfg.get("duplicate", {})
        eng_map = {"both": 0, "phash": 1, "dinov2": 2}
        self.combo_dup_engine.setCurrentIndex(eng_map.get(d.get("default_engine", "both"), 0))
        self.spin_phash.setValue(d.get("phash_threshold", 10))
        self.spin_dino_thresh.setValue(int(d.get("embedding_threshold", 0.95) * 100))

        p = self.cfg.get("performance", {})
        self.spin_workers.setValue(p.get("scanner_workers", 8))
        self.chk_cuda.setChecked(p.get("use_cuda", True) and cuda_available())

        t = self.cfg.get("tools", {})
        self.edit_exiftool.setText(t.get("exiftool_path", "exiftool.exe"))

        # Appearance settings
        a = self.cfg.get("appearance", {})
        idx = self.combo_theme.findData(a.get("theme", "system"))
        self.combo_theme.setCurrentIndex(idx if idx >= 0 else 0)
        mode = a.get("background_mode", "default")
        if mode == "blur":
            self.radio_mode_blur.setChecked(True)
        elif mode == "custom":
            self.radio_mode_custom.setChecked(True)
        else:
            self.radio_mode_default.setChecked(True)

        try:
            blur_val = int(float(a.get("blur_opacity", 50)))
        except (ValueError, TypeError):
            blur_val = 50
        self.slider_blur.setValue(max(0, min(100, blur_val)))
        self._on_blur_slider_changed(self.slider_blur.value())

        bg_type = a.get("background_type", "image")
        self.combo_bg_type.setCurrentIndex(1 if bg_type == "video" else 0)

        self.edit_bg_file.setText(a.get("background_file", ""))
        self._selected_raw_bg_file: Optional[Path] = None

        op_pct = int(a.get("overlay_opacity", 0.82) * 100)
        self.slider_opacity.setValue(max(10, min(95, op_pct)))
        self.lbl_opacity_val.setText(f"{self.slider_opacity.value()}%")

        self._update_mode_ui_state()

    def _on_bg_type_changed(self, index: int):
        pass

    def _browse_bg_file(self):
        idx = self.combo_bg_type.currentIndex()
        if idx == 0:
            filt = "Image Files (*.jpg *.jpeg *.png *.webp *.bmp *.gif);;All Files (*)"
        else:
            filt = "Video Files (*.mp4 *.webm *.avi *.mov *.mkv);;All Files (*)"

        p, _ = QFileDialog.getOpenFileName(self, "Chọn tệp hình nền", "", filt)
        if p:
            src = Path(p)
            self._selected_raw_bg_file = src
            self.edit_bg_file.setText(str(src))
            if src.suffix.lower() in VIDEO_BG_EXTS and self.combo_bg_type.currentIndex() != 1:
                self.combo_bg_type.setCurrentIndex(1)
            elif src.suffix.lower() in IMAGE_BG_EXTS and self.combo_bg_type.currentIndex() != 0:
                self.combo_bg_type.setCurrentIndex(0)

    def _clear_bg_file(self):
        self._selected_raw_bg_file = None
        self.edit_bg_file.setText("")

    def _browse_exiftool(self):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn exiftool.exe", "", "Executable (*.exe);;All Files (*)")
        if p:
            self.edit_exiftool.setText(p)

    def _save(self):
        eng_list = ["both", "phash", "dinov2"]
        model_list = ["dinov2_vits14", "dinov2_vitb14", "dinov2_vitl14"]

        self.cfg["rename"]["default_date_format"] = self.combo_date_fmt.currentText()
        self.cfg["rename"]["collision_digits"] = self.spin_digits.value()
        self.cfg["rename"]["sanitize_spaces"] = self.chk_sanitize.isChecked()

        self.cfg["duplicate"]["default_engine"] = eng_list[self.combo_dup_engine.currentIndex()]
        self.cfg["duplicate"]["phash_threshold"] = self.spin_phash.value()
        self.cfg["duplicate"]["embedding_threshold"] = self.spin_dino_thresh.value() / 100.0
        self.cfg["duplicate"]["dinov2_model"] = model_list[self.combo_dino_model.currentIndex()]

        self.cfg["performance"]["scanner_workers"] = self.spin_workers.value()
        self.cfg["performance"]["use_cuda"] = self.chk_cuda.isChecked()

        self.cfg["tools"]["exiftool_path"] = self.edit_exiftool.text().strip()

        # Determine chosen mode
        if self.radio_mode_blur.isChecked():
            chosen_mode = "blur"
        elif self.radio_mode_custom.isChecked():
            chosen_mode = "custom"
        else:
            chosen_mode = "default"

        chosen_type = "video" if self.combo_bg_type.currentIndex() == 1 else "image"
        bg_file_val = self.edit_bg_file.text().strip()

        if self._selected_raw_bg_file and self._selected_raw_bg_file.exists():
            copied_path = import_background_file(self._selected_raw_bg_file)
            if copied_path:
                bg_file_val = f"assets/background/{copied_path.name}"

        chosen_theme = self.combo_theme.currentData()
        self.cfg["appearance"] = {
            "theme": chosen_theme,
            "background_mode": chosen_mode,
            "blur_opacity": self.slider_blur.value(),
            "blur_enabled": (chosen_mode == "blur"),
            "background_type": chosen_type if chosen_mode == "custom" else "none",
            "background_file": bg_file_val if chosen_mode == "custom" else "",
            "overlay_opacity": self.slider_opacity.value() / 100.0,
        }

        if save_settings(self.cfg):
            from ui.theme import theme
            if theme().mode != chosen_theme:
                theme().set_mode(chosen_theme)   # applies live, no restart needed
            QMessageBox.information(self, "Thành công", "Đã lưu cài đặt hệ thống thành công!")
            self.accept()
        else:
            QMessageBox.critical(self, "Lỗi", "Không thể lưu cài đặt vào config/settings.json")
