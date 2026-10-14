# 📁 FileManagerPro (FMPRO)

<p align="center">
  <img src="exiftool_files/html/ET-256.png" width="100" height="100" alt="FileManagerPro Logo" />
</p>

<p align="center">
  <strong>Trình Quản Lý & Tối Ưu Tệp Tin Đa Phương Tiện Chuyên Nghiệp Dành Cho Windows</strong><br>
  <em>Tích hợp AI Deep Learning (DINOv2), Nhận diện Trùng lặp (pHash), Đổi tên Hàng loạt Hồi phục (WAL), và Xử lý Siêu dữ liệu EXIF/RAW.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?style=for-the-badge&logo=windows" alt="Platform Windows" />
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-3776AB?style=for-the-badge&logo=python" alt="Python" />
  <img src="https://img.shields.io/badge/GUI-PyQt6%20%2F%20PySide6-41CD52?style=for-the-badge&logo=qt" alt="GUI Qt" />
  <img src="https://img.shields.io/badge/AI%20Engine-PyTorch%20%2F%20CUDA-EE4C2C?style=for-the-badge&logo=pytorch" alt="AI PyTorch" />
  <img src="https://img.shields.io/badge/Release-v1.0.0%20Portable-blue?style=for-the-badge" alt="Release" />
</p>

---

## 🌟 Giới Thiệu (Overview)

**FileManagerPro** là phần mềm máy tính để bàn (Desktop GUI) hiệu năng cao, được thiết kế chuyên biệt cho nhiếp ảnh gia, nhà sáng tạo nội dung và người dùng có kho dữ liệu ảnh/video lớn.

Ứng dụng kết hợp sức mạnh của **Qt6 Fluent Dark UI**, công cụ trích xuất siêu dữ liệu chuẩn công nghiệp **ExifTool**, thuật toán băm nhận diện ảnh **pHash**, và mô hình thị giác máy tính **Meta DINOv2** tăng tốc bằng **NVIDIA CUDA GPU**.

---

## 🚀 Tính Năng Cốt Lõi (Key Features)

### 1. 🏷️ Bộ Đổi Tên Hàng Loạt Chuyên Nghiệp (Batch Renamer & Queue)
- **Token Chip Builder**: Ghép mẫu tên linh hoạt bằng các khối thẻ tương tác:
  - `{folder}`: Tên thư mục cha
  - `{date}`: Ngày chụp gốc trích xuất từ thẻ EXIF (`DDMMYY`, `YYYYMMDD`,...)
  - `{orientation}`: Hướng khung hình (`H` - Ngang, `V` - Dọc)
  - `{resolution}`: Độ phân giải thực tế (`WxH`)
  - `{seq}`: Đánh số thứ tự chống trùng lặp tự động (`_001`, `_002`...)
- **Bảng xem trước trực tiếp (Live Preview)**: Bảng 8 cột thông số chi tiết, hiển thị ảnh thumbnail nổi (Hover Preview) khi rà chuột.
- **Hàng đợi kéo thả (Queue Rename)**: Sắp xếp vị trí tệp trực quan, hoán đổi thứ tự đánh số nhanh chóng.
- **Nhật ký hoàn tác WAL (Write-Ahead Logging)**: Mọi thao tác đổi tên đều được ghi chép an toàn kèm mã kiểm tra MD5. Cho phép **hoàn tác 1-click** quay về tên tệp gốc bất kỳ lúc nào.

### 2. 🔍 Nhận Diện & Dọn Dẹp Ảnh Trùng Lặp Thông Minh (Duplicate Engine)
- **Engine kép (Dual Engine)**:
  - **pHash (Perceptual Hash)**: So sánh mã băm tri giác siêu tốc cho hàng nghìn ảnh.
  - **DINOv2 Deep Learning**: Trích xuất đặc trưng thị giác bằng AI, tìm được cả các ảnh chụp góc tương tự, ảnh qua chỉnh màu hoặc crop khung hình.
- **Tăng tốc phần cứng CUDA**: Tự động nhận diện card đồ họa NVIDIA RTX/GTX để tính toán song song ma trận.
- **Thông minh & An toàn**: Tự động chọn giữ lại tệp có chất lượng và độ phân giải cao nhất, đưa các bản trùng lặp vào Thùng rác (**Send2Trash**) an toàn, tuyệt đối không xóa vĩnh viễn ngoài ý muốn.

