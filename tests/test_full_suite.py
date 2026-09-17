"""
tests/test_full_suite.py
Comprehensive automated test suite for all FileManagerPro modules.
"""
from __future__ import annotations

import sys
import os
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image
import piexif

from utils.cuda_helper import get_cuda_info, cuda_available
from utils.file_utils import (
    compute_md5, compute_sha256, sanitize_filename,
    make_unique_path, safe_long_path, safe_rename_with_retry,
    RenameOperation, classify_extension,
)
from utils.date_utils import parse_exif_date, format_date_for_rename, extract_best_date
from utils.media_info import get_image_info, get_video_info, get_media_dimensions
from core.scanner import FileInfo, DirectoryScanner
from core.metadata import MetadataEngine, resolve_exiftool_exe
from core.renamer import RenameEngine, build_new_name
from core.logger import RenameLogger, LogEntry
from core.cleaner import FolderCleaner
from core.converter import ImageConverter
from core.organizer import FileOrganizer
from duplicate.phash_engine import PHashEngine
from duplicate.embedding_engine import EmbeddingEngine
from duplicate.dup_manager import DupManager, collect_image_paths


def test_suite():
    passed = 0
    failed = 0
    test_dir = Path(tempfile.mkdtemp(prefix="fmpro_test_"))
    print(f"=== Running FileManagerPro Test Suite in {test_dir} ===\n")

    def report(name: str, success: bool, detail: str = ""):
        nonlocal passed, failed
        if success:
            passed += 1
            print(f"  [PASS] {name} {detail}")
        else:
            failed += 1
            print(f"  [FAIL] {name} - {detail}")

    try:
        # 1. CUDA Helper Test
        info = get_cuda_info()
        report("CUDA Helper", True, f"Device: {info.device_name or 'CPU'}")

        # 2. File Utils: Hash, Sanitize, Long Path, Unique Path
        test_file = test_dir / "test_file.txt"
        test_file.write_text("Hello FileManagerPro Test", encoding="utf-8")
        md5_val = compute_md5(test_file)
        report("Compute MD5", len(md5_val) == 32, f"MD5: {md5_val}")

        sanitized = sanitize_filename("CON:<>|?*test  .")
        report("Sanitize Filename", "CON______test" in sanitized, f"Got: {sanitized}")

        u_path = make_unique_path(test_file)
        report("Make Unique Path", u_path.name == "test_file_001.txt", f"Got: {u_path.name}")

        long_p = safe_long_path(test_file)
        report("Safe Long Path", bool(long_p), f"Path: {long_p}")

        # Test Safe Rename with Retry
        dst_renamed = test_dir / "test_renamed.txt"
        ok, err = safe_rename_with_retry(test_file, dst_renamed)
        report("Safe Rename with Retry", ok and dst_renamed.exists(), f"Error: {err}")

        # 3. Media Creation & Date Extraction
        img_path = test_dir / "sample_photo.jpg"
        img = Image.new("RGB", (800, 600), color=(100, 150, 200))
        exif_bytes = piexif.dump({
            "0th": {},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2023:10:25 12:34:56"},
            "GPS": {}
        })
        img.save(img_path, exif=exif_bytes)

        dt, src_type = extract_best_date(img_path)
        report("Date Extraction", dt is not None and dt.year == 2023, f"Date: {dt}, Source: {src_type}")

        dim = get_image_info(img_path)
        report("Image Info & Orientation", dim.width == 800 and dim.height == 600 and dim.orientation == "H",
               f"{dim.width}x{dim.height} ({dim.orientation})")

        # 4. Scanner Test
        scanner = DirectoryScanner(root=test_dir, recursive=True)
        scanned = scanner.scan()
        report("Directory Scanner", len(scanned) >= 2, f"Scanned {len(scanned)} items")

        # 5. Metadata Engine Test (Safe Strip + Date Restoration)
        meta_engine = MetadataEngine()
        exif_avail = meta_engine.is_exiftool_available()
        report("ExifTool Detection", exif_avail, f"Exe: {meta_engine.exiftool_exe}")

        if exif_avail:
            ok_strip, pres_dt, strip_err = meta_engine.safe_strip(img_path)
            dt_after, _ = extract_best_date(img_path)
            report("Safe Metadata Strip & Date Preservation",
                   ok_strip and dt_after is not None and dt_after.year == 2023,
                   f"Preserved: {dt_after}")

        # 6. Rename Engine & Collision Handling
        sub_folder = test_dir / "Photos"
        sub_folder.mkdir(exist_ok=True)
        img_a = sub_folder / "img_a.jpg"
        img_b = sub_folder / "img_b.jpg"
        shutil.copy(img_path, img_a)
        shutil.copy(img_path, img_b)

        info_a = scanner.scan_file(img_a)
        info_b = scanner.scan_file(img_b)

        renamer = RenameEngine(date_fmt="DDMMYY", dry_run=False)
        ops = renamer.plan([info_a, info_b])
        for op in ops:
            op.execute()
        report("Rename Engine (Collision Auto _001)",
               len(ops) == 2 and ops[0].dst.name != ops[1].dst.name,
               f"{ops[0].dst.name} vs {ops[1].dst.name}")

        # 7. Logger & Restore Test
        log_file = test_dir / "rename_log.jsonl"
        logger = RenameLogger(log_path=log_file, compute_checksums=True)
        logger.log_batch(ops)
        report("Rename Logger (JSONL)", log_file.exists() and len(logger.read_entries()) == 2)

        restore_res = logger.restore_from_log(verify_checksum=False)
        report("Restore from Log", sum(1 for r in restore_res if r["success"]) == 2)

        # 8. Converter Test
        converter = ImageConverter()
        png_out = test_dir / "converted.png"
        conv_ok, conv_err = converter.convert(img_path, png_out)
        report("Format Converter (JPG -> PNG)", conv_ok and png_out.exists(), f"Error: {conv_err}")

        # 9. Organizer Test
        organizer = FileOrganizer(mode="date_year_month", dry_run=False)
        org_ops = organizer.plan([png_out], target_root=test_dir / "Organized")
        for op in org_ops:
            op.execute()
        report("File Organizer (YYYY/MM)", len(org_ops) == 1 and org_ops[0].dst.exists(),
               f"Dest: {org_ops[0].dst}")

        # 10. Duplicate Detection (pHash & DINOv2/Matrix)
        dup1 = test_dir / "dup_1.jpg"
        dup2 = test_dir / "dup_2.jpg"
        shutil.copy(img_path, dup1)
        shutil.copy(img_path, dup2)

        phash_eng = PHashEngine()
        hashes = phash_eng.compute_batch([dup1, dup2])
        groups = phash_eng.find_duplicate_groups(hashes, threshold=10)
        report("pHash Engine Grouping", len(groups) == 1 and len(groups[0]) == 2)

        dup_mgr = DupManager(phash_threshold=10)
        all_dups = dup_mgr.find_duplicates_phash([dup1, dup2])
        report("DupManager Orchestrator", len(all_dups) == 1 and len(all_dups[0].files) == 2)

        # 11. Folder Cleaner Test
        empty_dir = test_dir / "empty_subfolder"
        empty_dir.mkdir(exist_ok=True)
        cleaner = FolderCleaner(test_dir)
        empty_found = cleaner.scan()
        report("Empty Folder Cleaner", len(empty_found) >= 1)

        # 12. Inspector Test (Empty & Disguised check)
        from core.inspector import inspect_file, trim_file_overlay, repair_jpeg_header
        zero_file = test_dir / "zero.jpg"
        zero_file.touch()
        insp_zero = inspect_file(zero_file)
        report("Inspector (0-byte detection)", insp_zero["status"] == "CORRUPTED")

        # 13. Trailing Overlay Trimming Test
        overlay_jpg = test_dir / "overlay_sample.jpg"
        with open(img_path, "rb") as f:
            jpg_content = f.read()
        garbage_payload = b"EXTRA_JUNK_DATA_ZIP_OR_PAYLOAD_1234567890"
        with open(overlay_jpg, "wb") as f:
            f.write(jpg_content + garbage_payload)

        insp_overlay = inspect_file(overlay_jpg)
        report("Inspector (Overlay detection)", insp_overlay["status"] == "OVERLAY" and insp_overlay["can_trim"])

        trim_ok, bytes_cut, msg = trim_file_overlay(overlay_jpg, insp_overlay["valid_end_pos"])
        report("Trailing Overlay Trimming", trim_ok and bytes_cut == len(garbage_payload))

        # 14. JPEG Header Repair Test (SOI search)
        bad_header_jpg = test_dir / "bad_header.jpg"
        with open(bad_header_jpg, "wb") as f:
            f.write(b"CORRUPTED_PREFIX_BYTES_" + jpg_content)
        rep_ok, rep_msg = repair_jpeg_header(bad_header_jpg)
        report("JPEG Header Repair", rep_ok and "Da cat bo" in rep_msg)

        # 15. In-RAM Lossless Metadata Stripper Test
        from core.metadata import strip_jpeg_lossless_in_ram, strip_png_lossless_in_ram
        strip_test_jpg = test_dir / "strip_test.jpg"
        shutil.copy(img_path, strip_test_jpg)
        strip_ok, strip_err = strip_jpeg_lossless_in_ram(strip_test_jpg)
        report("In-RAM Lossless JPEG Stripper", strip_ok and strip_test_jpg.exists())

        # 16. Smart Auto-Keeper Duplicate Test
        from duplicate.dup_manager import select_best_keeper, DupGroup, DupFileItem
        group_test = DupGroup(
            group_id=99,
            files=[
                DupFileItem(path=Path("low_res.jpg"), similarity=1.0, engine="pHash", width=800, height=600, size_bytes=100000),
                DupFileItem(path=Path("high_res.jpg"), similarity=1.0, engine="pHash", width=3840, height=2160, size_bytes=2500000),
            ]
        )
        select_best_keeper(group_test)
        report("Smart Auto-Keeper (Keep Best Resolution)",
               group_test.files[1].action == "keep" and group_test.files[0].action == "delete")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    print(f"\n=== Test Summary: {passed} PASSED, {failed} FAILED ===")
    return failed == 0


if __name__ == "__main__":
    success = test_suite()
    sys.exit(0 if success else 1)
