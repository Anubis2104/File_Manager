"""
tests/test_progress_dialog_and_cancellation.py
Comprehensive test suite verifying:
1. TaskProgressDialog UI and API (indeterminate, progress updates, counter, cancel signal).
2. RenameOperation constructor compatibility with original_name and kwargs.
3. All worker classes support cancel() and emit cancelled signal.
4. Queue rename workflow execution with progress dialog.
"""
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from ui.widgets.progress_dialog import TaskProgressDialog
from utils.file_utils import RenameOperation
from core.workers import (
    RenameWorker, MetadataStripWorker, DupScanWorker, CleanWorker,
    DupDeleteWorker, MetadataRewriteWorker, DupRenameWorker, InspectorWorker
)
from ui.dialogs.convert_dialog import ConvertWorker


class TestProgressDialogAndCancellation(unittest.TestCase):

    def test_rename_operation_kwargs(self):
        """Verify RenameOperation accepts original_name and arbitrary kwargs without TypeError."""
        p1 = Path("test_src.jpg")
        p2 = Path("test_dst.jpg")
        op = RenameOperation(src=p1, dst=p2, dry_run=True, original_name="test_src.jpg", extra_flag="xyz")
        self.assertEqual(op.original_name, "test_src.jpg")
        self.assertEqual(op.src, p1)
        self.assertEqual(op.dst, p2)

    def test_progress_dialog_basics(self):
        """Test TaskProgressDialog state transitions, indeterminate mode, and update_progress."""
        dlg = TaskProgressDialog("Kiểm tra tiến trình")
        dlg.set_task("Tiến trình thử nghiệm", total=50, icon="🚀")
        self.assertEqual(dlg.progress_bar.maximum(), 50)
        self.assertEqual(dlg.lbl_title.text(), "Tiến trình thử nghiệm")

        dlg.update_progress(25, 50, "file_abc.jpg")
        self.assertEqual(dlg.progress_bar.value(), 25)
        self.assertIn("25 / 50 (50%)", dlg.lbl_counter.text())
        self.assertIn("file_abc.jpg", dlg.lbl_status.text())

        # Indeterminate mode
        dlg.set_indeterminate("Đang tải dữ liệu...")
        self.assertEqual(dlg.progress_bar.minimum(), 0)
        self.assertEqual(dlg.progress_bar.maximum(), 0)

        # Cancel emission
        received = []
        dlg.cancelled.connect(lambda: received.append(True))
        dlg.btn_cancel.click()
        self.assertTrue(len(received) > 0)
        self.assertTrue(dlg._is_cancelled)
        dlg.close()

    def test_all_workers_have_cancel_contract(self):
        """Verify all background workers have cancel() method and cancelled pyqtSignal."""
        workers = [
            RenameWorker(ops=[]),
            MetadataStripWorker(paths=[]),
            DupScanWorker(image_paths=[]),
            CleanWorker(root=Path(".")),
            DupDeleteWorker(target_paths=[]),
            MetadataRewriteWorker(files=[], tags={}),
            DupRenameWorker(groups=[]),
            InspectorWorker(root=Path(".")),
            ConvertWorker(jobs=[]),
        ]

        for w in workers:
            name = w.__class__.__name__
            self.assertTrue(hasattr(w, "cancel"), f"{name} missing cancel() method")
            self.assertTrue(callable(getattr(w, "cancel")), f"{name}.cancel is not callable")
            self.assertTrue(hasattr(w, "cancelled"), f"{name} missing cancelled signal")
            self.assertFalse(w._cancel_flag, f"{name} initial _cancel_flag should be False")
            w.cancel()
            self.assertTrue(w._cancel_flag, f"{name} _cancel_flag should be True after cancel()")

    def test_rename_worker_cancellation_execution(self):
        """Test RenameWorker actually respects cancel and halts before executing all ops."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ops = []
            for i in range(10):
                f = tmp_path / f"test_{i}.txt"
                f.write_text("content")
                dest = tmp_path / f"renamed_{i}.txt"
                ops.append(RenameOperation(src=f, dst=dest, dry_run=False))

            worker = RenameWorker(ops=ops)
            # Cancel immediately
            worker.cancel()

            cancelled_fired = []
            worker.cancelled.connect(lambda: cancelled_fired.append(True))
            worker.run()

            self.assertTrue(len(cancelled_fired) > 0, "Worker should have emitted cancelled signal")
            # All 10 files should not have been renamed because it was cancelled at op 0
            self.assertTrue((tmp_path / "test_9.txt").exists(), "test_9.txt should still exist un-renamed")

    def test_progress_dialog_attach_worker_and_direct_cancel(self):
        """Verify TaskProgressDialog.attach_worker connects worker.cancel and sets _worker_ref."""
        worker = RenameWorker(ops=[])
        dlg = TaskProgressDialog("Tiến trình đính kèm")
        dlg.attach_worker(worker)
        self.assertIs(dlg._worker_ref, worker)
        self.assertFalse(worker.is_cancelled)

        # Trigger cancel on dialog
        dlg.btn_cancel.click()
        self.assertTrue(worker.is_cancelled, "Worker should be cancelled immediately via DirectConnection")
        self.assertTrue(worker._cancel_event.is_set())
        dlg.close()

    def test_rename_midway_cancellation(self):
        """Verify that cancelling during execution halts rename and preserves unrenamed files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ops = []
            for i in range(10):
                f = tmp_path / f"item_{i}.txt"
                f.write_text(f"content {i}")
                dest = tmp_path / f"renamed_{i}.txt"
                ops.append(RenameOperation(src=f, dst=dest, dry_run=False))

            worker = RenameWorker(ops=ops)
            dlg = TaskProgressDialog("Đổi tên")
            dlg.attach_worker(worker)

            def cancel_on_progress(cur, tot, name):
                if cur == 3:
                    dlg.btn_cancel.click()

            worker.progress.connect(cancel_on_progress)
            cancelled_fired = []
            worker.cancelled.connect(lambda: cancelled_fired.append(True))

            worker.run()

            self.assertTrue(len(cancelled_fired) > 0, "Cancelled signal must be emitted")
            # 3 items renamed, items 4..9 must NOT be renamed!
            self.assertTrue((tmp_path / "item_9.txt").exists(), "item_9.txt must not be renamed after cancel")
            self.assertFalse((tmp_path / "renamed_9.txt").exists(), "renamed_9.txt must not exist")
            dlg.close()


if __name__ == "__main__":
    unittest.main()

