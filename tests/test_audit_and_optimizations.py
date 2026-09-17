"""
Tests for comprehensive audit optimizations:
- Safe case-only renaming on Windows NTFS
- Nested empty folder chain detection
- DSU transitive clustering in embedding / duplicate engine
- RGBA to RGB white canvas background conversion
- QuickLook multi-file keyboard navigation
- Multi-folder ScanWorker scanning
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from PIL import Image

from utils.file_utils import safe_rename_with_retry
from core.cleaner import find_empty_folders
from duplicate.embedding_engine import DisjointSetUnion
from core.converter import ImageConverter
from core.workers import ScanWorker

# Headless Qt setup for UI widget test
from PyQt6.QtWidgets import QApplication
app = QApplication.instance()
if not app:
    app = QApplication([sys.argv[0], "-platform", "offscreen"])

from ui.widgets.quick_look_dialog import QuickLookDialog


class TestAuditOptimizations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="fmpro_audit_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_case_only_rename_windows(self):
        """Verify renaming 'file.txt' to 'File.txt' succeeds without FileExistsError."""
        f1 = self.temp_dir / "sample_case_test.txt"
        f1.write_text("Hello World", encoding="utf-8")
        
        target = self.temp_dir / "Sample_Case_Test.txt"
        ok = safe_rename_with_retry(f1, target)
        self.assertTrue(ok, "safe_rename_with_retry failed for case-only rename")
        self.assertTrue(target.exists(), "Target file does not exist after rename")
        self.assertEqual(target.read_text(encoding="utf-8"), "Hello World")

    def test_nested_empty_folders_cleaner(self):
        """Verify find_empty_folders identifies full tree of empty nested directories."""
        parent = self.temp_dir / "dir_a"
        child = parent / "dir_b"
        grandchild = child / "dir_c"
        grandchild.mkdir(parents=True, exist_ok=True)

        # Also create a non-empty branch
        non_empty = self.temp_dir / "dir_d" / "dir_e"
        non_empty.mkdir(parents=True, exist_ok=True)
        (non_empty / "data.txt").write_text("not empty", encoding="utf-8")

        empty_dirs = find_empty_folders(self.temp_dir)
        empty_paths = [p.resolve() for p in empty_dirs]

        self.assertIn(grandchild.resolve(), empty_paths)
        self.assertIn(child.resolve(), empty_paths)
        self.assertIn(parent.resolve(), empty_paths)
        self.assertNotIn(non_empty.resolve(), empty_paths)

    def test_dsu_transitive_clustering(self):
        """Verify DisjointSetUnion groups transitive similarities (0~1, 1~2 -> [0, 1, 2])."""
        dsu = DisjointSetUnion(5)
        dsu.union(0, 1)
        dsu.union(1, 2)
        dsu.union(3, 4)

        groups = dsu.get_groups()
        # Should have 2 groups: {0, 1, 2} and {3, 4}
        group_sets = [set(g) for g in groups]
        self.assertIn({0, 1, 2}, group_sets)
        self.assertIn({3, 4}, group_sets)

    def test_rgba_to_rgb_white_canvas(self):
        """Verify transparent PNG converted to JPEG has white background instead of pitch black."""
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 0)) # Fully transparent
        png_path = self.temp_dir / "transparent.png"
        img.save(png_path)

        out_path = self.temp_dir / "converted.jpg"
        ok, err = ImageConverter().convert(png_path, out_path, quality=95)
        self.assertTrue(ok, f"Image conversion failed: {err}")

        self.assertTrue(out_path.exists())
        with Image.open(out_path) as converted:
            self.assertEqual(converted.mode, "RGB")
            # Pixel at (0, 0) should be pure white (255, 255, 255)
            pixel = converted.getpixel((0, 0))
            self.assertGreaterEqual(pixel[0], 250)
            self.assertGreaterEqual(pixel[1], 250)
            self.assertGreaterEqual(pixel[2], 250)

    def test_quick_look_navigation(self):
        """Verify QuickLook navigates through file list with left/right keys."""
        f1 = self.temp_dir / "f1.txt"
        f2 = self.temp_dir / "f2.txt"
        f3 = self.temp_dir / "f3.txt"
        for f in (f1, f2, f3):
            f.write_text("quicklook content", encoding="utf-8")

        dialog = QuickLookDialog()
        dialog.preview(f1, [f1, f2, f3])
        self.assertEqual(dialog.current_path, f1)
        self.assertEqual(dialog._current_index, 0)

        # Navigate forward
        dialog._navigate(1)
        self.assertEqual(dialog.current_path, f2)
        self.assertEqual(dialog._current_index, 1)

        # Navigate forward again
        dialog._navigate(1)
        self.assertEqual(dialog.current_path, f3)
        self.assertEqual(dialog._current_index, 2)

        # Wrap around to beginning
        dialog._navigate(1)
        self.assertEqual(dialog.current_path, f1)
        self.assertEqual(dialog._current_index, 0)

        # Wrap backwards
        dialog._navigate(-1)
        self.assertEqual(dialog.current_path, f3)
        self.assertEqual(dialog._current_index, 2)
        dialog.close()

    def test_scan_worker_multi_folder(self):
        """Verify ScanWorker accepts a list of root folders and scans all files."""
        dir1 = self.temp_dir / "folder1"
        dir2 = self.temp_dir / "folder2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "a.txt").write_text("a", encoding="utf-8")
        (dir2 / "b.txt").write_text("b", encoding="utf-8")

        worker = ScanWorker(root=[dir1, dir2], recursive=True)
        found_files = []
        worker.file_found.connect(lambda f: found_files.append(f))
        worker.run()

        found_names = [f.name for f in found_files]
        self.assertIn("a.txt", found_names)
        self.assertIn("b.txt", found_names)

    def test_empty_folder_cancellation(self):
        """Verify find_empty_folders and CleanWorker halt immediately when cancelled."""
        from core.workers import CleanWorker
        from core.cleaner import find_empty_folders

        # 1. find_empty_folders with immediate cancel
        dirs = find_empty_folders(self.temp_dir, cancel_check=lambda: True)
        self.assertEqual(dirs, [])

        # 2. CleanWorker cancellation
        d1 = self.temp_dir / "c1"
        d1.mkdir()
        worker = CleanWorker(self.temp_dir, dry_run=True)
        worker.cancel()  # Pre-cancel

        cancelled_fired = []
        worker.cancelled.connect(lambda: cancelled_fired.append(True))
        worker.run()
        self.assertTrue(cancelled_fired, "CleanWorker did not emit cancelled signal when cancelled")

    def test_command_palette_sizing(self):
        """Verify CommandPalette items have adequate vertical size to prevent text clipping."""
        from ui.widgets.command_palette import CommandPaletteDialog, PaletteCommand
        dlg = CommandPaletteDialog()
        dlg.set_commands([
            PaletteCommand("Hành động", "Đổi tên hàng loạt tệp...", "rename", "Ctrl+R"),
            PaletteCommand("Hành động", "Xóa thư mục rỗng vào thùng rác", "trash", ""),
        ])
        self.assertEqual(dlg.list_widget.count(), 2)
        for i in range(dlg.list_widget.count()):
            item = dlg.list_widget.item(i)
            widget = dlg.list_widget.itemWidget(item)
            self.assertGreaterEqual(item.sizeHint().height(), 46, "Item sizeHint height must be >= 46px")
            self.assertLessEqual(widget.sizeHint().height(), item.sizeHint().height(), "Widget must fit within item sizeHint")
        dlg.close()

    def test_safe_folder_customization_ini(self):
        """Verify is_safe_folder_customization_ini accepts valid desktop.ini and rejects masqueraded executables."""
        from utils.file_utils import is_safe_folder_customization_ini

        # 1. Legitimate desktop.ini
        valid_ini = self.temp_dir / "desktop.ini"
        valid_ini.write_text("[.ShellClassInfo]\nIconResource=C:\\Windows\\system32\\SHELL32.dll,4\n[ViewState]\nFolderType=Generic\n", encoding="utf-8")
        self.assertTrue(is_safe_folder_customization_ini(valid_ini))

        # 2. Fake .exe.ini (masqueraded executable)
        fake_exe_ini = self.temp_dir / "update.exe.ini"
        fake_exe_ini.write_text("[Section]\nKey=Value\n", encoding="utf-8")
        self.assertFalse(is_safe_folder_customization_ini(fake_exe_ini))

        # 3. Binary executable header (MZ) disguised as desktop.ini
        mz_ini = self.temp_dir / "folder.ini"
        mz_ini.write_bytes(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00")
        self.assertFalse(is_safe_folder_customization_ini(mz_ini))

        # 4. Malicious script pattern disguised as ini
        script_ini = self.temp_dir / "custom.ini"
        script_ini.write_bytes(b"[Config]\nRun=powershell -enc aW52b2tl\n")
        self.assertFalse(is_safe_folder_customization_ini(script_ini))

    def test_empty_folder_cleaner_with_desktop_ini(self):
        """Verify find_empty_folders recognizes folders containing only safe desktop.ini as empty, but not malware.exe.ini."""
        from core.cleaner import find_empty_folders

        # Folder A contains only legitimate desktop.ini
        folder_a = self.temp_dir / "empty_with_desktop_ini"
        folder_a.mkdir()
        ini_file = folder_a / "desktop.ini"
        ini_file.write_text("[.ShellClassInfo]\nIconResource=SHELL32.dll,3\n", encoding="utf-8")

        # Folder B contains fake .exe.ini
        folder_b = self.temp_dir / "not_empty_with_fake_ini"
        folder_b.mkdir()
        fake_file = folder_b / "trojan.exe.ini"
        fake_file.write_text("[Section]\nKey=Val\n", encoding="utf-8")

        empty_dirs = find_empty_folders(self.temp_dir)
        empty_paths = [p.resolve() for p in empty_dirs]

        self.assertIn(folder_a.resolve(), empty_paths, "Folder containing only legitimate desktop.ini should be recognized as empty")
        self.assertNotIn(folder_b.resolve(), empty_paths, "Folder containing trojan.exe.ini must NOT be recognized as empty")

    def test_dinov2_index_alignment_when_image_fails(self):
        """Verify EmbeddingEngine maintains 1-to-1 alignment between _paths and _embeddings without IndexError."""
        from duplicate.embedding_engine import EmbeddingEngine
        import numpy as np

        engine = EmbeddingEngine()
        # Mock load_model to avoid downloading weights during test
        engine.load_model = lambda: None
        engine.model = lambda batch: batch.new_ones((batch.shape[0], engine.embedding_dim))

        # Create 2 valid images and 1 corrupt/invalid file
        img1 = self.temp_dir / "valid1.jpg"
        img2 = self.temp_dir / "valid2.jpg"
        bad_file = self.temp_dir / "corrupt.jpg"

        Image.new("RGB", (64, 64), color="red").save(img1)
        Image.new("RGB", (64, 64), color="blue").save(img2)
        bad_file.write_bytes(b"NOT_AN_IMAGE_GARBAGE_BYTES")

        # Mock _load_image: return None for bad_file, valid tensor for good files
        orig_load = engine._load_image
        def mocked_load(p):
            if p == bad_file:
                return None
            return orig_load(p)
        engine._load_image = mocked_load

        # Run build_index with all 3 files
        engine.build_index([img1, bad_file, img2])

        # Assert self._paths only has the 2 valid files and matches embedding count
        self.assertEqual(len(engine._paths), 2)
        self.assertEqual(len(engine._embeddings), 2)
        self.assertEqual(engine._paths, [img1, img2])

        # Assert find_all_duplicates runs without any IndexError
        groups = engine.find_all_duplicates(threshold=0.5)
        self.assertIsInstance(groups, list)

    def test_mkv_metadata_strip_and_write_ffmpeg(self):
        """Verify FFmpeg lossless metadata stripping and writing for MKV files."""
        import subprocess
        from datetime import datetime
        from core.metadata import (
            strip_video_metadata_with_ffmpeg,
            write_video_metadata_with_ffmpeg,
            MetadataEngine
        )

        test_mkv = self.temp_dir / "sample_test.mkv"
        # Create a 1-second synthetic MKV file with initial metadata
        cmd_create = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
            "-c:v", "libx264", "-metadata", "title=InitialTitle",
            "-metadata", "artist=InitialArtist",
            str(test_mkv)
        ]
        r = subprocess.run(cmd_create, capture_output=True)
        if r.returncode != 0:
            self.skipTest("FFmpeg binary not available for synthetic MKV test")

        # 1. Test strip_video_metadata_with_ffmpeg
        ok, err = strip_video_metadata_with_ffmpeg(test_mkv)
        self.assertTrue(ok, f"strip_video_metadata_with_ffmpeg failed: {err}")

        probe_r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format_tags=title:format_tags=artist", "-of", "default=noprint_wrappers=1:nokey=1", str(test_mkv)],
            capture_output=True, text=True
        )
        self.assertNotIn("InitialTitle", probe_r.stdout)
        self.assertNotIn("InitialArtist", probe_r.stdout)

        # 2. Test write_video_metadata_with_ffmpeg
        target_dt = datetime(2025, 4, 15, 9, 30, 0)
        ok2, err2 = write_video_metadata_with_ffmpeg(
            test_mkv,
            tags={"Artist": "VerifiedArtist", "Title": "VerifiedTitle"},
            dt=target_dt
        )
        self.assertTrue(ok2, f"write_video_metadata_with_ffmpeg failed: {err2}")

        probe_r2 = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format_tags=artist:format_tags=title:format_tags=creation_time", "-of", "default=noprint_wrappers=1:nokey=0", str(test_mkv)],
            capture_output=True, text=True
        )
        self.assertIn("VerifiedArtist", probe_r2.stdout)
        self.assertIn("VerifiedTitle", probe_r2.stdout)

        # 3. Test MetadataEngine.safe_strip on MKV
        engine = MetadataEngine()
        ok3, dt3, err3 = engine.safe_strip(test_mkv)
        self.assertTrue(ok3, f"safe_strip failed on MKV: {err3}")

    def test_safe_strip_with_unicode_and_brackets(self):
        """Verify safe_strip and date restoration succeed on paths with brackets and Unicode/CJK."""
        from core.metadata import MetadataEngine
        from PIL import Image

        unicode_dir = self.temp_dir / "[紧急企划] R18 内部私定 [Test]"
        unicode_dir.mkdir(parents=True, exist_ok=True)
        test_jpg = unicode_dir / "[特写] 奶昔_001.jpg"

        img = Image.new("RGB", (32, 32), color="red")
        img.save(test_jpg, format="JPEG")

        engine = MetadataEngine()
        ok, dt, err = engine.safe_strip(test_jpg)
        self.assertTrue(ok, f"safe_strip failed on Unicode bracket path: {err}")
        self.assertEqual(err, "")

        # Also verify read_all succeeds via ExifTool
        tags = engine.read_all(test_jpg)
        self.assertIsInstance(tags, dict)
        self.assertTrue(len(tags) > 0)


if __name__ == "__main__":
    unittest.main()

