"""
tests/test_queue_renamer.py
Unit tests for QueueRenameDialog, Token Chip Builder, Breadcrumbs, and Hover Preview.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPoint

from core.scanner import DirectoryScanner, FileInfo
from core.renamer import RenameEngine, build_new_name
from ui.dialogs.queue_rename_dialog import QueueRenameDialog
from ui.widgets.toolbar import BreadcrumbAddressBar
from ui.widgets.hover_preview import HoverThumbnailPopup


class TestQueueRenamerAndUX(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Create folder with N files
        self.folder_a = self.root / "FolderA"
        self.folder_a.mkdir(parents=True, exist_ok=True)

        self.f1 = self.folder_a / "IMG_0001.JPG"
        self.f2 = self.folder_a / "IMG_0002.JPG"
        self.f3 = self.folder_a / "VIDEO_0003.MP4"

        for f in (self.f1, self.f2, self.f3):
            f.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 1024)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_token_chip_builder_pattern(self):
        """Verify custom token patterns in build_new_name and RenameEngine."""
        scanner = DirectoryScanner(root=self.folder_a, recursive=False)
        files = scanner.scan()
        self.assertEqual(len(files), 3)

        # Test pattern: {seq}_{folder}_{original}
        engine = RenameEngine(pattern="{seq}_{folder}_{original}", dry_run=True)
        ops = engine.plan(files)
        self.assertEqual(len(ops), 3)

        ops_by_src = {op.src.name: op for op in ops}
        self.assertTrue("_FolderA_IMG_0001" in ops_by_src["IMG_0001.JPG"].dst.name)
        self.assertTrue("_FolderA_IMG_0002" in ops_by_src["IMG_0002.JPG"].dst.name)
        self.assertTrue("_FolderA_VIDEO_0003" in ops_by_src["VIDEO_0003.MP4"].dst.name)
        self.assertEqual({op.dst.name[:3] for op in ops}, {"001", "002", "003"})

    def test_02_queue_rename_dialog_initialization(self):
        """Verify QueueRenameDialog initializes pool with N files and N empty slots."""
        dlg = QueueRenameDialog(folder=self.folder_a)
        self.assertEqual(dlg.total_count, 3)
        self.assertEqual(dlg.pool_list.count(), 3)
        self.assertEqual(dlg.queue_table.rowCount(), 3)
        self.assertTrue(all(slot is None for slot in dlg.slots))
        dlg.close()

    def test_03_queue_rename_slot_assignment_and_formula(self):
        """Verify slot assignment generates [Số thứ tự]_[Tên cũ]."""
        dlg = QueueRenameDialog(folder=self.folder_a)

        # Double click first item in pool -> assigns to slot 0
        item = dlg.pool_list.item(0)
        dlg._on_pool_double_clicked(item)

        self.assertIsNotNone(dlg.slots[0])
        self.assertEqual(dlg.pool_list.count(), 2)

        # Check planned name in slot 0
        new_name_in_table = dlg.queue_table.item(0, 2).text()
        self.assertTrue(new_name_in_table.startswith("001_FolderA_"))

        # Fill remaining slots
        dlg._fill_remaining_slots()
        self.assertTrue(all(slot is not None for slot in dlg.slots))
        self.assertEqual(dlg.pool_list.count(), 0)

        # Verify all 3 slots have sequential numbers
        self.assertTrue(dlg.queue_table.item(0, 2).text().startswith("001_"))
        self.assertTrue(dlg.queue_table.item(1, 2).text().startswith("002_"))
        self.assertTrue(dlg.queue_table.item(2, 2).text().startswith("003_"))

        # Test move up/down
        first_path = dlg.slots[0].path
        second_path = dlg.slots[1].path
        dlg._move_slot(0, 1)  # Move slot 0 down to slot 1
        self.assertEqual(dlg.slots[0].path, second_path)
        self.assertEqual(dlg.slots[1].path, first_path)

        dlg.close()

    def test_04_queue_rename_auto_sort(self):
        """Verify auto-sort by name fills all slots alphabetically."""
        dlg = QueueRenameDialog(folder=self.folder_a)
        dlg._auto_sort("name")

        self.assertTrue(all(slot is not None for slot in dlg.slots))
        self.assertEqual(dlg.slots[0].name, "IMG_0001.JPG")
        self.assertEqual(dlg.slots[1].name, "IMG_0002.JPG")
        self.assertEqual(dlg.slots[2].name, "VIDEO_0003.MP4")

        dlg.close()

    def test_05_breadcrumb_address_bar(self):
        """Verify BreadcrumbAddressBar decomposes path and emits navigation signal."""
        bar = BreadcrumbAddressBar()
        bar.set_path(self.folder_a)

        self.assertEqual(bar.text(), str(self.folder_a))
        # Crumb layout should have widgets for parts plus chevrons and edit button
        self.assertGreater(bar.crumb_layout.count(), 1)

        # Toggle to edit mode
        bar.focus_edit()
        self.assertEqual(bar.stack.currentIndex(), 1)

    def test_06_hover_thumbnail_popup(self):
        """Verify HoverThumbnailPopup initializes and generates preview without errors."""
        popup = HoverThumbnailPopup.instance()
        popup.show_preview(self.f1, QPoint(100, 100), "1024x768 • 1 KB")
        self.assertEqual(popup._current_path, self.f1)
        popup.hide()


if __name__ == "__main__":
    unittest.main()
