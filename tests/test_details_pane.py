"""
tests/test_details_pane.py
Explorer details / preview pane: real files in a temp folder, real Shell thumbnails
(Windows), and the wiring on the real MainWindow (offscreen).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QItemSelectionModel, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def pane(app):
    from ui.panels.details_pane import DetailsPane
    p = DetailsPane()
    p.resize(320, 700)
    p.show()
    yield p
    p.hide()
    p.deleteLater()
    QApplication.sendPostedEvents(None, 0)


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "data"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "x.txt").write_text("x")
    (d / "note.txt").write_text("dòng một\ndòng hai\n", encoding="utf-8")
    (d / "big.bin").write_bytes(b"\0" * 5000)
    img = QImage(640, 480, QImage.Format.Format_RGB32)
    img.fill(QColor("#3a7bd5"))
    assert img.save(str(d / "photo.png"))
    old = time.time() - 86400 * 3
    os.utime(d / "big.bin", (old, old))
    return d


def _wait(pred, ms=5000):
    for _ in range(ms // 20):
        if pred():
            return True
        QTest.qWait(20)
    return pred()


def _props(pane) -> dict[str, str]:
    return dict(pane.property_rows())


def test_single_file_shows_type_size_and_dates(pane, folder):
    pane.show_items([folder / "big.bin"], folder)
    pane.flush()
    assert pane.title_text() == "big.bin"
    props = _props(pane)
    assert props["Kích thước"].startswith("4,88 KB") or props["Kích thước"].startswith("4.88 KB")
    assert "5" in props["Kích thước"] and "byte" in props["Kích thước"]       # exact bytes, like Properties
    assert {"Ngày sửa đổi", "Ngày tạo", "Vị trí"} <= set(props)
    assert props["Vị trí"] == str(folder)


def test_image_shows_dimensions(pane, folder):
    pane.show_items([folder / "photo.png"], folder)
    pane.flush()
    assert _props(pane)["Kích thước ảnh"] == "640 x 480"


def test_folder_and_nothing_selected_shows_the_open_folder(pane, folder):
    pane.show_items([folder / "sub"], folder)
    pane.flush()
    assert _props(pane)["Chứa"] == "1 mục"
    assert "Kích thước" not in _props(pane)
    pane.show_items([], folder)
    pane.flush()
    assert pane.title_text() == "data"
    assert _props(pane)["Chứa"] == "4 mục"


def test_multi_selection_summary(pane, folder):
    pane.show_items([folder / "big.bin", folder / "note.txt"], folder)
    pane.flush()
    assert pane.title_text() == "2 mục được chọn"
    props = _props(pane)
    assert "Tổng kích thước" in props and props["Tệp"] == "2"
    assert "–" in props["Ngày sửa đổi"]                     # oldest – newest
    pane.show_items([folder / "big.bin", folder / "sub"], folder)
    pane.flush()
    assert "Tổng kích thước" not in _props(pane)             # Explorer gives no size once a folder is in
    assert _props(pane)["Thư mục"] == "1"


def test_rows_are_replaced_not_accumulated(pane, folder):
    for _ in range(5):
        pane.show_items([folder / "big.bin"], folder)
        pane.flush()
    assert len(pane.property_rows()) == len(set(k for k, _ in pane.property_rows()))


def test_missing_file_does_not_raise(pane, folder):
    pane.show_items([folder / "gone.txt"], folder)
    pane.flush()
    assert "Không đọc được" in pane.subtitle.text()


def test_selection_changes_are_coalesced(pane, folder, monkeypatch):
    calls = []
    monkeypatch.setattr(pane, "_render_details", lambda: calls.append(1))
    for p in ("big.bin", "note.txt", "photo.png", "big.bin"):
        pane.show_items([folder / p], folder)
    assert calls == []
    assert _wait(lambda: calls == [1], 1000)


def test_preview_mode_text_file(pane, folder):
    pane.set_mode("preview")
    pane.show_items([folder / "note.txt"], folder)
    pane.flush()
    assert pane.stack.currentWidget() is pane.preview_text
    assert pane.preview_text.toPlainText().startswith("dòng một")


def test_preview_mode_without_single_file(pane, folder):
    pane.set_mode("preview")
    pane.show_items([folder / "big.bin", folder / "note.txt"], folder)
    pane.flush()
    assert pane.stack.currentWidget() is pane.preview_image
    assert pane.preview_image.text() == "Chọn một tệp để xem trước"     # Explorer: "Select a file to preview."
    pane.show_items([folder / "sub"], folder)
    pane.flush()
    assert pane.preview_image.text() == "Không có bản xem trước."


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Shell thumbnails")
def test_shell_thumbnail_arrives_for_image(pane, folder):
    pane.show_items([folder / "photo.png"], folder)
    pane.flush()
    assert _wait(lambda: pane.thumb.pixmap() is not None and not pane.thumb.pixmap().isNull(), 8000)
    pm = pane.thumb.pixmap()
    assert pm.width() <= 256 and pm.height() <= 256
    c = pm.toImage().pixelColor(pm.width() // 2, pm.height() // 2)
    assert abs(c.blue() - 0xd5) < 24 and abs(c.red() - 0x3a) < 24           # it's our picture


# ── MainWindow wiring ──

@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    from ui.main_window import MainWindow
    w = MainWindow()
    w.closeEvent = lambda e: e.accept()
    w.show()
    yield w
    w.hide()
    w.deleteLater()


def _open(window, folder: Path):
    window._navigate_to(folder)
    window.content_panel.set_view("detail")
    model = window.content_panel.model
    _wait(lambda: model.rowCount(model.index(str(folder))) == len(list(folder.iterdir())))


def test_selection_drives_details_pane(window, folder):
    _open(window, folder)
    pane = window.right_dock.details_pane
    view = window.content_panel.detail_view
    idx = window.content_panel.model.index(str(folder / "big.bin"))
    view.selectionModel().select(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect
                                 | QItemSelectionModel.SelectionFlag.Rows)
    assert _wait(lambda: pane.title_text() == "big.bin", 2000)
    view.clearSelection()
    assert _wait(lambda: pane.title_text() == "data", 2000)


def test_alt_p_and_alt_shift_p_switch_pane_modes(window, folder):
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    _open(window, folder)
    pane = window.right_dock.details_pane
    QTest.keyClick(window.content_panel.detail_view, Qt.Key.Key_P, Qt.KeyboardModifier.AltModifier)
    assert window.right_dock.isVisible() and pane.mode == "preview"
    QTest.keyClick(window.content_panel.detail_view, Qt.Key.Key_P, Qt.KeyboardModifier.AltModifier)
    assert not window.right_dock.isVisible()                                 # same key again hides it
    QTest.keyClick(window.content_panel.detail_view, Qt.Key.Key_P,
                   Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
    assert window.right_dock.isVisible() and pane.mode == "details"
    assert window.command_bar.btn_details.isChecked()


def test_queue_mode_still_reachable(window, folder):
    _open(window, folder)
    window.right_dock.open_queue_with_paths([folder / "big.bin"])
    assert window.right_dock.is_queue_mode()
    window.right_dock.queue_dock.close_requested.emit()
    assert not window.right_dock.is_queue_mode()
    assert window.right_dock.isVisible() and window.command_bar.btn_details.isChecked()


def test_queue_opens_even_with_the_pane_hidden(window, folder):
    _open(window, folder)
    window._set_pane("")
    assert not window.right_dock.isVisible() and not window.command_bar.btn_details.isChecked()
    window.right_dock.open_queue_with_paths([folder / "big.bin"])
    assert window.right_dock.isVisible() and window.right_dock.is_queue_mode()
    window.right_dock.queue_dock.close_requested.emit()
    assert not window.right_dock.isVisible()                     # back to "pane off"
