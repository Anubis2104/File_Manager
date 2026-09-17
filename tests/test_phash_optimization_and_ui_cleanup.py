import os
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
import tempfile
import shutil

from PyQt6.QtWidgets import QApplication, QHeaderView, QProgressBar

from duplicate.phash_engine import PHashEngine
from duplicate.dup_manager import DupManager
from ui.dialogs.rename_dialog import RenameDialog
from ui.dialogs.queue_rename_dialog import QueueRenameDialog
from ui.dialogs.organize_dialog import OrganizeDialog
from ui.dialogs.metadata_dialog import MetadataDialog
from ui.dialogs.convert_dialog import ConvertDialog
from ui.dialogs.log_restore_dialog import LogRestoreDialog
from ui.dialogs.stats_dialog import StatsDialog
from ui.panels.dup_preview_panel import DupPreviewPanel
from ui.panels.right_dock_panel import QueueDockWidget


app = QApplication.instance()
if not app:
    app = QApplication([])


class TestPHashOptimizationAndUICleanup(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="fmpro_phash_test_"))

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_phash_vectorized_gemm_correctness_and_speed(self):
        """Verify vectorized matrix multiplication yields accurate clusters in milliseconds."""
        engine = PHashEngine(device="cpu")
        N = 300
        # Create synthetic hashes dict {Path: np.ndarray(64,)}
        np.random.seed(42)
        base_hash = np.random.randint(0, 2, size=(64,), dtype=bool)
        
        hashes = {}
        for i in range(N):
            p = Path(f"test_{i}.jpg")
            h = np.random.randint(0, 2, size=(64,), dtype=bool)
            hashes[p] = h
            
        # Inject exact duplicates and 1-bit difference duplicates
        # Group 1: 0, 1, 2
        p0, p1, p2 = Path("test_0.jpg"), Path("test_1.jpg"), Path("test_2.jpg")
        hashes[p0] = base_hash
        hashes[p1] = base_hash.copy()
        hashes[p2] = base_hash.copy()
        hashes[p2][0] = not hashes[p2][0]  # distance 1
        
        # Group 2: 10, 11
        p10, p11 = Path("test_10.jpg"), Path("test_11.jpg")
        other_hash = np.random.randint(0, 2, size=(64,), dtype=bool)
        hashes[p10] = other_hash
        hashes[p11] = other_hash.copy()
        
        import time
        t0 = time.perf_counter()
        groups = engine.find_duplicate_groups_cpu(hashes, threshold=5)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.2, f"Vectorized grouping took too long: {elapsed:.3f}s")
        
        # Verify groups found
        group_sets = [set(g) for g in groups]
        self.assertTrue(any({p0, p1, p2}.issubset(s) for s in group_sets))
        self.assertTrue(any({p10, p11}.issubset(s) for s in group_sets))

    def test_phash_cancellation_and_progress(self):
        """Verify compute_batch supports on_progress and early cancellation."""
        img_paths = []
        for i in range(5):
            p = self.temp_dir / f"img_{i}.png"
            img = Image.new("RGB", (32, 32), color=(i * 40, 100, 150))
            img.save(p)
            img_paths.append(p)

        engine = PHashEngine(device="cpu")
        progress_calls = []

        def on_prog(cur, tot, name):
            progress_calls.append((cur, tot, name))

        # Test normal batch with progress
        hashes = engine.compute_batch(img_paths, on_progress=on_prog)
        self.assertEqual(len(hashes), 5)
        self.assertGreater(len(progress_calls), 0)

        # Test early cancellation
        cancel_after = 2
        def cancel_check():
            return len(progress_calls) >= cancel_after

        progress_calls.clear()
        hashes_cancelled = engine.compute_batch(
            img_paths, on_progress=on_prog, cancel_check=cancel_check
        )
        self.assertLess(len(hashes_cancelled), 5, "Cancellation did not abort batch computation early")

    def test_no_embedded_progress_bars_in_dialogs_and_panels(self):
        def get_embedded_progress_bars(widget):
            from ui.widgets.progress_dialog import TaskProgressDialog
            bars = []
            for pb in widget.findChildren(QProgressBar):
                # If the progress bar is inside a modal TaskProgressDialog, it is not an embedded bar
                p = pb.parent()
                is_task_dlg = False
                while p is not None:
                    if isinstance(p, TaskProgressDialog):
                        is_task_dlg = True
                        break
                    p = p.parent()
                if not is_task_dlg:
                    bars.append(pb)
            return bars

        # 1. DupPreviewPanel
        dup_panel = DupPreviewPanel()
        self.assertEqual(len(get_embedded_progress_bars(dup_panel)), 0)
        self.assertFalse(hasattr(dup_panel, "progress_bar"))

        # 2. QueueDockWidget
        queue_dock = QueueDockWidget()
        self.assertEqual(len(get_embedded_progress_bars(queue_dock)), 0)
        self.assertFalse(hasattr(queue_dock, "progress_bar"))

        # 3. RenameDialog
        rename_dlg = RenameDialog()
        self.assertEqual(len(get_embedded_progress_bars(rename_dlg)), 0)
        self.assertFalse(hasattr(rename_dlg, "progress"))
        self.assertFalse(hasattr(rename_dlg, "scan_banner"))

        # 4. QueueRenameDialog
        queue_rename_dlg = QueueRenameDialog(folder=self.temp_dir)
        self.assertEqual(len(get_embedded_progress_bars(queue_rename_dlg)), 0)
        self.assertFalse(hasattr(queue_rename_dlg, "progress"))

        # 5. OrganizeDialog
        organize_dlg = OrganizeDialog(files=[], root_dir=self.temp_dir)
        self.assertEqual(len(get_embedded_progress_bars(organize_dlg)), 0)
        self.assertFalse(hasattr(organize_dlg, "progress"))

        # 6. ConvertDialog
        convert_dlg = ConvertDialog()
        self.assertEqual(len(get_embedded_progress_bars(convert_dlg)), 0)
        self.assertFalse(hasattr(convert_dlg, "progress"))

        # 7. LogRestoreDialog
        log_dlg = LogRestoreDialog()
        self.assertEqual(len(get_embedded_progress_bars(log_dlg)), 0)
        self.assertFalse(hasattr(log_dlg, "progress"))

        # 8. StatsDialog
        stats_dlg = StatsDialog(self.temp_dir)
        self.assertEqual(len(get_embedded_progress_bars(stats_dlg)), 0)
        self.assertFalse(hasattr(stats_dlg, "progress"))
        if stats_dlg._thread and stats_dlg._thread.isRunning():
            stats_dlg._worker.cancel()
            stats_dlg._thread.quit()
            stats_dlg._thread.wait(500)

        # 9. MetadataDialog
        meta_dlg = MetadataDialog(current_dir=self.temp_dir)
        self.assertEqual(len(get_embedded_progress_bars(meta_dlg)), 0)
        self.assertFalse(hasattr(meta_dlg, "progress"))

    def test_metadata_dialog_avoids_resizetocontents_freeze(self):
        """Verify MetadataDialog does not use ResizeToContents on data columns (which caused 107s freeze)."""
        meta_dlg = MetadataDialog(current_dir=self.temp_dir)
        header = meta_dlg.table.horizontalHeader()
        mode_col2 = header.sectionResizeMode(2)
        mode_col3 = header.sectionResizeMode(3)
        self.assertNotEqual(mode_col2, QHeaderView.ResizeMode.ResizeToContents)
        self.assertNotEqual(mode_col3, QHeaderView.ResizeMode.ResizeToContents)


if __name__ == "__main__":
    unittest.main()
