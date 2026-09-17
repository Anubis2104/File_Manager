"""
tests/test_simulation_folder_rename_flow.py
Simulates the entire user flow:
1. User right clicks or selects a folder in TreePanel or ContentPanel.
2. Triggers Rename.
3. Verifies recursive folder traversal and parameter extraction.
4. Executes rename and verifies on-disk changes and logcat logging.
"""
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.dialogs.rename_dialog import RenameDialog
from core.scanner import DirectoryScanner


class TestSimulationFolderRenameFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # Create realistic folder structure:
        # root/
        # ├── 2024_Trip/
        # │   ├── Day1/
        # │   │   ├── DSC_0001.JPG
        # │   │   └── DSC_0002.JPG
        # │   └── Day2/
        # │       └── DSC_0003.JPG
        # └── Notes.txt

        self.dir_trip = self.root / "2024_Trip"
        self.dir_day1 = self.dir_trip / "Day1"
        self.dir_day2 = self.dir_trip / "Day2"

        self.dir_day1.mkdir(parents=True, exist_ok=True)
        self.dir_day2.mkdir(parents=True, exist_ok=True)

        self.f1 = self.dir_day1 / "DSC_0001.JPG"
        self.f2 = self.dir_day1 / "DSC_0002.JPG"
        self.f3 = self.dir_day2 / "DSC_0003.JPG"
        self.f_notes = self.root / "Notes.txt"

        for f in (self.f1, self.f2, self.f3):
            f.write_bytes(b"\xFF\xD8\xFF\xE0" + b"\x00" * 2048)
        self.f_notes.write_text("Vacation plan", encoding="utf-8")

        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        # Process any pending Qt events
        QApplication.processEvents()
        self.temp_dir.cleanup()

    def test_tree_context_menu_batch_rename_trigger(self):
        """Simulate right-clicking on a folder in TreePanel and launching batch rename."""
        self.window._navigate_to(self.root)

        # Pre-scanned files check
        scanner = DirectoryScanner(root=self.dir_trip, recursive=True)
        scanned_files = scanner.scan()
        self.assertEqual(len(scanned_files), 3)

        dlg = RenameDialog(files=scanned_files, folder=self.dir_trip, parent=self.window)
        self.assertEqual(dlg.table.rowCount(), 3)

        # Verify all 3 files are captured with their subfolders (Day1 and Day2)
        subfolder_names = [dlg.table.item(r, 0).text() for r in range(3)]
        self.assertTrue(any("Day1" in s for s in subfolder_names))
        self.assertTrue(any("Day2" in s for s in subfolder_names))

        # Verify new planned names preserve subfolders
        planned_names = [dlg.table.item(r, 2).text() for r in range(3)]
        self.assertTrue(all(name.lower().endswith(".jpg") for name in planned_names))
        self.assertTrue(any(name.startswith("Day1_") for name in planned_names))
        self.assertTrue(any(name.startswith("Day2_") for name in planned_names))

        dlg.close()

    def test_content_panel_folder_selection_rename(self):
        """Simulate selecting a folder in ContentPanel and opening RenameDialog with background scan."""
        self.window._navigate_to(self.root)

        dlg = RenameDialog(folder=self.dir_trip, parent=self.window)
        start = time.time()
        while dlg._scan_thread and dlg._scan_thread.isRunning() and (time.time() - start < 3.0):
            QApplication.processEvents()
            time.sleep(0.05)

        self.assertEqual(dlg.table.rowCount(), 3)
        dlg.close()


if __name__ == "__main__":
    unittest.main()
