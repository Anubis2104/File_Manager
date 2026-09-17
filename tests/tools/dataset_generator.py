"""
==============================================================================
TOOL: Dataset Generator & Tree Replicator for Stress Testing
Author: QA Engineering Team
Target Directory: Configurable via CLI argument (default: ./Pictures)
==============================================================================
"""

import os
import sys
import shutil
import stat
import random
import string
import struct
from pathlib import Path
from typing import List, Tuple

# Cấu hình UTF-8 cho stdout/stderr trên Windows để tránh lỗi UnicodeEncodeError
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Thư mục mục tiêu: Lấy từ tham số dòng lệnh nếu có, hoặc mặc định thư mục Pictures cùng cấp script
DEFAULT_TARGET_DIR = Path(__file__).resolve().parent / "Pictures"
TARGET_DIR = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_TARGET_DIR)

# -----------------------------------------------------------------------------
# 1. HÀM TẠO ẢNH RAW NHỎ HỢP LỆ (Không cần thư viện Pillow)
# -----------------------------------------------------------------------------
def create_valid_1x1_png(filepath: Path):
    """Tạo 1 file PNG 1x1 pixel hợp lệ bằng binary thô."""
    png_data = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00'
        b'\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    fp = Path(filepath)
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, 'wb') as f:
        f.write(png_data)

def create_corrupted_jpeg(filepath: Path):
    """Tạo file có header JPEG nhưng dữ liệu sau đó bị hỏng/cắt cụt."""
    # Header chuẩn JPEG (SOI, APP0 marker) + dữ liệu rác
    corrupted_data = b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00' + os.urandom(128)
    fp = Path(filepath)
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, 'wb') as f:
        f.write(corrupted_data)

def create_fake_image_from_text(filepath: Path):
    """Tạo file chứa văn bản thuần nhưng mang đuôi mở rộng .jpg / .png."""
    fp = Path(filepath)
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, 'w', encoding='utf-8') as f:
        f.write("This is a plain text file pretending to be an image. QA Edge Case.")

# -----------------------------------------------------------------------------
# 2. HÀM DUYỆT CÂY & NHÂN BẢN FILE HIỆN CÓ (Tree Replicator)
# -----------------------------------------------------------------------------
def replicate_existing_tree(root_dir: str, clones_count: int = 3):
    """
    Duyệt đệ quy toàn bộ thư mục và nhân bản các file với nhiều biến thể tên khác nhau.
    """
    print(f"\n[*] Đang quét và nhân bản cây thư mục tại: {root_dir}")
    source_files = []
    
    for dirpath, _, filenames in os.walk(root_dir):
        # Tránh quét vào các thư mục QA đặc biệt để tránh nhân bản lặp vô hạn khi chạy lại script
        if any(skip in dirpath for skip in ["QA_Edge_Cases", "QA_Test_Empty_Folders", "Replica_Level_"]):
            continue
        for fname in filenames:
            full_path = Path(dirpath) / fname
            # Bỏ qua các file do script vừa tạo nếu chạy lại
            if "_qa_replica_" not in fname and "_edge_" not in fname and "_nested_clone_" not in fname:
                source_files.append(full_path)

    print(f"    -> Tìm thấy {len(source_files)} file gốc ban đầu.")
    if not source_files:
        print("    [!] Không có file gốc sẵn có. Script sẽ tự tạo dữ liệu mẫu khởi đầu.")
        sample_init_dir = Path(root_dir) / "Initial_Sample"
        sample_init_dir.mkdir(parents=True, exist_ok=True)
        create_valid_1x1_png(sample_init_dir / "sample_base.png")
        source_files.append(sample_init_dir / "sample_base.png")

    created_count = 0
    for src in source_files:
        parent_dir = src.parent
        stem = src.stem
        suffix = src.suffix
        
        for i in range(1, clones_count + 1):
            # Nhân bản trong cùng thư mục
            clone_name_1 = f"{stem}_qa_replica_copy_{i}{suffix}"
            dest_1 = parent_dir / clone_name_1
            try:
                shutil.copy2(src, dest_1)
                created_count += 1
            except Exception as e:
                print(f"    [!] Lỗi khi nhân bản {dest_1}: {e}")

            # Nhân bản sang thư mục con phụ
            sub_replica_dir = parent_dir / f"Replica_Level_{i}"
            sub_replica_dir.mkdir(exist_ok=True)
            dest_2 = sub_replica_dir / f"{stem}_nested_clone_{i}{suffix}"
            try:
                shutil.copy2(src, dest_2)
                created_count += 1
            except Exception as e:
                print(f"    [!] Lỗi khi nhân bản nested {dest_2}: {e}")

    print(f"    [+] Đã tạo thành công {created_count} bản sao nhân bản.")

