# 📋 KẾ HOẠCH HƯỚNG DẪN KIỂM THỬ THỦ CÔNG (MANUAL TEST PLAN)
### Ứng dụng Quản lý & Xử lý Tệp tin Đa năng — **FileManagerPro**

Tài liệu này được thiết kế để bạn có thể **tự tay kiểm tra (Test tay)** lần lượt từng màn hình, tính năng, nút bấm, phím tắt và luồng xử lý dữ liệu của dự án một cách trực quan và có hệ thống.

---

## 🗺️ 1. SƠ ĐỒ BỐ CỤC GIAO DIỆN (UI LAYOUT MAP)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ [📁 Mở thư mục] [🔍 Quét] [✏️ Đổi tên] [🛡️ Metadata] [📂 Sắp xếp] [📊 Thống kê] [⚙️]  │ ➔ TOOLBAR
│  Đường dẫn: [ D:\Photos\2023                       ] [🔍 Tìm kiếm... (Ctrl+F)        ] │
├─────────────────────────┬──────────────────────────────────────────┬───────────────────┤
│ 📂 CÂY THƯ MỤC          │ 📄 VÙNG HIỂN THỊ TỆP CHÍNH (CONTENT)     │ 🖼️ XEM TRƯỚC      │
│ (Tree Panel - Trái)     │ (Chế độ Icon ⊞ / Detail ☰)                │ (Preview - Phải)  │
│ ├─ This PC              │ ┌──────────────────────────────────────┐ │ ┌───────────────┐ │
│ │  ├─ C:\               │ │ [Ảnh 1.jpg] [Ảnh 2.png] [Video.mp4]  │ │ │  Hình ảnh    │ │
│ │  └─ D:\               │ │ [Doc.pdf]   [Data.xlsx]              │ │ │  thu nhỏ     │ │
│ │     └─ Photos         │ └──────────────────────────────────────┘ │ └───────────────┘ │
│                         │ Tab: [📁 File Explorer] [🔍 Trùng lặp]  │ Thông số EXIF/Kích│
├─────────────────────────┴──────────────────────────────────────────┴───────────────────┤
│ 🚀 THANH TIẾN TRÌNH: [🔍 Đang quét: Trip_01.jpg | 1,200/3,000 (40%) | 220 f/s] [✖ Hủy] │ ➔ PROGRESS BAR
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 📍 D:\Photos\2023       │ 12 mục đã chọn                           │ ⚡ RTX 4050 (6GB) │ ➔ STATUSBAR
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🧪 2. CHECKLIST KIỂM THỬ THỦ CÔNG TỪNG CHỨC NĂNG

---

