"""
tests/test_inspector_security.py
Unit tests for inspector, security, and lossless in-memory stripper.
Runs with standard Python libraries + send2trash.
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.inspector import inspect_file, repair_jpeg_header, trim_file_overlay
from core.security import AmsiScanner, quarantine_file
from core.metadata import strip_jpeg_lossless_in_ram, strip_png_lossless_in_ram


def run_tests():
    test_dir = Path(tempfile.mkdtemp(prefix="test_sec_insp_"))
    passed = 0
    failed = 0

    def report(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  [PASS] {name} {detail}")
        else:
            failed += 1
            print(f"  [FAIL] {name} - {detail}")

    try:
        print(f"=== Testing Inspector & Security Subsystems in {test_dir} ===\n")

        # 1. Zero byte file
        f_zero = test_dir / "zero.jpg"
        f_zero.touch()
        res_zero = inspect_file(f_zero)
        report("Zero byte file detection", res_zero["status"] == "CORRUPTED")

        # 2. Corrupt block
        f_corrupt = test_dir / "corrupt_dump.jpg"
        with open(f_corrupt, "wb") as f:
            f.write(b"\x00" * 1024)
        res_corrupt = inspect_file(f_corrupt)
        report("Corrupted null-block detection", res_corrupt["status"] == "CORRUPTED")

        # 3. Disguised PE (MZ header)
        f_pe = test_dir / "invoice.jpg"
        with open(f_pe, "wb") as f:
            f.write(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 200)
        res_pe = inspect_file(f_pe)
        report("Disguised PE detection", res_pe["status"] == "THREAT" and res_pe["threat_type"] == "DISGUISED_PE")

        # 4. WebShell in image
        f_shell = test_dir / "avatar.png"
        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
        with open(f_shell, "wb") as f:
            f.write(fake_png + b"<?php eval($_POST['cmd']); ?>\x00\x00\x00\x00IEND\xaeB`\x82")
        res_shell = inspect_file(f_shell)
        report("WebShell injection detection", res_shell["status"] == "THREAT" and res_shell["threat_type"] == "SCRIPT_INJECTION")

        # 5. Trailing overlay on JPEG
        # Minimal valid JPEG
        valid_jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
            b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00"
            b"\xff\xd9"
        )
        overlay_payload = b"PAYLOAD_ZIP_CONCEALED_12345"
        f_overlay = test_dir / "sample_overlay.jpg"
        with open(f_overlay, "wb") as f:
            f.write(valid_jpeg + overlay_payload)

        res_overlay = inspect_file(f_overlay)
        report("Trailing overlay detection", res_overlay["status"] == "OVERLAY" and res_overlay["can_trim"])

        # Trim overlay
        ok_trim, cut_len, trim_msg = trim_file_overlay(f_overlay, res_overlay["valid_end_pos"])
        report("In-place overlay trimming", ok_trim and cut_len == len(overlay_payload))
        report("Post-trim verification", f_overlay.stat().st_size == len(valid_jpeg))

        # 6. JPEG Header Repair
        f_bad_hdr = test_dir / "bad_hdr.jpg"
        with open(f_bad_hdr, "wb") as f:
            f.write(b"CORRUPTED_PREFIX_GARBAGE_" + valid_jpeg)
        ok_rep, msg_rep = repair_jpeg_header(f_bad_hdr)
        report("JPEG Header Repair", ok_rep and f_bad_hdr.stat().st_size == len(valid_jpeg))

        # 7. In-RAM JPEG Lossless Metadata Stripper
        f_strip_jpg = test_dir / "strip_me.jpg"
        # Add a comment marker 0xFE to JPEG
        comment_seg = b"\xff\xfe\x00\x08Hello!"
        jpeg_with_com = valid_jpeg[:2] + comment_seg + valid_jpeg[2:]
        with open(f_strip_jpg, "wb") as f:
            f.write(jpeg_with_com)
        ok_strip, err_strip = strip_jpeg_lossless_in_ram(f_strip_jpg)
        report("In-RAM JPEG Lossless Stripper", ok_strip and b"Hello!" not in f_strip_jpg.read_bytes())

        # 8. AMSI Scanner
        amsi = AmsiScanner()
        report("AMSI Scanner Initialization", amsi.available is True)
        if amsi.available:
            detected, code, desc = amsi.scan_buffer(b"Hello clean buffer", "test.txt")
            report("AMSI Clean Buffer Scan", detected is False)
        amsi.close()

        # 9. Quarantine Vault Manager
        q_dir = test_dir / "_Quarantine"
        f_malware = test_dir / "eicar_mock.txt"
        f_malware.write_text("Mock threat content for quarantine testing")
        q_ok, q_target = quarantine_file(f_malware, q_dir, "TEST_THREAT", "Mock threat details")
        report("Quarantine file movement", q_ok and Path(q_target).exists() and not f_malware.exists())
        log_file = q_dir / "quarantine_log.txt"
        report("Quarantine log generation", log_file.exists() and "TEST_THREAT" in log_file.read_text(encoding="utf-8"))

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    print(f"\n=== Result: {passed} PASSED, {failed} FAILED ===")
    return failed == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_tests() else 1)