# -----------------------------------------------------------------------------
# 3. TẠO HÀNG LOẠT THƯ MỤC RỖNG (Empty Directories)
# -----------------------------------------------------------------------------
def create_empty_directories(root_dir: str):
    """Tạo thư mục rỗng nhiều cấp độ và phân nhánh."""
    print("\n[*] Đang tạo hàng loạt thư mục rỗng (Empty Folders)...")
    base_empty = Path(root_dir) / "QA_Test_Empty_Folders"
    base_empty.mkdir(parents=True, exist_ok=True)

    # 1. Thư mục rỗng cấp 1
    for i in range(1, 15):
        try:
            (base_empty / f"empty_folder_{i:03d}").mkdir(exist_ok=True)
        except Exception as e:
            print(f"    [!] Lỗi tạo thư mục empty_folder_{i:03d}: {e}")

    # 2. Thư mục rỗng lồng sâu nhiều cấp (Deeply nested empty hierarchy)
    try:
        deep_path = base_empty / "nested_level_1" / "nested_level_2" / "nested_level_3" / "nested_level_4" / "nested_level_5"
        deep_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"    [!] Lỗi tạo chuỗi thư mục lồng sâu: {e}")

    # 3. Thư mục có ký tự lạ nhưng rỗng
    for folder_name in [
        "Thư mục rỗng tiếng Việt có dấu",
        "empty_folder_with_space_at_end",
        ".hidden_empty_folder"
    ]:
        try:
            (base_empty / folder_name).mkdir(exist_ok=True)
        except Exception as e:
            print(f"    [!] Lỗi tạo thư mục '{folder_name}': {e}")
    
    print("    [+] Đã tạo 20+ thư mục rỗng với nhiều cấu trúc lồng ghép.")

# -----------------------------------------------------------------------------
# 4. TẠO TẬP DỮ LIỆU EDGE CASES (Dữ liệu biên, dị biệt, lỗi)
# -----------------------------------------------------------------------------
def create_edge_case_files(root_dir: str):
    """Tạo toàn diện các loại file biên, file lỗi, file độc hại, file hệ thống."""
    print("\n[*] Đang tạo dữ liệu kiểm thử biên (Edge Cases & Malformed Files)...")
    edge_dir = Path(root_dir) / "QA_Edge_Cases"
    edge_dir.mkdir(parents=True, exist_ok=True)

    # A. Tệp 0-byte (Zero-byte files)
    zero_dir = edge_dir / "01_Zero_Byte_Files"
    zero_dir.mkdir(exist_ok=True)
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".raw", ""]:
        fname = f"zero_byte_file{ext}"
        try:
            (zero_dir / fname).touch()
        except Exception as e:
            print(f"    [!] Lỗi tạo 0-byte file {fname}: {e}")

    # B. Tệp ảnh bị hỏng cấu trúc (Corrupted Images)
    corrupt_dir = edge_dir / "02_Corrupted_Images"
    corrupt_dir.mkdir(exist_ok=True)
    create_corrupted_jpeg(corrupt_dir / "corrupted_header_only.jpg")
    create_corrupted_jpeg(corrupt_dir / "corrupted_partial_stream.jpeg")
    create_fake_image_from_text(corrupt_dir / "fake_image_text_content.png")
    create_fake_image_from_text(corrupt_dir / "fake_image_text_content.jpg")
    
    # File hoàn toàn là byte rác ngẫu nhiên
    try:
        with open(corrupt_dir / "random_garbage_bytes.png", "wb") as f:
            f.write(os.urandom(1024 * 50))  # 50KB rác
    except Exception as e:
        print(f"    [!] Lỗi tạo file byte rác: {e}")

    # C. Tên file & thư mục chứa ký tự Unicode phức tạp / Tiếng Việt / Emojis
    unicode_dir = edge_dir / "03_Unicode_Special_Chars_Tiếng_Việt_🔥"
    unicode_dir.mkdir(exist_ok=True)
    
    special_names = [
        "ảnh_du_lịch_đà_nẵng_hội_an_2026_🇻🇳.jpg",
        "file with multiple   spaces   inside.png",
        " leading_space.jpg",
        "trailing_space.png",
        "symbols_#@!$%^&()_+[]{}~`,.jpg",
        "semi;colon_and'single_quote'double.png",
        "tên_rất_dài_được_tạo_ra_nhằm_kiểm_tra_độ_dài_chuỗi_ký_tự_unicode_tiếng_việt_có_dấu_hoàn_chỉnh_trên_hệ_điều_hành_windows.jpg",
        "mixed_case_EXTENSIONS.PnG",
        "CAPITAL_EXTENSION.JPG",
        "double_extension.jpg.png.jpg",
        ".only_extension.jpg",
        "no_extension_file"
    ]
    for name in special_names:
        try:
            create_valid_1x1_png(unicode_dir / name)
        except Exception as e:
            print(f"    [!] Lỗi tạo file edge case '{name}': {e}")

    # D. File trùng lặp hoàn toàn nội dung (Exact Duplicates)
    dup_dir = edge_dir / "04_Exact_Duplicates"
    dup_dir.mkdir(exist_ok=True)
    origin_dup = dup_dir / "original_source_image.png"
    create_valid_1x1_png(origin_dup)
    for i in range(1, 6):
        try:
            shutil.copy2(origin_dup, dup_dir / f"duplicate_hash_match_{i}.png")
        except Exception as e:
            print(f"    [!] Lỗi khi nhân bản file duplicate {i}: {e}")
    
    # Thêm 1 duplicate đặt ở thư mục con khác
    dup_sub = dup_dir / "sub_dup_folder"
    dup_sub.mkdir(exist_ok=True)
    try:
        shutil.copy2(origin_dup, dup_sub / "duplicate_in_another_dir.png")
    except Exception as e:
        print(f"    [!] Lỗi khi nhân bản file duplicate sang sub folder: {e}")

    # E. File chỉ đọc (Read-only) để kiểm tra xử lý PermissionError khi xóa/di chuyển
    readonly_dir = edge_dir / "05_Read_Only_Locked"
    readonly_dir.mkdir(exist_ok=True)
    ro_file = readonly_dir / "read_only_image.jpg"
    # Nếu file đã tồn tại ở trạng thái read-only từ lần chạy trước, cần mở quyền ghi trước khi ghi đè
    if ro_file.exists():
        try:
            os.chmod(ro_file, stat.S_IWRITE)
        except Exception:
            pass
    create_valid_1x1_png(ro_file)
    try:
        # Gán thuộc tính read-only
        os.chmod(ro_file, stat.S_IREAD)
    except Exception as e:
        print(f"    [!] Lỗi gán quyền read-only cho {ro_file}: {e}")

    # F. Tệp tin hệ thống và tệp ẩn (System & Hidden files)
    sys_dir = edge_dir / "06_Hidden_And_System_Files"
    sys_dir.mkdir(exist_ok=True)
    create_valid_1x1_png(sys_dir / ".hidden_dot_image.jpg")
    create_fake_image_from_text(sys_dir / "Thumbs.db")
    create_fake_image_from_text(sys_dir / ".DS_Store")
    create_fake_image_from_text(sys_dir / "desktop.ini")

    # G. Đường dẫn cực dài (Long Path Limit Testing)
    try:
        long_dir = edge_dir
        for step in range(6):
            long_dir = long_dir / f"nested_folder_with_very_long_name_level_{step}_testing_path_limits"
            long_dir.mkdir(exist_ok=True)
        create_valid_1x1_png(long_dir / "test_long_path_end_file.png")
    except Exception as e:
        print(f"    [!] Gặp giới hạn MAX_PATH của Windows khi tạo Long Path: {e}")

    print("    [+] Đã hoàn thành tạo toàn bộ các kịch bản dữ liệu biên (Edge Cases).")

