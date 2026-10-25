"""
tests/test_env_stress.py
Empirical stress tests for FileManagerPro Python environment:
- PyTorch: tensor creation, matmul, autograd, CNN module forward pass, torchvision transforms
- FAISS: IndexFlatIP, IndexFlatL2, 1000-vector indexing, batch search, k-NN retrieval, edge cases, serialization
- OpenCV & ImageHash: synthetic frame encoding/decoding, color spaces, filtering, pHash/dHash/aHash/wHash, scipy distance
- Media & Metadata: piexif roundtrip, mutagen tag handling, rawpy exception handling, ffmpeg-python graph construction
- Headless PyQt6 MainWindow: offscreen event loops, tab creation/cycling, dock toggling, resize events, clean disposal
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

import pytest
import numpy as np

# Set offscreen Qt platform before any Qt modules load
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_torch_stress():
    # torch/torchvision are optional (requirements-ai.txt); pHash-only installs skip
    torch = pytest.importorskip("torch")
    transforms = pytest.importorskip("torchvision.transforms")
    from PIL import Image

    print(f"\n[TORCH] Version: {torch.__version__}, Threads: {torch.get_num_threads()}")

    # 1. Tensor creation & basic math operations
    x = torch.randn(500, 500, dtype=torch.float32)
    y = torch.randn(500, 500, dtype=torch.float32)
    z = torch.matmul(x, y)
    assert z.shape == (500, 500)
    assert not torch.isnan(z).any()

    # 2. Autograd backpropagation stress
    w = torch.randn(64, 64, requires_grad=True)
    v = torch.randn(64, 64)
    loss = (torch.mm(w, v) ** 2).sum() + torch.relu(w).sum()
    loss.backward()
    assert w.grad is not None
    assert w.grad.shape == (64, 64)
    assert not torch.isnan(w.grad).any()

    # 3. Neural network forward pass
    class MiniConvNet(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = torch.nn.Conv2d(3, 16, kernel_size=3, padding=1)
            self.bn1 = torch.nn.BatchNorm2d(16)
            self.act = torch.nn.GELU()
            self.pool = torch.nn.AdaptiveAvgPool2d((1, 1))
            self.fc = torch.nn.Linear(16, 384)

        def forward(self, x):
            x = self.act(self.bn1(self.conv1(x)))
            x = self.pool(x)
            x = torch.flatten(x, 1)
            x = self.fc(x)
            return torch.nn.functional.normalize(x, p=2, dim=-1)

    model = MiniConvNet()
    model.eval()
    dummy_input = torch.randn(8, 3, 224, 224)
    with torch.no_grad():
        out = model(dummy_input)
    assert out.shape == (8, 384)
    norms = torch.norm(out, p=2, dim=-1)
    np.testing.assert_allclose(norms.numpy(), np.ones(8), atol=1e-5)

    # 4. Serialization check
    buf = io.BytesIO()
    torch.save(model.state_dict(), buf)
    buf.seek(0)
    loaded = torch.load(buf, weights_only=True)
    assert "conv1.weight" in loaded

    # 5. Torchvision image transforms
    img = Image.new("RGB", (256, 256), color=(128, 64, 32))
    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    tensor_img = transform(img)
    assert tensor_img.shape == (3, 224, 224)


def test_faiss_stress():
    faiss = pytest.importorskip("faiss")

    # 1. IndexFlatIP with DINOv2 embedding dim (384)
    dim = 384
    n_vectors = 1000
    np.random.seed(42)

    raw_data = np.random.randn(n_vectors, dim).astype(np.float32)
    # L2 normalize
    faiss.normalize_L2(raw_data)

    index_ip = faiss.IndexFlatIP(dim)
    assert index_ip.is_trained
    assert index_ip.ntotal == 0

    index_ip.add(raw_data)
    assert index_ip.ntotal == n_vectors

    # Batch search with exact self-retrieval check
    queries = raw_data[:5]
    k = 5
    distances, indices = index_ip.search(queries, k)
    assert distances.shape == (5, k)
    assert indices.shape == (5, k)

    for i in range(5):
        # The nearest neighbor of queries[i] must be vector i itself with cosine sim ~ 1.0
        assert indices[i, 0] == i
        np.testing.assert_allclose(distances[i, 0], 1.0, atol=1e-5)

    # 2. IndexFlatL2 with 768 dimensions
    dim_l2 = 768
    data_l2 = np.random.randn(200, dim_l2).astype(np.float32)
    index_l2 = faiss.IndexFlatL2(dim_l2)
    index_l2.add(data_l2)
    assert index_l2.ntotal == 200

    q_l2 = data_l2[:3]
    dists_l2, idxs_l2 = index_l2.search(q_l2, 3)
    for i in range(3):
        assert idxs_l2[i, 0] == i
        np.testing.assert_allclose(dists_l2[i, 0], 0.0, atol=1e-5)

    # 3. Edge case: top_k > ntotal
    dist_overflow, idx_overflow = index_l2.search(q_l2[:1], 500)
    assert dist_overflow.shape == (1, 500)
    # Beyond index_l2.ntotal, results are padded with -1
    assert idx_overflow[0, 200] == -1

    # 4. Serialization / deserialization to file
    with tempfile.NamedTemporaryFile(suffix=".index", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        faiss.write_index(index_ip, tmp_path)
        assert os.path.exists(tmp_path)
        reloaded = faiss.read_index(tmp_path)
        assert reloaded.ntotal == n_vectors
        assert reloaded.d == dim
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_opencv_and_imagehash_stress():
    import cv2
    import imagehash
    from PIL import Image
    import scipy.spatial.distance as sp_dist

    # 1. OpenCV synthetic drawing & manipulation
    img_bgr = np.zeros((300, 400, 3), dtype=np.uint8)
    img_bgr[:] = (45, 120, 200)
    cv2.circle(img_bgr, (200, 150), 60, (0, 255, 0), -1)
    cv2.putText(img_bgr, "FileManagerPro", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    # Color conversion
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    assert img_gray.shape == (300, 400)

    # Encode to JPEG in memory
    success, encoded_jpg = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert success
    assert len(encoded_jpg) > 0

    # Decode from memory
    decoded = cv2.imdecode(encoded_jpg, cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (300, 400, 3)

    # Encode to PNG in memory
    success_png, encoded_png = cv2.imencode(".png", img_bgr)
    assert success_png
    decoded_png = cv2.imdecode(encoded_png, cv2.IMREAD_COLOR)
    assert decoded_png is not None

    # Filtering & edge detection
    blurred = cv2.GaussianBlur(img_gray, (5, 5), 1.5)
    edges = cv2.Canny(blurred, 50, 150)
    assert edges.shape == (300, 400)

    # 2. ImageHash on PIL Image
    pil_img1 = Image.fromarray(img_rgb)
    pil_img2 = pil_img1.resize((200, 200))

    h_p = imagehash.phash(pil_img1)
    h_d = imagehash.dhash(pil_img1)
    h_a = imagehash.average_hash(pil_img1)
    h_w = imagehash.whash(pil_img1)

    assert len(str(h_p)) > 0
    assert len(str(h_d)) > 0
    assert len(str(h_a)) > 0
    assert len(str(h_w)) > 0

    # Resized identical image should have minimal or 0 hamming distance
    h_p2 = imagehash.phash(pil_img2)
    diff = h_p - h_p2
    assert diff <= 4, f"pHash diff between scales was unexpectedly large: {diff}"

    # 3. Scipy spatial distance
    v1 = np.array([1.0, 0.0, 0.5])
    v2 = np.array([0.9, 0.1, 0.4])
    cos_sim = 1.0 - sp_dist.cosine(v1, v2)
    assert 0.95 <= cos_sim <= 1.01


def test_media_metadata_libraries():
    import piexif
    import mutagen
    from mutagen.id3 import ID3, TIT2, TPE1
    import rawpy
    import ffmpeg
    from PIL import Image

    # 1. Piexif synthetic EXIF roundtrip
    img = Image.new("RGB", (100, 100), color=(200, 100, 50))
    zeroth_ifd = {
        piexif.ImageIFD.Make: "FileManagerProCamera",
        piexif.ImageIFD.Software: "FileManagerPro AI",
    }
    exif_ifd = {
        piexif.ExifIFD.UserComment: b"EmpiricalStressTest",
    }
    exif_dict = {"0th": zeroth_ifd, "Exif": exif_ifd, "GPS": {}, "1st": {}, "thumbnail": None}
    exif_bytes = piexif.dump(exif_dict)
    assert len(exif_bytes) > 0

    bio = io.BytesIO()
    img.save(bio, format="JPEG", exif=exif_bytes)
    bio.seek(0)

    loaded_exif = piexif.load(bio.getvalue())
    assert loaded_exif["0th"][piexif.ImageIFD.Make] == b"FileManagerProCamera"
    assert loaded_exif["0th"][piexif.ImageIFD.Software] == b"FileManagerPro AI"

    # 2. Mutagen ID3 manipulation in memory
    id3 = ID3()
    id3.add(TIT2(encoding=3, text="Test Title"))
    id3.add(TPE1(encoding=3, text="Test Artist"))
    assert str(id3["TIT2"]) == "Test Title"
    assert str(id3["TPE1"]) == "Test Artist"

    # 3. Rawpy API availability & error handling
    assert hasattr(rawpy, "RawPy")
    # Feed invalid raw data: ensure it raises LibRawFileUnsupportedError or similar, without segfault
    dummy_corrupt = b"NOT_A_RAW_FILE_12345"
    with pytest.raises(Exception) as exc_info:
        rawpy.imread(io.BytesIO(dummy_corrupt))
    assert exc_info.type is not None

    # 4. ffmpeg-python graph generation
    stream = ffmpeg.input("dummy_input.mp4")
    video = stream.video.filter("scale", 1280, 720)
    audio = stream.audio
    out = ffmpeg.output(video, audio, "dummy_output.mp4")
    cmd_args = ffmpeg.compile(out)
    assert "dummy_input.mp4" in cmd_args
    assert "dummy_output.mp4" in cmd_args
    assert any("scale=1280:720" in str(arg) for arg in cmd_args)


def test_headless_mainwindow_stress(qtbot=None):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QSize, QEvent
    from PyQt6.QtGui import QResizeEvent

    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    from ui.main_window import MainWindow

    # 1. Instantiate window
    win = MainWindow()
    win.show()
    app.processEvents()

    # 2. Stress resize events across different geometry scales
    test_sizes = [
        QSize(800, 600),
        QSize(1280, 800),
        QSize(1920, 1080),
        QSize(400, 300),  # minimum boundary
        QSize(1024, 768),
    ]
    for size in test_sizes:
        win.resize(size)
        event = QResizeEvent(size, win.size())
        app.sendEvent(win, event)
        app.processEvents()
        assert win.width() > 0
        assert win.height() > 0

    # 3. Stress tab additions and switching
    if hasattr(win, "workspace_tabs"):
        initial_count = len(win.workspace_tabs.tabs)
        # Add new tabs
        for i in range(3):
            if hasattr(win.workspace_tabs, "add_tab"):
                win.workspace_tabs.add_tab()
                app.processEvents()
        assert len(win.workspace_tabs.tabs) >= initial_count

        # Cycle selection
        for i in range(len(win.workspace_tabs.tabs)):
            if hasattr(win.workspace_tabs, "set_active_tab"):
                win.workspace_tabs.set_active_tab(i)
                app.processEvents()

    # 4. Stress dock mode toggling
    if hasattr(win, "right_dock"):
        for _ in range(5):
            win.right_dock.set_mode("queue")
            app.processEvents()
            assert win.right_dock.is_queue_mode()
            win.right_dock.set_mode("preview")
            app.processEvents()
            assert not win.right_dock.is_queue_mode()

    # 5. Clean teardown
    win.close()
    app.processEvents()


if __name__ == "__main__":
    test_torch_stress()
    print("[PASS] Torch stress test passed!")
    test_faiss_stress()
    print("[PASS] FAISS stress test passed!")
    test_opencv_and_imagehash_stress()
    print("[PASS] OpenCV and ImageHash stress test passed!")
    test_media_metadata_libraries()
    print("[PASS] Media and Metadata stress test passed!")
    test_headless_mainwindow_stress()
    print("[PASS] Headless MainWindow stress test passed!")
    print("\nALL EMPIRICAL ENVIRONMENT STRESS TESTS COMPLETED SUCCESSFULLY!")
