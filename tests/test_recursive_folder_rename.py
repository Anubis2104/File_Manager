"""
tests/test_recursive_folder_rename.py
Verify automatic recursive directory tree traversal and parameter-rich batch rename.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set offscreen Qt for headless testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from core.scanner import DirectoryScanner, FileInfo
from core.renamer import RenameEngine, build_new_name
from core.logger import RenameLogger
from ui.dialogs.rename_dialog import RenameDialog, _format_size


class TestRecursiveFolderRename(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Create nested directory tree:
        # root/
        # ├── root_img.jpg
        # ├── vacation/
        # │   ├── beach.jpg
        # │   └── mountains/
        # │       └── peak.jpg
        # └── clips/
        #     └── intro.mp4

        self.sub_vacation = self.root / "vacation"
        self.sub_mountains = self.sub_vacation / "mountains"
        self.sub_clips = self.root / "clips"

        self.sub_vacation.mkdir(parents=True, exist_ok=True)
        self.sub_mountains.mkdir(parents=True, exist_ok=True)
        self.sub_clips.mkdir(parents=True, exist_ok=True)

        self.f_root = self.root / "root_img.jpg"
        self.f_vacation = self.sub_vacation / "beach.jpg"
        self.f_mountains = self.sub_mountains / "peak.jpg"
        self.f_clip = self.sub_clips / "intro.mp4"

        for p in (self.f_root, self.f_vacation, self.f_mountains, self.f_clip):
            p.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 1024)  # dummy content

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_recursive_scanner_finds_all_subfolders(self):
        """Scanner with recursive=True must discover files in all subdirectories."""
        scanner = DirectoryScanner(root=self.root, recursive=True, max_workers=4)
        files = scanner.scan()
        found_paths = {f.path for f in files}

        self.assertEqual(len(files), 4)
        self.assertIn(self.f_root, found_paths)
        self.assertIn(self.f_vacation, found_paths)
        self.assertIn(self.f_mountains, found_paths)
        self.assertIn(self.f_clip, found_paths)

    def test_02_rename_engine_preserves_subfolder_structure(self):
        """RenameEngine.plan must keep each file in its original subfolder."""
        scanner = DirectoryScanner(root=self.root, recursive=True, max_workers=4)
        files = scanner.scan()

        engine = RenameEngine(date_fmt="YYYYMMDD", dry_run=True)
        ops = engine.plan(files)

        self.assertEqual(len(ops), 4)
        for op in ops:
            # Crucial requirement: op.dst.parent must remain op.src.parent!
            self.assertEqual(op.dst.parent, op.src.parent)

        # Check subfolder naming prefixes
        op_by_src = {op.src: op for op in ops}
        self.assertTrue(op_by_src[self.f_vacation].dst.name.startswith("vacation_"))
        self.assertTrue(op_by_src[self.f_mountains].dst.name.startswith("mountains_"))
        self.assertTrue(op_by_src[self.f_clip].dst.name.startswith("clips_"))

    def test_03_rename_dialog_ui_and_columns(self):
        """RenameDialog must initialize 8 columns with rich metadata parameters."""
        scanner = DirectoryScanner(root=self.root, recursive=True, max_workers=4)
        files = scanner.scan()

        dlg = RenameDialog(files=files, folder=self.root)
        self.assertEqual(dlg.table.columnCount(), 8)
        self.assertEqual(dlg.table.rowCount(), 4)

        expected_headers = [
            "Thư mục con",
            "Tên gốc",
            "Tên mới dự kiến",
            "Ngày (EXIF / Tạo)",
            "Độ phân giải & Chiều",
            "Dung lượng",
            "Định dạng",
            "Trạng thái",
        ]
        for col, expected in enumerate(expected_headers):
            item = dlg.table.horizontalHeaderItem(col)
            self.assertIsNotNone(item)
            self.assertEqual(item.text(), expected)

        # Verify search filter works
        dlg._filter_table("mountains")
        hidden_rows = [dlg.table.isRowHidden(r) for r in range(4)]
        self.assertEqual(hidden_rows.count(False), 1)  # Only 1 row visible
        dlg._filter_table("")  # Reset
        hidden_rows_reset = [dlg.table.isRowHidden(r) for r in range(4)]
        self.assertEqual(hidden_rows_reset.count(False), 4)  # All 4 visible

        # Verify summary badges
        self.assertIn("4 tệp", dlg.lbl_summary_files.text())

        dlg.close()

    def test_04_format_size_helper(self):
        """Verify _format_size helper handles various sizes correctly."""
        self.assertEqual(_format_size(500), "500 B")
        self.assertEqual(_format_size(2048), "2.0 KB")
        self.assertEqual(_format_size(5 * 1048576), "5.00 MB")
        self.assertEqual(_format_size(2 * 1073741824), "2.00 GB")


if __name__ == "__main__":
    unittest.main()