# -----------------------------------------------------------------------------
# 5. HÀM TỔNG KẾT & IN THỐNG KÊ DATASET
# -----------------------------------------------------------------------------
def print_dataset_summary(root_dir: str):
    """Thống kê tổng số file, folder và dung lượng sau khi tạo."""
    total_files = 0
    total_dirs = 0
    total_size = 0
    extensions_stat = {}

    for dirpath, dirnames, filenames in os.walk(root_dir):
        total_dirs += len(dirnames)
        for f in filenames:
            total_files += 1
            fp = Path(dirpath) / f
            try:
                size = fp.stat().st_size
                total_size += size
                ext = fp.suffix.lower() if fp.suffix else "(no_ext)"
                extensions_stat[ext] = extensions_stat.get(ext, 0) + 1
            except Exception:
                pass

    print("\n" + "=" * 60)
    print(f"  TỔNG KẾT DỮ LIỆU KIỂM THỬ TẠI: {root_dir}")
    print("=" * 60)
    print(f"  • Tổng số thư mục (Folders): {total_dirs}")
    print(f"  • Tổng số tệp tin (Files)  : {total_files}")
    print(f"  • Tổng dung lượng ước tính  : {total_size / 1024:.2f} KB")
    print("\n  • Phân bổ theo phần mở rộng (Extensions):")
    for ext, count in sorted(extensions_stat.items(), key=lambda x: x[1], reverse=True):
        print(f"    - {ext:<12}: {count:>5} files")
    print("=" * 60)

# -----------------------------------------------------------------------------
# MAIN EXECUTION
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("================================================================")
    print(" BẮT ĐẦU KHỞI TẠO BỘ DỮ LIỆU KIỂM THỬ CHO PYTHON APP")
    print(f" Thư mục mục tiêu: {TARGET_DIR}")
    print("================================================================")

    # Đảm bảo thư mục gốc tồn tại
    target_path = Path(TARGET_DIR)
    target_path.mkdir(parents=True, exist_ok=True)

    # 1. Nhân bản cây thư mục hiện có
    replicate_existing_tree(TARGET_DIR, clones_count=3)

    # 2. Tạo hàng loạt thư mục rỗng
    create_empty_directories(TARGET_DIR)

    # 3. Tạo các file edge case, lỗi cấu trúc, unicode, permissions
    create_edge_case_files(TARGET_DIR)

    # 4. Thống kê toàn diện
    print_dataset_summary(TARGET_DIR)
    print("\n[V] ĐÃ HOÀN TẤT VIỆC TẠO DỮ LIỆU TEST!")