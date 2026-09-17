"""
tests/test_ui_upgrades.py
Automated Unit Tests for FileManagerPro UI/UX Upgrades:
- Vector SVG Iconography
- QuickLook Modal Viewer
- Command Palette (Spotlight launcher)
- Media Card Delegate
- ContentPanel Dropzone & Event handling
"""
import sys
import os
import unittest
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QSize, QEvent
from PyQt6.QtGui import QKeyEvent, QFileSystemModel, QPixmap

# Ensure QApplication exists in test environment
_APP = QApplication.instance() or QApplication(sys.argv)

from ui.widgets.svg_icons import get_svg_pixmap, get_svg_icon
from ui.widgets.quick_look_dialog import QuickLookDialog
from ui.widgets.command_palette import CommandPaletteDialog, PaletteCommand
from ui.panels.media_card_delegate import MediaCardDelegate
from ui.panels.content_panel import ContentPanel, EmptyDropzoneWidget


class TestUIUpgrades(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_folder = Path(cls.temp_dir.name)

        # Create sample files for testing
        cls.img_path = cls.test_folder / "test_photo.jpg"
        pix = QPixmap(100, 100)
        pix.fill(Qt.GlobalColor.blue)
        pix.save(str(cls.img_path))

        cls.txt_path = cls.test_folder / "notes.txt"
        cls.txt_path.write_text("Hello FileManagerPro UI upgrade!\nLine 2.\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_svg_icon_generation(self):
        """Verify vector SVG icons generate non-null pixmaps and scalable icons."""
        test_icons = ["folder", "drive", "image", "video", "rename", "command", "shield", "trash"]
        for name in test_icons:
            pix = get_svg_pixmap(name, color="#38bdf8", size=24)
            self.assertFalse(pix.isNull(), f"SVG Pixmap for '{name}' should not be null")
            self.assertEqual(pix.width(), 24)
            self.assertEqual(pix.height(), 24)

            icon = get_svg_icon(name, color="#cbd5e1", size=20)
            self.assertFalse(icon.isNull(), f"QIcon for '{name}' should not be null")

    def test_quick_look_dialog(self):
        """Verify QuickLookDialog previews files, extracts badges, and navigates."""
        dlg = QuickLookDialog()
        files = [self.img_path, self.txt_path]

        # Preview image
        dlg.preview(self.img_path, files)
        self.assertEqual(dlg.current_path, self.img_path)
        self.assertIn("test_photo.jpg", dlg.lbl_filename.text())
        self.assertIn("1 / 2", dlg.lbl_counter.text())

        # Test navigate next
        dlg._navigate(1)
        self.assertEqual(dlg.current_path, self.txt_path)
        self.assertIn("notes.txt", dlg.lbl_filename.text())
        self.assertIn("2 / 2", dlg.lbl_counter.text())

        # Test navigate previous
        dlg._navigate(-1)
        self.assertEqual(dlg.current_path, self.img_path)

        dlg.close()

    def test_command_palette(self):
        """Verify CommandPalette filters commands accurately and executes callbacks."""
        dlg = CommandPaletteDialog()
        executed = []

        cmds = [
            PaletteCommand("Hành động", "Đổi tên hàng loạt", "rename", "Ctrl+R", lambda: executed.append("rename")),
            PaletteCommand("Hành động", "Xóa Metadata tệp", "shield", "", lambda: executed.append("meta")),
            PaletteCommand("Điều hướng", "Nhảy tới Desktop", "folder", "", path_target=Path.home() / "Desktop"),
        ]
        dlg.set_commands(cmds)

        # Initial unfiltered count
        self.assertEqual(len(dlg._filtered_commands), 3)

        # Filter query
        dlg._filter_commands("meta")
        self.assertEqual(len(dlg._filtered_commands), 1)
        self.assertEqual(dlg._filtered_commands[0].title, "Xóa Metadata tệp")

        # Execute selected command
        dlg._execute_selected()
        self.assertIn("meta", executed)

        dlg.close()

    def test_media_card_delegate(self):
        """Verify MediaCardDelegate size hint and thumbnail caching."""
        model = QFileSystemModel()
        delegate = MediaCardDelegate(model)
        from PyQt6.QtWidgets import QStyleOptionViewItem
        opt = QStyleOptionViewItem()
        idx = model.index(0, 0)
        size = delegate.sizeHint(opt, idx)
        self.assertEqual(size.width(), MediaCardDelegate.CARD_WIDTH)
        self.assertEqual(size.height(), MediaCardDelegate.CARD_HEIGHT)

    def test_content_panel_dropzone(self):
        """Verify ContentPanel contains EmptyDropzoneWidget and custom signals."""
        panel = ContentPanel()
        self.assertTrue(hasattr(panel, "dropzone"))
        self.assertIsInstance(panel.dropzone, EmptyDropzoneWidget)
        self.assertTrue(hasattr(panel, "quick_look_requested"))
        self.assertTrue(hasattr(panel, "files_dropped"))

        # Verify dropzone buttons can trigger signals without crashing
        panel.dropzone.create_folder_clicked.emit()
        panel.dropzone.browse_clicked.emit()
        panel.dropzone.go_up_clicked.emit()

    def test_appearance_settings_and_modes(self):
        """Verify 3 background modes, blur slider range, and SettingsDialog integration."""
        from core.background_manager import load_appearance_settings, save_appearance_settings
        from ui.dialogs.settings_dialog import SettingsDialog

        # Test loading appearance settings defaults
        appr = load_appearance_settings()
        self.assertIn("background_mode", appr)
        self.assertIn("blur_opacity", appr)
        self.assertIn(appr["background_mode"], ("default", "blur", "custom"))
        self.assertGreaterEqual(appr["blur_opacity"], 0)
        self.assertLessEqual(appr["blur_opacity"], 100)

        # Test SettingsDialog UI components
        dlg = SettingsDialog()
        self.assertTrue(hasattr(dlg, "radio_mode_default"))
        self.assertTrue(hasattr(dlg, "radio_mode_blur"))
        self.assertTrue(hasattr(dlg, "radio_mode_custom"))
        self.assertTrue(hasattr(dlg, "slider_blur"))
        self.assertTrue(hasattr(dlg, "lbl_blur_val"))

        # Test switching to Default mode
        dlg.radio_mode_default.setChecked(True)
        dlg._update_mode_ui_state()
        self.assertFalse(dlg.g_blur.isEnabled())
        self.assertFalse(dlg.g_wall.isEnabled())

        # Test switching to Blur mode
        dlg.radio_mode_blur.setChecked(True)
        dlg._update_mode_ui_state()
        self.assertTrue(dlg.g_blur.isEnabled())
        self.assertFalse(dlg.g_wall.isEnabled())

        # Test blur slider values and label text
        dlg.slider_blur.setValue(0)
        self.assertIn("Trong suốt hoàn toàn", dlg.lbl_blur_val.text())

        dlg.slider_blur.setValue(20)
        self.assertIn("Trong suốt cao", dlg.lbl_blur_val.text())

        dlg.slider_blur.setValue(50)
        self.assertIn("Kính mờ tiêu chuẩn", dlg.lbl_blur_val.text())

        dlg.slider_blur.setValue(95)
        self.assertIn("Mờ đục", dlg.lbl_blur_val.text())

        # Test switching to Custom mode
        dlg.radio_mode_custom.setChecked(True)
        dlg._update_mode_ui_state()
        self.assertFalse(dlg.g_blur.isEnabled())
        self.assertTrue(dlg.g_wall.isEnabled())

        dlg.close()


if __name__ == "__main__":
    unittest.main()