### 🔹 TEST CASE 1: DUYỆT & ĐIỀU HƯỚNG TỆP TIN (FILE EXPLORER)
* **Mục tiêu:** Kiểm tra khả năng mở, duyệt, lọc và xem trước file.
* **Các bước thực hiện:**
  1. Chạy chương trình: `python main.py`.
  2. Tại **Cây thư mục bên trái (Tree Panel)**, nhấp chuột vào một ổ đĩa hoặc thư mục có chứa ảnh/video (ví dụ: `D:\` hoặc `Pictures`).
  3. Tại **Vùng hiển thị chính (Content Panel)**:
     * Nhấp đúp chuột vào một thư mục con bất kỳ ➔ *Kỳ vọng: Ứng dụng lập tức đi sâu vào thư mục đó, thanh địa chỉ cập nhật.*
     * Bấm nút **[⊞ Grid View]** và **[☰ Detail View]** ở góc trên bên phải ➔ *Kỳ vọng: Chuyển đổi mượt mà giữa dạng lưới icon và dạng bảng thông tin chi tiết.*
     * Gõ chữ vào ô tìm kiếm **(Ctrl+F)** ➔ *Kỳ vọng: Danh sách file tự động lọc theo từ khóa vừa gõ.*
     * Nhấp chọn 1 file ảnh bất kỳ ➔ *Kỳ vọng: Khung Preview bên phải hiển thị ảnh thu nhỏ, kích thước (WxH), hướng H/V và dung lượng.*
  4. Thử các phím tắt điều hướng:
     * `Alt + Left`: Quay lại thư mục trước đó (*Back*).
     * `Alt + Right`: Tiến tới thư mục tiếp theo (*Forward*).
     * `Alt + Up`: Lên thư mục cha (*Up to Parent*).
     * `F5`: Làm mới danh sách (*Refresh*).
     * `Ctrl + L`: Nhảy con trỏ chuột lên thanh địa chỉ để nhập trực tiếp đường dẫn.

---

### 🔹 TEST CASE 2: QUÉT THƯ MỤC & THANH TIẾN TRÌNH THỜI GIAN THỰC
* **Mục tiêu:** Kiểm tra khả năng trích xuất metadata đa luồng và hiển thị tiến trình.
* **Các bước thực hiện:**
  1. Chọn một thư mục có nhiều file (từ 50 đến hàng nghìn file).
  2. Bấm nút **[🔍 Quét thư mục]** trên thanh công cụ.
  3. Quan sát **Thanh tiến trình (Progress Banner)** xuất hiện phía trên thanh trạng thái:
     * *Kỳ vọng 1:* Hiển thị tên file đang đọc theo thời gian thực: `📄 ...filename.ext`.
     * *Kỳ vọng 2:* Đếm số lượng (`150 / 500 file`), tỷ lệ `%`, tốc độ quét (`file/s`) và thời gian dự kiến còn lại (`ETA: còn ~3s`).
  4. Nhấp nút **[✖ Hủy]** trong khi đang quét ➔ *Kỳ vọng: Quá trình quét dừng lại ngay lập tức, hiển thị thông báo "Đã dừng quét thư mục" mà không làm treo app.*

---

### 🔹 TEST CASE 3: ĐỔI TÊN HÀNG LOẠT & CHỐNG TRÙNG LẶP (BATCH RENAME)
* **Mục tiêu:** Kiểm tra quy tắc đổi tên chuẩn hóa `[ThưMục]_[Ngày]_[Hướng]_[KíchThước]` và khả năng chống ghi đè file.
* **Các bước thực hiện:**
  1. Chọn các file cần đổi tên (hoặc bấm **[🔍 Quét thư mục]** trước).
  2. Bấm nút **[✏️ Đổi tên hàng loạt]** trên thanh công cụ (hoặc phím tắt `Ctrl+R`).
  3. Trong hộp thoại **"Đổi tên hàng loạt"**:
     * Chọn định dạng ngày: `DDMMYY`, `DDMMYYYY`, `YYYYMMDD`.
     * Quan sát **Bảng xem trước (Preview Table)**: Cột "Tên mới" sẽ hiển thị màu xanh lá cây cho các file có tên thay đổi.
     * Kiểm tra các file chụp cùng một thời điểm: Các file này sẽ tự động được thêm đuôi `_001`, `_002`... để chống trùng.
  4. Nhấp nút **[✔ Thực hiện đổi tên]** ➔ Bấm **Yes** xác nhận.
  5. Kiểm tra kết quả: File trên ổ đĩa được đổi tên thành công và một dòng log JSONL được ghi nhận.

---

### 🔹 TEST CASE 4: HOÀN TÁC / KHÔI PHỤC TỪ NHẬT KÝ (LOG & RESTORE)
* **Mục tiêu:** Kiểm tra tính an toàn tuyệt đối khi cần khôi phục lại tên file cũ.
* **Các bước thực hiện:**
  1. Trên Menu / Toolbar, bấm nút **[⟲ Khôi phục]**.
  2. Chọn file `rename_log.jsonl` đã tạo ở bước trên.
  3. Bấm **[🔍 Tải & Phân tích Log]** ➔ *Kỳ vọng: Bảng hiển thị toàn bộ lịch sử đổi tên.*
  4. Bấm **[⟲ Khôi phục tất cả]** ➔ *Kỳ vọng: Tất cả các file được tự động đổi lại chính xác tên gốc ban đầu.*

---

### 🔹 TEST CASE 5: XÓA AN TOÀN METADATA & BẢO TOÀN NGÀY TẠO (SAFE STRIP)
* **Mục tiêu:** Kiểm tra tính năng xóa sạch GPS, camera info nhưng vẫn giữ nguyên ngày chụp gốc.
* **Các bước thực hiện:**
  1. Chọn 1 hoặc nhiều file ảnh/video trên giao diện chính.
  2. Bấm nút **[🛡️ Xóa Metadata]** trên thanh công cụ.
  3. Trong hộp thoại:
     * Chọn phạm vi: *"Các file đang chọn trên giao diện"* hoặc *"Toàn bộ thư mục"*.
     * Bấm **[👁️ Xem Metadata raw]** ➔ *Kỳ vọng: Bảng chi tiết toàn bộ các thẻ EXIF/GPS hiện có của file.*
  4. Bấm nút **[🛡️ Thực hiện Xóa an toàn]**.
  5. Sau khi hoàn tất: Mở lại xem metadata của file ➔ *Kỳ vọng: Tọa độ GPS, thông tin máy ảnh đã bị xóa sạch, nhưng ngày chụp gốc (`DateTimeOriginal` / Video Creation Date) vẫn được giữ nguyên.*

---

### 🔹 TEST CASE 6: PHÁT HIỆN & XÓA ẢNH TRÙNG LẶP (DUPLICATE DETECTION)
* **Mục tiêu:** Kiểm tra engine AI (GPU pHash + DINOv2) và cơ chế xóa trùng an toàn.
* **Các bước thực hiện:**
  1. Chuẩn bị 2-3 bức ảnh giống hệt nhau hoặc cùng góc chụp trong một thư mục.
  2. Chuyển sang tab **"🔍 Trùng lặp"** (ở giữa màn hình).
  3. Chọn chế độ quét: `pHash (Nhanh)`, `DINOv2 (AI Học sâu)` hoặc `Cả hai (Khuyên dùng)`.
  4. Nhấp nút **[🚀 Quét ảnh trùng lặp]**.
  5. Sau khi quét xong:
     * Các nhóm trùng lặp sẽ hiển thị dạng lưới ảnh thu nhỏ kèm thông số độ tương đồng `%`, kích thước và dung lượng.
     * Nhấp nút **[★ Giữ ảnh tốt nhất]** ➔ *Kỳ vọng: Ứng dụng tự động chọn giữ lại ảnh có độ phân giải/dung lượng cao nhất, đánh dấu đỏ các ảnh trùng còn lại.*
     * Nhấp nút **[🗑️ Áp dụng xóa X file]** ➔ *Kỳ vọng: Các file được đưa vào **Thùng rác Windows (Recycle Bin)** một cách an toàn.*

---

### 🔹 TEST CASE 7: TỰ ĐỘNG SẮP XẾP THEO THƯ MỤC (FILE ORGANIZER)
* **Mục tiêu:** Phân loại file theo niên đại hoặc thể loại.
* **Các bước thực hiện:**
  1. Bấm nút **[📂 Tự động sắp xếp]** trên thanh công cụ.
  2. Chọn phương thức gom nhóm:
     * `Theo Năm/Tháng (YYYY/MM)` ➔ Ví dụ: `2023/10/photo.jpg`.
     * `Theo Năm/Tháng/Ngày (YYYY/MM/DD)`.
     * `Theo Thể loại Media (Images/Videos/Others)`.
     * `Theo Đuôi mở rộng (JPG/PNG/MP4)`.
  3. Chọn thư mục đích và bấm **[🔄 Xem trước]** để kiểm tra đường dẫn mới.
  4. Bấm **[✔ Bắt đầu sắp xếp]** ➔ *Kỳ vọng: Các thư mục con được tự động tạo và di chuyển file vào đúng vị trí.*

---

### 🔹 TEST CASE 8: CHUYỂN ĐỔI ĐỊNH DẠNG (FORMAT CONVERTER)
* **Mục tiêu:** Chuyển đổi định dạng ảnh/video hàng loạt sang JPG, PNG, WEBP, MP4...
* **Các bước thực hiện:**
  1. Bấm nút **[🔄 Chuyển đổi định dạng]** (hoặc `Ctrl+Shift+C`).
  2. Bấm **[➕ Thêm file]** hoặc tải danh sách file cần chuyển đổi.
  3. Chọn định dạng đích (ví dụ: `.webp` hoặc `.png`), điều chỉnh thanh trượt chất lượng (Quality 1-100).
  4. Chọn thư mục lưu xuất và bấm **[✔ Bắt đầu chuyển đổi]**.
  5. *Kỳ vọng: Các file mới được xuất ra thư mục đích với định dạng mới, giữ nguyên file gốc.*

---

### 🔹 TEST CASE 9: DỌN DẸP THƯ MỤC RỖNG (FOLDER CLEANER)
* **Mục tiêu:** Tìm và xóa các thư mục không chứa dữ liệu.
* **Các bước thực hiện:**
  1. Trên menu chuột phải hoặc thanh công cụ, chọn **[Dọn thư mục rỗng]**.
  2. *Kỳ vọng: Ứng dụng quét đệ quy từ dưới lên và hiển thị danh sách các thư mục rỗng cần dọn dẹp.*
  3. Bấm **Yes** xác nhận ➔ *Kỳ vọng: Các thư mục rỗng được đưa vào Thùng rác.*

---

### 🔹 TEST CASE 10: THỐNG KÊ Ổ ĐĨA & CÀI ĐẶT HỆ THỐNG
* **Mục tiêu:** Kiểm tra màn hình thống kê biểu đồ dung lượng và lưu cài đặt.
* **Các bước thực hiện:**
  1. Bấm nút **[📊 Thống kê]**: Quan sát biểu đồ phân loại dung lượng Media, bảng top 15 file lớn nhất.
  2. Bấm nút **[⚙️ Cài đặt]**: Thay đổi số luồng quét (Scanner Workers) hoặc ngưỡng trùng lặp, sau đó bấm **[Lưu cài đặt]**.
  3. Mở file `config/settings.json` ➔ *Kỳ vọng: Các thiết lập mới được lưu lại chính xác.*

---

## ⌨️ 3. BẢNG PHÍM TẮT TIỆN ÍCH TRONG ỨNG DỤNG

| Phím tắt | Chức năng tương ứng |
|:---|:---|
| **`F5`** | Làm mới toàn bộ danh sách thư mục và tệp tin |
| **`Ctrl + F`** | Đặt con trỏ vào ô tìm kiếm tệp tin |
| **`Ctrl + L`** | Đặt con trỏ vào thanh nhập đường dẫn thư mục |
| **`Alt + Up`** | Đi lên thư mục cha (Level Up) |
| **`Alt + Left`** | Quay lại thư mục trước đó (Back) |
| **`Alt + Right`**| Đi tới thư mục tiếp theo (Forward) |
| **`Ctrl + R`** | Mở nhanh hộp thoại Đổi tên hàng loạt |
| **`Ctrl + Shift + C`** | Mở nhanh hộp thoại Chuyển đổi định dạng Media |
