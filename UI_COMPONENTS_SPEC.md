# 📑 TÀI LIỆU ĐẶC TẢ THÀNH PHẦN GIAO DIỆN & TIÊU CHÍ NHẬN DIỆN LỖI
### Dự án: **FileManagerPro**
> *Tài liệu được xây dựng theo phương pháp **Spec-Driven Development (spec-kit)** và quy chuẩn kiểm thử/đánh giá mã nguồn (**code-reviewer**).*

---

## 🗺️ 1. TỔNG QUAN KIẾN TRÚC GIAO DIỆN

Giao diện ứng dụng được thiết kế theo mô hình **Windows File Explorer hiện đại**, tích hợp đa tầng xử lý đa luồng (QThread), chia thành 5 khu vực chính:
1. **Thanh điều hướng & Công cụ trên cùng (Top Toolbars)**: Lịch sử di chuyển, thanh địa chỉ, ô tìm kiếm và các nút tác vụ nhanh.
2. **Cây thư mục bên trái (Tree Panel)**: Cấu trúc phân cấp ổ đĩa và thư mục.
3. **Khu vực trung tâm đa tab (Central Tab Widget)**:
   - **Tab 1: Duyệt tệp tin (Content Panel)**: Chế độ Grid (Lưới icon) và Detail (Bảng chi tiết).
   - **Tab 2: Tệp trùng lặp (Duplicate Preview Panel)**: Quản lý nhóm ảnh/video trùng lặp thị giác.
   - **Tab 3: Kiểm định & Bảo mật (Inspector Panel)**: Quét nhị phân 5 lớp, gọt trailing overlay, diệt mã độc AMSI.
4. **Khung xem trước bên phải (Preview Panel)**: Xem trước hình ảnh, thông số kỹ thuật và siêu dữ liệu EXIF.
5. **Thanh tiến trình nổi (Progress Banner) & Thanh trạng thái dưới cùng (Status Bar)**.

---

## 🎛️ 2. CHI TIẾT TỪNG THÀNH PHẦN GIAO DIỆN & DẤU HIỆU NHẬN BIẾT LỖI

---

### PHẦN I: THANH ĐIỀU HƯỚNG CHÍNH (AppToolBar)
*Tệp mã nguồn: [`ui/widgets/toolbar.py`](ui/widgets/toolbar.py)*

