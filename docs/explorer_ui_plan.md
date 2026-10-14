# Kế hoạch: Giao diện giống Windows 11 File Explorer

> Trạng thái: Gate 1 đã duyệt (2026-10-14) · **GĐ 0–1 xong** (2026-10-15) · tiếp theo: GĐ 2–3
> Quyết định đã chốt (/grill-me): giống tối đa nhưng giữ tính năng riêng · theme theo hệ thống (sáng/tối + accent) ·
> tính năng riêng đặt trên command bar + menu ⋯ · menu chuột phải kiểu Win11 + "Show more options" gốc của Shell.

## Bối cảnh kỹ thuật

- Qt 6.11 (PyQt6) có sẵn style `windows11`. Máy đích là Windows 11 build 26300, hỗ trợ Mica.
- `ContentPanel` và `TreePanel` đã dùng `QFileSystemModel`, nên giữ nguyên lớp dữ liệu.
- **Rủi ro chính:** có 132 lời gọi `setStyleSheet` trong `ui/`. Widget nào bị gắn QSS sẽ mất cách vẽ gốc của `windows11`,
  nên phải chuyển sang QPalette + style hệ thống, và chỉ tự vẽ (custom paint) cho widget đặc thù.
- Thư viện mới: `comtypes` (thuần Python, MIT) cho Shell thumbnail (`IShellItemImageFactory`) và menu gốc (`IContextMenu`).

## Các giai đoạn (mỗi giai đoạn = 1 PR, bạn dùng thử rồi phản hồi trước khi sang giai đoạn sau)

| # | Giai đoạn | Nội dung | Rủi ro |
|---|---|---|---|
| 0 | **Nền tảng theme** | `ui/theme.py`: token màu Win11 sáng/tối lấy theo hệ thống (`QStyleHints.colorScheme`, accent từ registry), đổi realtime khi Windows đổi theme; `app.setStyle("windows11")`; bỏ dần `dark_theme.qss` và 132 `setStyleSheet` | Cao: chạm gần hết UI |
| 1 | **Khung cửa sổ** | Nền Mica (DWM), thanh tiêu đề tự vẽ chứa tab, nút thu nhỏ/phóng to/đóng, **giữ Snap Layouts** (`WM_NCHITTEST`), kéo/double-click | Cao: native event Windows |
| 2 | **Hàng địa chỉ** | ← → ↑ ⟳ · breadcrumb phẳng, mũi tên `>` mở danh sách thư mục cùng cấp, click vùng trống thì sang chế độ gõ đường dẫn · ô "Tìm trong <thư mục>" | Thấp |
| 3 | **Command bar** | New ▾ · Cut · Copy · Paste · Rename · Share · Delete │ Sort ▾ · View ▾ · **Công cụ ▾** (Đổi tên hàng loạt, Chuyển đổi, Metadata, Sắp xếp, Dọn thư mục rỗng, Trùng lặp, Kiểm định, Thống kê) · ⋯ (Cài đặt, Khôi phục log, Logcat). Bỏ thanh icon ở đáy. Cut/Copy/Paste dùng clipboard chuẩn (CF_HDROP), nên dán qua lại được với Explorer thật | Trung bình |
| 4 | **Khung điều hướng** | Home (mục ghim), OneDrive, **This PC** (ổ đĩa + dung lượng), Network; ẩn file/thư mục ẩn theo cài đặt Explorer | Trung bình |
| 5 | **Vùng nội dung** | Mặc định Details (Name / Date modified / Type / Size); 8 chế độ xem (Extra large…Content); **thumbnail Shell thật** chạy nền + cache; Ctrl+cuộn chuột đổi cỡ icon | Cao: hiệu năng |
| 6 | **Menu chuột phải** | Menu Win11 tự vẽ (hàng icon Cut/Copy/Rename/Share/Delete, Open, Open with, Công cụ ▸) + **"Show more options"** mở menu Shell gốc (7-Zip, Open with…) | Cao: COM |
| 7 | **Thanh trạng thái + khung chi tiết** | "N mục · M đã chọn · dung lượng" + nút chuyển Details/Icons; khung Preview/Details bật tắt như Explorer | Thấp |
| 8 | **Trang Trùng lặp / Kiểm định** | Bỏ 3 tab lớn; mở như một "trang" trong vùng nội dung (giống Home/Gallery), restyle theo token | Trung bình |
| 9 | **Hoàn thiện** | Segoe Fluent Icons, hiệu ứng hover/chọn, phím tắt giống Explorer (F2, Del, Ctrl+Shift+N, Alt+Enter mở Properties gốc), kiểm tra a11y/tương phản | Thấp |

## Ghi chú kỹ thuật đã kiểm chứng (GĐ 1)

- **Không dùng `FramelessWindowHint`**: frameless + `WA_TranslucentBackground` khiến Qt tạo cửa sổ
  `WS_EX_LAYERED`, pixel trong suốt bị xuyên chuột, không có Mica, không có nút DWM.
- **Không dùng `ExpandedClientAreaHint`** (Qt 6.9+): Qt tự vẽ icon + chữ tiêu đề đè lên vùng tab.
- Cách dùng: giữ khung native, `WM_NCCALCSIZE` trả 0, nút caption do DWM vẽ (`DwmDefWindowProc`).
- PyQt6 6.11: `nativeEvent` phải trả `(False, 0)`; trả kết quả của `super()` (`(False, None)`) gây crash.

## Định nghĩa hoàn thành (DoD) cho mỗi giai đoạn

- 79 test hiện có vẫn xanh; thêm test cho logic mới (theme token, model, clipboard, shell COM wrapper).
- **Ảnh chụp đặt cạnh nhau**: app (chụp tự động) và Explorer (ảnh bạn gửi), ở cả sáng lẫn tối.
- Hiệu năng: thư mục khoảng 5.000 file không làm đơ UI (logcat watchdog không báo ANR), thumbnail tải dần.
- Bạn dùng thử thật và duyệt trước khi sang giai đoạn kế.

## Đội ngũ & Kỹ năng (Team & Skill Matrix)

| Vai trò / Agent | Phạm vi tệp độc quyền | Kỹ năng | Trách nhiệm |
|---|---|---|---|
| **Primary (Claude)** | `ui/**`, `ui/theme.py`, `utils/shell_*.py`, `tests/**` | `python-patterns`, `python-testing` | Triển khai tuần tự từng giai đoạn |
| **`python-reviewer`** | Toàn bộ diff (read-only) | `python-coding-style` | Gate 2 mỗi PR |
| **`performance-optimizer`** | `ui/panels/content_panel.py`, `utils/shell_thumbs.py` (read-only) | — | Giai đoạn 5: thumbnail, cache, ANR |
| **`a11y-architect`** | `ui/**` (read-only) | `accessibility` | Giai đoạn 9: tương phản, bàn phím, screen reader |
| **`silent-failure-hunter`** | `utils/shell_*.py` (read-only) | `error-handling` | Giai đoạn 5–6: lỗi COM bị nuốt |

Các agent review chỉ đọc và chạy sau khi giai đoạn code xong, nên không có hai agent sửa cùng một file.

## Cần từ người dùng

1. Ảnh chụp Explorer trên máy bạn (sáng + tối): thanh trên cùng, khung trái, Details, Large icons, menu chuột phải, menu "⋯".
2. Đường dẫn một thư mục mẫu lớn (ảnh / video / RAW, khoảng vài nghìn file) để đo hiệu năng.
3. Duyệt Gate 1 cho plan này, và dùng thử + phản hồi sau mỗi PR.