### 3. 🛡️ Kiểm Định Cấu Trúc Nhị Phân & Bảo Mật Tệp (File Inspector)
- **Phân tích Magic Bytes**: Quét toàn diện tiêu đề nhị phân (Header/EOF) của ảnh JPEG, PNG, WEBP, GIF, BMP.
- **Phát hiện dữ liệu đính kèm ẩn (Trailing Overlay)**: Nhận diện mã độc, file RAR/EXE ngụy trang giấu đằng sau đuôi ảnh.
- **Gọt Overlay & Sửa Header**: Khôi phục cấu hình byte ban đầu và gọt bỏ dữ liệu dư thừa an toàn.

### 4. 📸 Xử Lý Metadata & Ảnh RAW (EXIF Studio)
- Tích hợp sẵn bộ công cụ **ExifTool** độc lập.
- Đọc chi tiết toàn bộ thẻ máy ảnh (Camera Model, Lens, ISO, F-number, Shutter Speed, GPS).
- Hỗ trợ định dạng ảnh RAW chuyên nghiệp: `.CR2`, `.NEF`, `.ARW`, `.DNG` qua `rawpy`.
- **Làm sạch Metadata bảo toàn ngày chụp**: Xóa thông tin cá nhân/GPS nhưng tự động giữ nguyên tem thời gian chụp gốc của ảnh.

### 5. 🗂️ Tự Động Sắp Xếp & Dọn Thư Mục Rỗng
- Gom nhóm tệp tự động theo Năm/Tháng hoặc theo Định dạng tệp vào đúng cây thư mục.
- Quét đệ quy cây thư mục và dọn dẹp các thư mục rỗng an toàn qua Thùng rác.

---

## ⚡ Hướng Dẫn Cài Đặt & Khởi Chạy (Quick Start)

### 🌟 Cách 1: Dành Cho Người Dùng Phổ Thông (Bản Portable .exe)
> **Không cần cài đặt Python. Không cần gõ lệnh. Chỉ cần tải về là chạy!**

