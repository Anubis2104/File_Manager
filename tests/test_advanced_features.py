"""
tests/test_advanced_features.py
Tests for MediaExtractor, ArgfileMetadataEngine, TransactionManager, and DupRenameWorker.
"""
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image
import piexif

from utils.media_extractor import MediaExtractor
from core.metadata import ArgfileMetadataEngine, MetadataEngine
from core.logger import TransactionManager, RenameLogger
from duplicate.phash_engine import PHashEngine, DisjointSetUnion
from core.workers import DupRenameWorker


def test_advanced():
    test_dir = Path(tempfile.mkdtemp(prefix="fmpro_adv_test_"))
    print(f"=== Running Advanced Feature Tests in {test_dir} ===\n")
    passed = 0
    failed = 0

    def report(name: str, success: bool, detail: str = ""):
        nonlocal passed, failed
        if success:
            passed += 1
            print(f"  [PASS] {name} {detail}")
        else:
            failed += 1
            print(f"  [FAIL] {name} - {detail}")

    try:
        # 1. Test DisjointSetUnion
        dsu = DisjointSetUnion(6)
        dsu.union(0, 1)
        dsu.union(1, 2)
        dsu.union(3, 4)
        from collections import defaultdict
        groups_dict = defaultdict(list)
        for i in range(6):
            groups_dict[dsu.find(i)].append(i)
        groups = [g for g in groups_dict.values() if len(g) > 1]
        report("DSU Grouping", len(groups) == 2 and set(groups[0]) == {0, 1, 2} and set(groups[1]) == {3, 4})

        # 2. Test MediaExtractor on PIL Image
        img_p = test_dir / "sample.jpg"
        img = Image.new("RGB", (128, 128), color=(200, 100, 50))
        img.save(img_p)

        extractor = MediaExtractor()
        t = extractor.extract_image_tensor(img_p)
        report("MediaExtractor Image Tensor", t is not None and t.shape == (1, 1, 32, 32), f"Shape: {t.shape if t is not None else 'None'}")

        # 3. Test ArgfileMetadataEngine batch rewrite & scan
        arg_engine = ArgfileMetadataEngine()
        img2_p = test_dir / "sample2.jpg"
        img.save(img2_p)

        tags = {"Artist": "QA Engineer", "Copyright": "FileManagerPro 2026", "UserComment": "Automated Test"}
        updated_count = arg_engine.rewrite_tags_batch([img_p, img2_p], tags=tags)
        report("ArgfileMetadataEngine Rewrite Tags Batch", updated_count == 2, f"Updated: {updated_count}/2")

        scanned_tags = arg_engine.scan_tags_batch([img_p, img2_p])
        report("ArgfileMetadataEngine Scan Tags Batch", len(scanned_tags) == 2, f"Scanned: {len(scanned_tags)}")


        # 4. Test TransactionManager WAL and Rollback
        tx = TransactionManager(log_dir=test_dir)
        
        file_to_rename = test_dir / "orig_name.jpg"
        img.save(file_to_rename)
        target_name = test_dir / "new_name.jpg"

        tx.log("RENAME", {"src": str(file_to_rename), "dst": str(target_name)})
        shutil.move(file_to_rename, target_name)
        report("TransactionManager Log", tx.wal_path.exists() and target_name.exists())

        rb_results = tx.rollback()
        report("TransactionManager Rollback", len(rb_results) == 1 and file_to_rename.exists() and not target_name.exists())
        tx.close()


        # 5. Test pHash Batch GEMM
        phash_eng = PHashEngine()
        hashes = phash_eng.compute_batch([img_p, img2_p])
        groups = phash_eng.find_duplicate_groups(hashes, threshold=10)
        report("PHashEngine Batch GEMM", len(groups) == 1 and len(groups[0]) == 2)

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    print(f"\n=== Advanced Summary: {passed} PASSED, {failed} FAILED ===")
    # pytest ignores return values — the suite must assert to be able to fail
    assert failed == 0, f"{failed} check(s) failed, see [FAIL] lines above"


if __name__ == "__main__":
    try:
        test_advanced()
    except AssertionError as exc:
        print(exc)
        sys.exit(1)
    sys.exit(0)
