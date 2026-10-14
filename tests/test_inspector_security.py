"""
tests/test_inspector_security.py
Unit tests for inspector, security, and lossless in-memory stripper.
Wrapped in unittest.TestCase for proper discoverability and test isolation.
"""
from __future__ import annotations

import base64
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from core.inspector import inspect_file, repair_jpeg_header, trim_file_overlay
from core.security import AmsiScanner, quarantine_file
from core.metadata import strip_jpeg_lossless_in_ram, strip_png_lossless_in_ram


class TestInspectorSecurity(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_sec_insp_"))
        self.valid_jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
            b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00"
            b"\xff\xd9"
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_zero_byte_file(self):
        f_zero = self.test_dir / "zero.jpg"
        f_zero.touch()
        res_zero = inspect_file(f_zero)
        self.assertEqual(res_zero["status"], "CORRUPTED")

    def test_corrupted_null_block(self):
        f_corrupt = self.test_dir / "corrupt_dump.jpg"
        f_corrupt.write_bytes(b"\x00" * 1024)
        res_corrupt = inspect_file(f_corrupt)
        self.assertEqual(res_corrupt["status"], "CORRUPTED")

    def test_disguised_pe(self):
        # Dynamically build MZ header to avoid static AV signature
        mz = bytes([0x4D, 0x5A, 0x90, 0x00, 0x03, 0x00]) + b"\x00" * 200
        f_pe = self.test_dir / "invoice.jpg"
        f_pe.write_bytes(mz)
        res_pe = inspect_file(f_pe)
        self.assertEqual(res_pe["status"], "THREAT")
        self.assertEqual(res_pe["threat_type"], "DISGUISED_PE")

    def test_webshell_injection(self):
        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
        script_payload = b"<script>evil()</script>"
        f_shell = self.test_dir / "avatar.png"
        f_shell.write_bytes(fake_png + script_payload + b"\x00\x00\x00\x00IEND\xaeB`\x82")
        res_shell = inspect_file(f_shell)
        self.assertEqual(res_shell["status"], "THREAT")
        self.assertEqual(res_shell["threat_type"], "SCRIPT_INJECTION")

    def test_trailing_overlay_and_trim(self):
        overlay_payload = b"PAYLOAD_ZIP_CONCEALED_12345"
        f_overlay = self.test_dir / "sample_overlay.jpg"
        f_overlay.write_bytes(self.valid_jpeg + overlay_payload)

        res_overlay = inspect_file(f_overlay)
        self.assertEqual(res_overlay["status"], "OVERLAY")
        self.assertTrue(res_overlay["can_trim"])

        ok_trim, cut_len, _ = trim_file_overlay(f_overlay, res_overlay["valid_end_pos"])
        self.assertTrue(ok_trim)
        self.assertEqual(cut_len, len(overlay_payload))
        self.assertEqual(f_overlay.stat().st_size, len(self.valid_jpeg))

    def test_jpeg_header_repair(self):
        f_bad_hdr = self.test_dir / "bad_hdr.jpg"
        f_bad_hdr.write_bytes(b"CORRUPTED_PREFIX_GARBAGE_" + self.valid_jpeg)
        ok_rep, _ = repair_jpeg_header(f_bad_hdr)
        self.assertTrue(ok_rep)
        self.assertEqual(f_bad_hdr.stat().st_size, len(self.valid_jpeg))

    def test_strip_jpeg_lossless_in_ram(self):
        f_strip_jpg = self.test_dir / "strip_me.jpg"
        comment_seg = b"\xff\xfe\x00\x08Hello!"
        jpeg_with_com = self.valid_jpeg[:2] + comment_seg + self.valid_jpeg[2:]
        f_strip_jpg.write_bytes(jpeg_with_com)

        ok_strip, err_strip = strip_jpeg_lossless_in_ram(f_strip_jpg)
        self.assertTrue(ok_strip)
        self.assertNotIn(b"Hello!", f_strip_jpg.read_bytes())

    def test_amsi_scanner(self):
        amsi = AmsiScanner()
        if amsi.available:
            detected, code, desc = amsi.scan_buffer(b"Hello clean buffer", "test.txt")
            self.assertFalse(detected)
        amsi.close()

    def test_quarantine_vault_manager(self):
        q_dir = self.test_dir / "_Quarantine"
        f_mock = self.test_dir / "sample_test.txt"
        f_mock.write_text("Mock threat content for quarantine testing", encoding="utf-8")
        q_ok, q_target = quarantine_file(f_mock, q_dir, "TEST_THREAT", "Mock threat details")
        self.assertTrue(q_ok)
        self.assertTrue(Path(q_target).exists())
        self.assertFalse(f_mock.exists())
        log_file = q_dir / "quarantine_log.txt"
        self.assertTrue(log_file.exists())
        self.assertIn("TEST_THREAT", log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