1. Vào mục [**Releases**](https://github.com) của dự án trên GitHub.
2. Tải về tệp nén **`FileManagerPro_v1.0_Portable.zip`**.
3. Giải nén vào một thư mục bất kỳ trên máy tính.
4. Nhấp đúp vào tệp **`FileManagerPro.exe`** để mở ứng dụng ngay lập tức!

---

### 🛠️ Cách 2: Dành Cho Lập Trình Viên / Clone Từ GitHub (Zero-Config Launcher)

1. Clone mã nguồn về máy:
   ```bash
   git clone https://github.com/your-username/FileManagerPro.git
   cd FileManagerPro
   ```
2. **Khởi chạy bằng 1 click**:
   - Nhấp đúp vào tệp **`Run_FileManagerPro.bat`**.
   - Script sẽ **tự động kiểm tra Python**, **tự khởi tạo môi trường ảo `.venv`**, **tự động cài đặt đầy đủ thư viện** từ `requirements.txt` và khởi động app.
   - Các lần mở tiếp theo, ứng dụng sẽ khởi động ngay lập tức với độ trễ 0 giây.

---

### 💻 Cách 3: Cài Đặt Thủ Công Bằng Dòng Lệnh (Terminal / PowerShell)

Nếu bạn muốn tự quản lý môi trường ảo:

```powershell
# 1. Tạo môi trường ảo Python
python -m venv .venv

# 2. Kích hoạt môi trường ảo
.\.venv\Scripts\activate

# 3. Cài đặt các gói phụ thuộc
pip install -r requirements.txt

# 3b. (Tùy chọn) Bật engine AI DINOv2 — PyTorch + FAISS (~2.5 GB)
#     Không cài thì tính năng tìm trùng chỉ dùng pHash.
pip install -r requirements-ai.txt

# 4. Khởi chạy ứng dụng
python main.py
```

---

## 📦 Cách Tự Đóng Gói Thành Bản Portable `.exe` (Build From Source)

Dự án đã tích hợp sẵn kịch bản đóng gói tự động tối ưu qua PyInstaller:

1. Đảm bảo bạn đã kích hoạt môi trường ảo hoặc cài đặt các thư viện cần thiết.
2. Nhấp đúp vào tệp **`build_portable.bat`** (hoặc chạy trong terminal):
   ```cmd
   build_portable.bat
   ```
3. Kết quả xuất ra:
   - Thư mục chạy độc lập: `dist\FileManagerPro\FileManagerPro.exe`
   - Gói nén chia sẻ: `dist\FileManagerPro_v1.0_Portable.zip` (Sẵn sàng upload lên GitHub Releases).

---

## ⌨️ Bảng Phím Tắt Tiện Ích (Shortcuts)

| Phím Tắt | Tác Vụ |
| :--- | :--- |
| `Ctrl + R` | Mở hộp thoại Đổi tên hàng loạt (`RenameDialog`) |
| `Ctrl + P` | Mở bảng lệnh nhanh (Command Palette) |
| `Ctrl + F` | Nhảy nhanh vào ô tìm kiếm tệp tin |
| `Ctrl + L` | Nhảy nhanh vào thanh địa chỉ thư mục |
| `Ctrl + Shift + C` | Mở hộp thoại Chuyển đổi định dạng tệp |
| `Alt + Left` | Quay lại thư mục trước trong lịch sử (`Back`) |
| `Alt + Right` | Tiến lên thư mục kế tiếp trong lịch sử (`Forward`) |
| `Alt + Up` | Lên thư mục cấp cha trực tiếp (`Parent Directory`) |
| `F5` | Làm mới danh sách tệp tin và cây thư mục (`Refresh`) |
| `Space` | Xem nhanh tệp tin đang chọn (Quick Look Preview) |

---

## 📂 Cấu Trúc Dự Án (Project Architecture)

```
FileManagerPro/
│
├── core/                     # Tầng lõi xử lý logic nền tảng
│   ├── app_logcat.py         # Hệ thống ghi nhật ký & giám sát giật lag GUI
│   ├── background_manager.py # Quản lý ảnh/video nền giao diện
│   ├── converter.py          # Bộ chuyển đổi định dạng ảnh/video
│   ├── metadata.py           # Trích xuất và bóc tách metadata EXIF/RAW
│   ├── renamer.py            # Động cơ phân giải mẫu đổi tên Token
│   ├── security.py           # Quét tệp nhị phân & kiểm định bảo mật
│   └── workers.py            # Các tác vụ chạy ngầm QThread đa luồng
│
├── duplicate/                # Động cơ nhận diện trùng lặp
│   ├── dup_manager.py        # Điều phối phân tích ảnh trùng lặp
│   ├── phash_engine.py       # Thuật toán băm Perceptual Hash
│   └── embedding_engine.py   # Mô hình AI DINOv2 Deep Learning
│
├── ui/                       # Giao diện người dùng đồ họa Qt6
│   ├── dialogs/              # Các hộp thoại tác vụ (Rename, Convert, Settings,...)
│   ├── panels/               # Các bảng chức năng (Tree, Content, Preview,...)
│   ├── widgets/              # Các thành phần giao diện nhỏ (Toolbar, Statusbar,...)
│   └── main_window.py        # Cửa sổ ứng dụng chính MainWindow
│
├── utils/                    # Các tiện ích bổ trợ
│   ├── cuda_helper.py        # Kiểm tra phần cứng NVIDIA CUDA / GPU
│   ├── date_utils.py         # Định dạng ngày EXIF & tìm kiếm ExifTool
│   └── file_utils.py         # Thao tác tệp, tính hash MD5/SHA256, app root
│
├── config/                   # Cấu hình ứng dụng
│   └── settings.json         # Thiết lập mặc định (ngưỡng băm, workers,...)
│
├── tests/                    # Bộ kiểm thử tự động toàn diện (41 unit tests)
├── assets/                   # Tài nguyên đồ họa, biểu tượng, hình nền
├── exiftool_files/           # Thư viện ExifTool độc lập
├── ExifTool.exe              # File thực thi ExifTool wrapper
├── Run_FileManagerPro.bat    # Trình khởi chạy tự động Zero-Config
├── build_portable.bat        # Script đóng gói Portable .exe
├── filemanagerpro.spec       # Tệp đặc tả PyInstaller
├── requirements.txt          # Danh mục thư viện Python
├── requirements-ai.txt       # (Tùy chọn) PyTorch + FAISS cho engine DINOv2
└── README.md                 # Tài liệu hướng dẫn sử dụng
```

---

## 🧪 Kiểm Thử Tự Động (Automated Testing)

Dự án đi kèm bộ kiểm định gồm **41 unit test** bao phủ toàn bộ các luồng chức năng:

```powershell
python -m unittest discover tests
```

**Kết quả kiểm tra**:
```
Ran 41 tests in 6.488s
OK
```

---

## 📄 Bản Quyền & Giấy Phép (License)

Phần mềm được phát hành theo giấy phép mã nguồn mở **MIT License**. Bạn được tự do sử dụng, chỉnh sửa, đóng gói và chia sẻ cho mục đích cá nhân cũng như thương mại.