| Thành phần | Mã định danh / Ký hiệu | Thao tác tương tác | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- | :--- | :--- |
| **Nút Quay lại (Back)** | `btn_back` (`←`) | Nhấp chuột trái hoặc nhấn `Alt + Left` | Trở về thư mục vừa duyệt trước đó trong lịch sử (`_history`). Nút tự động làm mờ (Disable) khi không còn lịch sử quay lại. | <ul><li>Bấm vào nhưng thư mục không đổi hoặc nhảy sai thư mục.</li><li>Vừa mở app chưa đi đâu nhưng nút vẫn sáng (Enable).</li><li>Đã duyệt qua 3-4 thư mục nhưng nút vẫn bị mờ (Disable) không cho bấm.</li><li>Quay lại nhưng ô địa chỉ không cập nhật theo.</li></ul> |
| **Nút Tiến lên (Forward)** | `btn_fwd` (`→`) | Nhấp chuột trái hoặc nhấn `Alt + Right` | Tiến tới thư mục tiếp theo sau khi đã nhấn Back. Tự động Disable nếu đang ở thư mục mới nhất. | <ul><li>Đã bấm Back rồi nhưng nút Forward vẫn bị Disable.</li><li>Khi duyệt vào một thư mục mới tinh thì nút Forward lại sáng lên (vi phạm logic xoá nhánh forward).</li><li>Bấm vào gây văng ứng dụng do index lịch sử vượt quá độ dài `_history`.</li></ul> |
| **Nút Lên thư mục cha (Up)** | `btn_up` (`↑`) | Nhấp chuột trái hoặc nhấn `Alt + Up` | Nhảy lên thư mục cấp cha trực tiếp (`path.parent`). | <ul><li>Đang ở thư mục con nhưng bấm Up không phản hồi.</li><li>Đang ở gốc ổ đĩa (ví dụ `D:\`) bấm Up làm treo ứng dụng hoặc lặp vô tận.</li><li>Nội dung hiển thị lên thư mục cha nhưng Cây thư mục bên trái không cuộn theo.</li></ul> |
| **Thanh địa chỉ (Address Bar)** | `address_bar` (`QLineEdit`) | Nhấp chuột nhập văn bản, nhấn `Enter` hoặc `Ctrl + L` | Hiển thị đường dẫn hiện tại; cho phép dán/nhập đường dẫn bất kỳ rồi nhấn Enter để điều hướng tức thì. | <ul><li>Nhập đường dẫn hợp lệ và gõ Enter nhưng không chuyển thư mục.</li><li>Nhập đường dẫn sai/không tồn tại nhưng khung viền không đổi sang màu đỏ cảnh báo (`border-color: #ff453a`).</li><li>Bị đóng băng (Freeze) giao diện khi nhập đường dẫn mạng UNC hoặc ổ đĩa bị ngắt kết nối.</li></ul> |
| **Ô tìm kiếm nhanh** | `search_bar` (`QLineEdit`) | Nhập ký tự hoặc nhấn `Ctrl + F` | Lọc tức thì (Real-time filter) danh sách tệp/thư mục ở panel giữa theo chuỗi con (substring) vừa gõ. | <ul><li>Gõ ký tự vào nhưng danh sách tệp không thay đổi (không lọc).</li><li>Xóa sạch ô tìm kiếm nhưng danh sách tệp không khôi phục lại đầy đủ.</li><li>Tìm kiếm phân biệt chữ hoa/thường không mong muốn (ví dụ gõ `jpg` không tìm thấy `.JPG`).</li></ul> |

---

### PHẦN II: THANH CÔNG CỤ TÁC VỤ (Actions ToolBar)
*Tệp mã nguồn: [`ui/main_window.py`](ui/main_window.py)*

| Thành phần | Mã định danh / Nhãn | Phím tắt | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- | :--- | :--- |
| **Đổi tên hàng loạt** | `act_rename` | `Ctrl + R` | Mở hộp thoại `RenameDialog` nạp danh sách các tệp đang được chọn (hoặc toàn bộ thư mục nếu không chọn tệp nào). | <ul><li>Bấm vào không hiện hộp thoại.</li><li>Đã chọn 5 file nhưng khi mở hộp thoại lại thấy 0 file hoặc danh sách rỗng.</li><li>Mở hộp thoại nhưng làm treo giao diện chính (không chạy QDialog độc lập).</li></ul> |
| **Chuyển đổi định dạng** | `act_convert` | `Ctrl + Shift + C` | Mở hộp thoại `ConvertDialog` để chuyển đổi ảnh (Pillow/rawpy) hoặc video (ffmpeg). | <ul><li>Bấm vào không phản hồi.</li><li>Không nhận diện đúng danh sách tệp ảnh/video đang chọn để điền sẵn vào bảng chuyển đổi.</li></ul> |
| **Xóa Metadata** | `act_strip_meta` | — | Mở hộp thoại `MetadataDialog` làm sạch EXIF, XMP, IPTC bảo toàn ngày chụp gốc. | <ul><li>Bấm vào báo lỗi thiếu ExifTool dù hệ thống đã có.</li><li>Hộp thoại mở lên nhưng bị khoá nút thực thi (Action Button bị mờ vô lý).</li></ul> |
| **Xóa thư mục rỗng** | `act_clean` | — | Quét toàn bộ cây thư mục hiện tại, tìm các thư mục không chứa tệp và đưa an toàn vào Thùng rác (Send2Trash). | <ul><li>Xóa nhầm thư mục đang có tệp tin con ẩn.</li><li>Xóa vĩnh viễn (hard delete) thay vì đưa vào Thùng rác.</li><li>Treo toàn bộ ứng dụng khi duyệt thư mục có hàng chục nghìn nhánh con.</li><li>Không hiển thị thông báo kết quả (báo đã xoá bao nhiêu thư mục).</li></ul> |
| **Tự động sắp xếp** | `act_organize` | — | Mở hộp thoại `OrganizeDialog` gom tệp vào các thư mục Năm/Tháng hoặc Loại tệp. | <ul><li>Hộp thoại không xuất hiện hoặc mở ra với đường dẫn đích bị trống.</li></ul> |
| **Thống kê** | `act_stats` | — | Mở `StatsDialog` phân tích dung lượng ổ đĩa, nhóm tệp lớn nhất, tỷ lệ chiếm dụng. | <ul><li>Bấm vào làm đơ giao diện do tính toán dung lượng ở luồng chính (Main GUI Thread).</li><li>Biểu đồ / bảng thống kê hiện giá trị 0 byte hoặc âm.</li></ul> |
| **Cài đặt** | `act_settings` | — | Mở hộp thoại `SettingsDialog` tinh chỉnh cấu hình ngưỡng băm, phím tắt, ExifTool. | <ul><li>Thay đổi thông số và bấm Lưu nhưng khi mở lại thì thông số bị reset về mặc định.</li><li>Nhập đường dẫn ExifTool mới nhưng hệ thống không áp dụng ngay.</li></ul> |
| **Khôi phục từ Log** | `act_restore` | — | Mở `LogRestoreDialog` đọc file nhật ký `rename_log.jsonl` để hoàn tác tên tệp cũ. | <ul><li>Không mở được file log mặc định `rename_log.jsonl`.</li><li>Bảng log không tải được danh sách các lần đổi tên trước đó.</li></ul> |

---

### PHẦN III: CÂY THƯ MỤC BÊN TRÁI (TreePanel)
*Tệp mã nguồn: [`ui/panels/tree_panel.py`](ui/panels/tree_panel.py)*

| Thành phần | Thao tác tương tác | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- | :--- |
| **Cây phân cấp ổ đĩa** (`tree`) | Nhấp chuột trái chọn 1 thư mục | Phát tín hiệu `folder_selected(Path)`, kích hoạt Panel giữa tải nội dung thư mục đó. | <ul><li>Nhấp chọn một thư mục nhưng panel giữa không tải tệp của thư mục đó.</li><li>Các ổ đĩa gắn ngoài (USB, ổ cứng di động) cắm vào máy nhưng cây thư mục không nhận diện.</li><li>Không hiển thị mũi tên mở rộng (`>`) ở các thư mục có thư mục con.</li></ul> |
| **Đồng bộ vị trí (`expand_to`)** | Tự động kích hoạt khi chuyển thư mục từ Toolbar / ContentPanel | Tự động cuộn và mở rộng cây thư mục đến đúng vị trí thư mục đang đứng. | <ul><li>Chuyển thư mục ở ô địa chỉ nhưng cây thư mục vẫn đứng yên ở vị trí cũ.</li><li>Cây thư mục bị giật lag, nhảy vị trí liên tục khi chuyển thư mục nhanh.</li></ul> |

---

### PHẦN IV: VÙNG HIỂN THỊ NỘI DUNG CHÍNH (ContentPanel)
*Tệp mã nguồn: [`ui/panels/content_panel.py`](ui/panels/content_panel.py)*

| Thành phần | Thao tác tương tác | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- | :--- |
| **Nút Grid View (`⊞`)** | Nhấp chuột | Chuyển vùng hiển thị sang dạng lưới Thumbnail cỡ lớn (80x80 px). Nút `⊞` sáng lên, nút `☰` mờ đi. | <ul><li>Bấm vào nhưng giao diện không chuyển dạng xem.</li><li>Thumbnail bị vỡ bố cục, icon đè lên nhau hoặc khoảng cách quá rộng.</li><li>Cả hai nút Grid và Detail đều cùng sáng hoặc cùng tắt.</li></ul> |
| **Nút Detail View (`☰`)** | Nhấp chuột | Chuyển sang dạng bảng chi tiết gồm các cột: Tên, Kích thước, Loại, Ngày sửa đổi. | <ul><li>Cột thông tin bị co rúm, không đọc được tên tệp.</li><li>Không sắp xếp (Sort) được khi nhấp vào tiêu đề cột.</li></ul> |
| **Nhấp chọn tệp (Single Click)** | Nhấp chuột trái vào 1 tệp tin | Phát tín hiệu `file_selected(Path)` gửi sang Panel Preview bên phải để nạp ảnh & EXIF. Đồng thời cập nhật số lượng tệp chọn dưới Status Bar. | <ul><li>Nhấp vào tệp nhưng khung Preview bên phải vẫn trơ ra dòng chữ "Chọn file để xem preview".</li><li>Status bar không đếm đúng số mục chọn (ví dụ chọn 1 file nhưng status bar vẫn rỗng).</li></ul> |
| **Nhấp đúp chuột (Double Click)** | Nhấp đúp vào 1 thư mục con | Mở sâu vào thư mục đó, cập nhật lại thanh địa chỉ và lịch sử Back/Forward. | <ul><li>Nhấp đúp vào thư mục con nhưng không mở được, ứng dụng đứng yên.</li><li>Nhấp đúp vào tệp tin nhưng lại kích hoạt hành vi mở thư mục gây lỗi đường dẫn.</li></ul> |
| **Chọn nhiều tệp (Multi-selection)** | Giữ `Ctrl` hoặc `Shift` + click chuột | Chọn nhiều tệp đồng thời, Status Bar hiển thị `"X mục đã chọn"`. | <ul><li>Giữ Ctrl click chọn thêm tệp nhưng các tệp trước đó bị bỏ chọn.</li><li>Kéo chuột quét vùng chọn (Rubber-band selection) nhưng không chọn được tệp.</li></ul> |
| **Menu chuột phải (Context Menu)** | Nhấp chuột phải vào tệp/nhóm tệp đang chọn | Bật menu ngữ cảnh tại đúng vị trí con trỏ chuột với 5 lệnh: Đổi tên, Chuyển đổi, Xóa Metadata, Tự động sắp xếp, Kiểm định tệp này. | <ul><li>Nhấp chuột phải nhưng không hiện Menu.</li><li>Menu hiện sai vị trí (bị lệch ra góc màn hình).</li><li>Đang chọn 10 file nhưng nhấp chuột phải chỉ nhận diện file cuối cùng.</li><li>Chọn lệnh trong menu nhưng không thực thi đúng đối tượng đã chọn.</li></ul> |

---

### PHẦN V: KHUNG XEM TRƯỚC BÊN PHẢI (PreviewPanel)
*Tệp mã nguồn: [`ui/panels/preview_panel.py`](ui/panels/preview_panel.py)*

| Thành phần | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- |
| **Vùng hiển thị ảnh thu nhỏ (`thumb`)** | Hiển thị thumbnail mượt mà của ảnh JPG, PNG, WEBP, ảnh RAW (CR2, NEF, ARW qua `rawpy`) hoặc icon định dạng (🎬, 📄). | <ul><li>Ảnh định dạng phổ biến nhưng hiện chữ cảnh báo: `⚠ Không thể đọc ảnh`.</li><li>Ảnh phân giải cao (trên 20MB hoặc 8K) bị từ chối nạp do bộ nhớ Qt (`Rejecting image as it exceeds allocation limit`).</li><li>Tỉ lệ ảnh bị bóp méo (méo hình dọc/ngang thay vì giữ nguyên tỷ lệ `KeepAspectRatio`).</li></ul> |
| **Thẻ thông tin siêu dữ liệu (`info_label`)** | Hiển thị chi tiết: Tên tệp, Định dạng, Dung lượng (KB/MB), Độ phân giải (WxH), Hướng xoay (Ngang H/ Dọc V), Thời lượng video, và **Ngày chụp gốc EXIF**. | <ul><li>Hiển thị lỗi: `Lỗi: [nội dung lỗi]`.</li><li>Tệp có EXIF chụp máy ảnh nhưng thông tin ngày bị báo `unknown` hoặc lấy nhầm ngày copy file (`mtime`).</li><li>Độ phân giải hiển thị `None × None`.</li></ul> |

---

### PHẦN VI: TAB TỆP TRÙNG LẶP (DupPreviewPanel)
*Tệp mã nguồn: [`ui/panels/dup_preview_panel.py`](ui/panels/dup_preview_panel.py)*

| Thành phần | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- |
| **Menu chọn Engine** (`engine_combo`) | Chọn 1 trong 3 chế độ: `pHash (Nhanh)`, `DINOv2 (Chính xác)`, hoặc `Cả hai`. | <ul><li>Chọn DINOv2 khi không có PyTorch/CUDA làm crash ứng dụng thay vì tự động thông báo hoặc fallback sang pHash.</li></ul> |
| **Nút "Bắt đầu quét"** (`btn_scan`) | Khởi chạy luồng `QThread` quét tính toán mã băm ảnh toàn bộ thư mục. Hiện thanh tiến trình. | <ul><li>Bấm vào bị đơ GUI toàn bộ trong lúc quét.</li><li>Quét xong nhưng danh sách nhóm trùng lặp vẫn trống dù cố tình tạo 2 file ảnh giống hệt nhau.</li></ul> |
| **Nút thu gọn nhóm (`▾` / `▸`)** | Nhấp để ẩn/hiện danh sách ảnh trong một nhóm trùng lặp cụ thể. | <ul><li>Bấm vào nhưng danh sách thumbnail không ẩn đi.</li><li>Ký hiệu mũi tên không đổi chiều (`▾` sang `▸`).</li></ul> |
| **Thẻ ảnh thu nhỏ (`ThumbnailCard`)** | Hiển thị ảnh, Badge độ tương đồng (%), Độ phân giải, Dung lượng và **2 nút: [✔ Giữ] / [✖ Xóa]**. | <ul><li>Hệ thống không tự động đánh dấu [✔ Giữ] cho file có độ phân giải cao nhất.</li><li>Bấm [✖ Xóa] nhưng trạng thái nút không chuyển màu đỏ/gạch mờ tệp.</li><li>Bấm được cả hai nút [Giữ] và [Xóa] cùng một lúc cho 1 tệp.</li></ul> |
| **Nút "Áp dụng Xóa"** (`btn_apply`) | Đưa toàn bộ các tệp được đánh dấu [✖ Xóa] vào Thùng rác một cách an toàn. | <ul><li>Nút sáng khi chưa có tệp nào bị đánh dấu xóa.</li><li>Bấm Xóa nhưng file trên đĩa cứng vẫn còn nguyên.</li><li>Xóa thẳng tay (Delete vĩnh viễn) mà không qua Send2Trash.</li></ul> |

---

### PHẦN VII: TAB KIỂM ĐỊNH & BẢO MẬT (InspectorPanel)
*Tệp mã nguồn: [`ui/panels/inspector_panel.py`](ui/panels/inspector_panel.py)*

| Thành phần | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- |
| **Thẻ thống kê số liệu (`StatCard`)** | Cập nhật số liệu tức thì: Tổng số tệp, Tệp hợp lệ, Tệp dôi dư Overlay, Tệp hỏng, Tệp đã cách ly. | <ul><li>Số liệu hiển thị NaN hoặc không cộng dồn khi phát hiện tệp lỗi.</li><li>Tổng số tệp quét không khớp với tổng các mục con cộng lại.</li></ul> |
| **Nút "Quét kiểm định"** (`btn_scan`) | Phân tích cấu trúc nhị phân (Binary magic bytes, EOF markers, Trailing bytes, AMSI malware scan). | <ul><li>Tệp có mã độc hoặc chèn file RAR/EXE đằng sau ảnh JPEG nhưng không phát hiện ra Trailing Overlay.</li><li>Gây lỗi Permission Denied làm sập luồng quét khi gặp tệp hệ thống bị khóa.</li></ul> |
| **Nút "Gọt Overlay các mục chọn"** | Cắt bỏ phần byte dôi dư sau marker kết thúc ảnh (ví dụ sau `FF D9` của JPEG hoặc `IEND` của PNG). | <ul><li>Gọt xong làm hỏng cấu trúc ảnh khiến ảnh không mở được nữa.</li><li>Gọt trực tiếp vào file gốc mà không có cơ chế backup/quarantine.</li></ul> |
| **Nút "Sửa Header JPEG"** | Khôi phục byte mồi `FF D8 FF` cho ảnh bị hỏng phần đầu do virus hoặc lỗi truyền file. | <ul><li>Ảnh không phải JPEG nhưng vẫn cố sửa làm tệp bị hỏng hoàn toàn.</li></ul> |

---

### PHẦN VIII: THANH TIẾN TRÌNH NỔI & THANH TRẠNG THÁI (ProgressBanner & StatusBar)
*Tệp mã nguồn: [`ui/widgets/progress_banner.py`](ui/widgets/progress_banner.py) & [`ui/widgets/statusbar.py`](ui/widgets/statusbar.py)*

| Thành phần | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- |
| **Banner tiến trình nổi (`ProgressBanner`)** | Tự động trượt mở phía trên StatusBar khi có tác vụ nặng (quét, đổi tên, chuyển đổi format). Hiển thị: Tên file hiện tại, Tốc độ (`file/s`), Thời gian còn lại (`ETA`), Nút `Hủy`. | <ul><li>Tác vụ chạy ngầm nhưng Banner không xuất hiện, người dùng không biết app đang chạy hay bị treo.</li><li>Tốc độ xử lý hoặc ETA tính toán ra số âm hoặc vô tận (`còn ~0s` nhưng mãi không xong).</li><li>Bấm nút **[Hủy]** nhưng tiến trình vẫn tiếp tục chạy ngầm, không dừng luồng `QThread`.</li><li>Tác vụ chạy xong nhưng Banner không tự động ẩn sau 2.5 giây.</li></ul> |
| **Badge phần cứng CUDA/CPU** (`lbl_cuda`) | Hiển thị màu xanh lá: `GPU: [Tên GPU]` nếu có CUDA; hiển thị màu cam: `CPU Mode` nếu không có card/PyTorch. | <ul><li>Máy có RTX/GTX nhưng ứng dụng luôn nhận diện là CPU Mode do cấu hình đường dẫn sai.</li><li>Hiện thông báo lỗi crash đỏ chót thay vì hiển thị nhãn nhẹ nhàng `CPU Mode`.</li></ul> |

---

### PHẦN IX: HỘP THOẠI TÁC VỤ (Dialogs)

| Hộp thoại | Thành phần cốt lõi | Chức năng kỳ vọng | Dấu hiệu nhận biết khi CHẠY SAI (Bug Symptoms) |
| :--- | :--- | :--- | :--- |
| **Hộp thoại Đổi tên** (`RenameDialog`) | Bảng xem trước đổi tên 8 cột thông số, Bộ ghép mẫu tương tác (Token Chip Builder), Hover Thumbnail Preview, Quét đệ quy cây thư mục. | Hiển thị thông số chi tiết (Thư mục con, Tên gốc, Tên mới, Ngày/EXIF, Kích thước, Dung lượng, Định dạng, Trạng thái). Ghép mẫu token linh hoạt `{folder}_{date}_{orientation}_{resolution}`. Rà chuột hiển thị thumbnail nổi. | <ul><li>Đổi định dạng ngày hoặc token nhưng bảng Preview không cập nhật theo.</li><li>Tên mới bị trùng lặp làm ghi đè mất file của người dùng mà không có cảnh báo.</li><li>Đổi tên thành công nhưng không ghi lại nhật ký vào `rename_log.jsonl`.</li></ul> |
| **Hộp thoại Đổi tên Hàng đợi Kéo Thả** (`QueueRenameDialog`) | Vùng kho tệp nguồn bên trái, Dãy $N$ vị trí hàng đợi bên phải (#01..#N), Bộ nút xếp tự động (Ngày/Tên/Size). | Kéo thả tệp từ kho sang hàng đợi hoặc hoán đổi vị trí trực tiếp. Tên mới đổi theo quy tắc: `[Số thứ tự]_[Tên theo quy tắc cũ]`. Đổi tên có tiến trình và ghi nhật ký khôi phục. | <ul><li>Kéo thả tệp vào slot nhưng slot không nhận (Drop event bị nuốt).</li><li>Số thứ tự không tăng tuần tự hoặc trùng số thứ tự giữa 2 slot.</li><li>Thực hiện đổi tên nhưng làm mất tệp chưa được xếp vào hàng đợi.</li></ul> |
| **Hộp thoại Chuyển đổi** (`ConvertDialog`) | Thanh trượt chất lượng (Quality 1-100), Menu định dạng đích (`.png`, `.webp`...), Quét thư mục đệ quy.| Tạo bản sao chuyển đổi tại thư mục đích, không bao giờ ghi đè file gốc. Hỗ trợ quét đệ quy toàn bộ thư mục con. | <ul><li>Chuyển đổi làm mất dữ liệu file gốc.</li><li>File đích tạo ra có dung lượng 0 byte nhưng vẫn báo thành công.</li><li>Kéo thanh trượt Quality nhưng file xuất ra không thay đổi dung lượng.</li></ul> |
| **Hộp thoại Metadata** (`MetadataViewerDialog` & `MetadataDialog`) | Bảng hiển thị thẻ EXIF hai cột (Thẻ & Giá trị), Nút Xóa Metadata bảo toàn ngày, Quét đệ quy thư mục con. | Đọc và liệt kê toàn bộ thẻ EXIF, IPTC, XMP. Khi xoá metadata, trích xuất ngày chụp lưu vào RAM rồi ghi trả lại sau khi strip. Hỗ trợ duyệt đệ quy cây thư mục. | <ul><li>Bảng hiển thị thông báo: *"Không tìm thấy metadata..."* đối với ảnh chụp từ máy ảnh/điện thoại.</li><li>Sau khi xóa metadata, ngày tạo file bị nhảy sang thời gian hiện tại của máy tính thay vì giữ nguyên ngày chụp gốc.</li></ul> |
| **Hộp thoại Gom nhóm** (`OrganizeDialog`) | Combobox quy tắc gom (`YYYY/MM`, Loại tệp...)| Di chuyển tệp vào đúng cấu trúc thư mục logic được chỉ định. | <ul><li>Tệp bị mất trong quá trình di chuyển (Move error).</li><li>Tạo thư mục sai cấu trúc (ví dụ: `2026/0` thay vì `2026/09`).</li></ul> |
| **Hộp thoại Cài đặt** (`SettingsDialog`) | Trường nhập đường dẫn ExifTool (`edit_exiftool`), Nút Duyệt (`📁`)| Lưu trữ và tải cấu hình hệ thống từ file `config/settings.json`. | <ul><li>Chọn file `exiftool.exe` không tồn tại nhưng vẫn cho lưu mà không kiểm tra `-ver`.</li><li>Lưu cấu hình báo lỗi Permission Denied do không tạo thư mục `config/`.</li></ul> |
| **Hộp thoại Hoàn tác** (`LogRestoreDialog`) | Bảng nhật ký hoàn tác kèm Checkbox từng dòng, Nút "Khôi phục các mục đã chọn". | Đọc file `.jsonl`, kiểm tra đối chiếu mã băm MD5 và đổi tên tệp trở về trạng thái ban đầu trước khi rename. | <ul><li>Bấm khôi phục nhưng tên tệp không đổi lại như cũ.</li><li>Tệp đã bị xóa khỏi ổ đĩa nhưng app vẫn cố khôi phục gây crash unhandled exception.</li></ul> |

---

## 🛑 3. BẢNG TỔNG HỢP CÁC LỖI THƯỜNG GẶP & CÁCH PHÒNG TRÁNH (CODE-REVIEWER CHECKLIST)

1. **Lỗi chặn luồng chính (GUI Freezing)**:
   - *Biểu hiện*: Cửa sổ bị mờ, chuột biến thành vòng tròn xoay, Windows hiện thông báo *(Not Responding)*.
   - *Nguyên nhân*: Chạy quét thư mục lớn, tính perceptual hash hoặc chạy ExifTool trực tiếp trên luồng giao diện chính mà không đẩy vào `QThread` / `QThreadPool`.
2. **Lỗi nuốt ngoại lệ âm thầm (Silent Exception Swallowing)**:
   - *Biểu hiện*: Bấm nút nhưng không có bất kỳ phản hồi nào, không có thông báo lỗi.
   - *Nguyên nhân*: Sử dụng khối `except: pass` trống rỗng trong các module `core/` làm che giấu lỗi đọc tệp hoặc lỗi thiếu thư viện.
3. **Lỗi bộ nhớ ảnh Qt (`QImageIOHandler Limit`)**:
   - *Biểu hiện*: Console báo `Rejecting image as it exceeds allocation limit of 256 megabytes`.
   - *Khắc phục*: Đã cấu hình `QImageReader.setAllocationLimit(0)` trong [main.py](main.py).
4. **Lỗi mất đồng bộ Lịch sử Điều hướng**:
   - *Biểu hiện*: Nhấn `Back` thì quay lại đúng thư mục nhưng ô địa chỉ vẫn hiển thị đường dẫn cũ, hoặc cây thư mục bên trái không trỏ đúng node tương ứng.
