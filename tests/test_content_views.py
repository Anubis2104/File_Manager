"""
tests/test_content_views.py
Explorer content area (phase 5): Windows Shell thumbnails, async cache, the eight view
layouts, per-folder defaults/memory, Ctrl+wheel zoom, Details columns, Explorer-style
names/sizes, status bar text, and the real Ctrl+Shift+1..8 / Ctrl+Shift+N keys.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QStandardPaths, Qt  # noqa: E402
from PyQt6.QtGui import QFont, QWheelEvent  # noqa: E402
from PyQt6.QtTest import QSignalSpy, QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QListView, QMessageBox  # noqa: E402

from ui.explorer_model import COL_DATE, COL_NAME, COL_SIZE, COL_TYPE, explorer_display_name, explorer_size_text  # noqa: E402
from ui.panels.explorer_delegate import VIEW_ORDER, VIEW_SPECS, wrap_lines  # noqa: E402

WINDOWS = sys.platform == "win32"


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    from ui.theme import theme
    if theme()._app is None:
        theme().install(a, mode="dark")
    return a


@pytest.fixture
def panel(app):
    from ui.panels.content_panel import ContentPanel
    p = ContentPanel()
    p.resize(900, 600)
    p.show()
    yield p
    p.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def _wait(pred, ms=5000):
    for _ in range(ms // 20):
        if pred():
            return True
        QTest.qWait(20)
    return pred()


def _jpeg(path: Path, size=(800, 400), color=(220, 30, 30)) -> Path:
    from PIL import Image
    Image.new("RGB", size, color).save(path)
    return path


# ── Windows Shell images ─────────────────────────────────────────

@pytest.mark.skipif(not WINDOWS, reason="Windows Shell")
def test_shell_thumbnail_keeps_content_and_aspect(app, tmp_path):
    from utils.shell_thumbs import THUMBNAIL_ONLY, shell_image
    img = shell_image(_jpeg(tmp_path / "wide.jpg"), 96, THUMBNAIL_ONLY)
    assert img is not None and img.width() == 96 and img.height() == 48
    c = img.pixelColor(48, 24)
    assert (abs(c.red() - 220) < 12, abs(c.green() - 30) < 12) == (True, True)


@pytest.mark.skipif(not WINDOWS, reason="Windows Shell")
def test_shell_thumbnail_accepts_qt_style_paths(app, tmp_path):
    """QFileSystemModel.filePath() returns 'C:/...'; the Shell rejected those (E_INVALIDARG)."""
    from utils.shell_thumbs import THUMBNAIL_ONLY, shell_image
    f = _jpeg(tmp_path / "qt path.jpg", (400, 400))
    assert shell_image(f.as_posix(), 64, THUMBNAIL_ONLY) is not None


@pytest.mark.skipif(not WINDOWS, reason="Windows Shell")
def test_content_panel_shows_shell_thumbnails(panel, tmp_path):
    """End to end: the icon view requests thumbnails for the model's paths and gets them."""
    from ui.thumbnails import ThumbnailCache
    for i in range(3):
        _jpeg(tmp_path / f"p{i}.jpg", (500, 300), (40 * i, 100, 200))
    spy = QSignalSpy(ThumbnailCache.instance().ready)
    panel.load_directory(tmp_path)
    panel.set_view("large")
    QApplication.processEvents()
    panel.grid_view.viewport().repaint()
    assert _wait(lambda: len(spy) >= 3, 10000), f"only {len(spy)} thumbnails arrived"


@pytest.mark.skipif(not WINDOWS, reason="Windows Shell")
def test_shell_icons_keep_transparency_and_thumbnail_only_means_only(app, tmp_path):
    from utils.shell_thumbs import ICON_ONLY, THUMBNAIL_ONLY, shell_image
    txt = tmp_path / "notes.txt"
    txt.write_text("x")
    icon = shell_image(txt, 48, ICON_ONLY)
    assert icon is not None and icon.pixelColor(0, 0).alpha() == 0       # not a black square
    assert shell_image(txt, 48, THUMBNAIL_ONLY) is None
    assert shell_image(tmp_path / "missing.png", 48) is None


@pytest.mark.skipif(not WINDOWS, reason="Windows Shell")
def test_thumbnail_cache_is_async_and_cached(app, tmp_path):
    from ui.thumbnails import ThumbnailCache
    cache = ThumbnailCache.instance()
    f = _jpeg(tmp_path / "a.jpg", (300, 300), (10, 200, 40))
    assert cache.get(f, 64) is None                                       # never blocks the caller
    # The cache is a process-wide singleton: other tests' thumbnails also emit `ready`,
    # so wait for this file's own pixmap instead of counting signals
    assert _wait(lambda: cache.get(f, 64) is not None)
    pm = cache.get(f, 64)
    assert pm is not None and not pm.isNull()
    _jpeg(f, (300, 300), (0, 0, 255))                                     # edited photo -> new key
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))
    assert cache.get(f, 64) is None


# ── Explorer naming / sizes ─────────────────────────────────────

@pytest.mark.skipif(not WINDOWS, reason="registry file types")
def test_known_extensions_hidden_like_explorer():
    assert explorer_display_name("report.txt", False, hide_extensions=True) == "report"
    assert explorer_display_name("report.txt", False, hide_extensions=False) == "report.txt"
    assert explorer_display_name("archive.zzqq9", False, hide_extensions=True) == "archive.zzqq9"  # unregistered
    assert explorer_display_name("My.Folder", True, hide_extensions=True) == "My.Folder"
    assert explorer_display_name(".gitignore", False, hide_extensions=True) == ".gitignore"


def test_explorer_size_text_rounds_up_to_kb():
    from PyQt6.QtCore import QLocale
    en = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
    assert explorer_size_text(0, en) == "0 KB"
    assert explorer_size_text(1, en) == "1 KB"
    assert explorer_size_text(1025, en) == "2 KB"
    assert explorer_size_text(5 * 1024 * 1024, en) == "5,120 KB"


def test_status_bar_text(app, tmp_path):
    from ui.widgets.statusbar import AppStatusBar, explorer_bytes
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"x" * 3000); b.write_bytes(b"x" * 2000)
    bar = AppStatusBar()
    bar.set_item_count(12)
    bar.update_selection([a, b])
    assert bar.lbl_items.text() == "12 mục"
    assert bar.lbl_selection.text().startswith("2 mục được chọn") and "KB" in bar.lbl_selection.text()
    bar.update_selection([a, tmp_path])                                   # folder selected -> no size
    assert bar.lbl_selection.text() == "2 mục được chọn"
    assert explorer_bytes(512) == "512 bytes"


def test_wrap_lines_elides_third_line():
    font = QFont("Segoe UI", 9)
    lines = wrap_lines("a very long photo name that keeps going and going.jpg", font, 80, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")


# ── Views ────────────────────────────────────────────────────────

def test_eight_layouts_configure_the_views(panel, tmp_path):
    (tmp_path / "x.txt").write_text("1")
    panel.load_directory(tmp_path)
    spy = QSignalSpy(panel.view_mode_changed)
    gv = panel.grid_view
    for mode in VIEW_ORDER:
        panel.set_view(mode)
        assert panel.view_mode == mode
        if mode == "detail":
            assert panel.stack.currentIndex() == 1
            continue
        spec = VIEW_SPECS[mode]
        assert panel.stack.currentIndex() in (0, 2)                       # list view or empty dropzone
        assert gv.iconSize().width() == spec.icon
        assert panel.item_delegate.spec is spec
        if spec.kind in ("icon", "tile"):
            assert gv.viewMode() == QListView.ViewMode.IconMode and gv.gridSize() == spec.cell
        elif mode == "list":
            assert gv.flow() == QListView.Flow.TopToBottom and gv.isWrapping()
        elif mode == "small":
            assert gv.flow() == QListView.Flow.LeftToRight and gv.isWrapping()
        elif mode == "content":
            assert gv.flow() == QListView.Flow.TopToBottom and not gv.isWrapping()
    assert len(spy) >= len(VIEW_ORDER) - 1
    panel.set_view("grid")                                                # old alias
    assert panel.view_mode == "large"


def test_default_view_by_folder_type_and_memory(panel, tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(); b.mkdir()
    panel.load_directory(a)
    assert panel.view_mode == "detail"                                    # Explorer's general items
    panel.set_view("tiles")
    panel.load_directory(b)
    assert panel.view_mode == "detail"
    panel.load_directory(a)
    assert panel.view_mode == "tiles"                                     # remembered per folder
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    if pictures and Path(pictures).is_dir():
        panel.load_directory(Path(pictures))
        assert panel.view_mode == "large"


def test_ctrl_wheel_zooms_through_icon_sizes(panel, tmp_path):
    panel.load_directory(tmp_path)
    panel.set_view("medium")
    vp = panel.grid_view.viewport()

    def wheel(dy):
        ev = QWheelEvent(QPointF(10, 10), QPointF(vp.mapToGlobal(QPoint(10, 10))), QPoint(0, 0), QPoint(0, dy),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(vp, ev)
    wheel(120)
    assert panel.view_mode == "large"
    wheel(120); wheel(120)
    assert panel.view_mode == "xl"                                        # clamps at the largest
    wheel(-120)
    assert panel.view_mode == "large"


def test_details_columns_in_explorer_order(panel, tmp_path):
    header = panel.detail_view.horizontalHeader()
    assert [header.logicalIndex(v) for v in range(4)] == [COL_NAME, COL_DATE, COL_TYPE, COL_SIZE]


def test_item_count_signal(panel, tmp_path):
    for n in ("1.txt", "2.txt", "3.txt"):
        (tmp_path / n).write_text(n)
    spy = QSignalSpy(panel.item_count_changed)
    panel.load_directory(tmp_path)
    assert _wait(lambda: len(spy) > 0 and spy[-1][0] == 3)


# ── Real keyboard shortcuts on the main window ───────────────────

def test_layout_and_new_folder_shortcuts_fire(app, tmp_path, monkeypatch):
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
    monkeypatch.chdir(tmp_path)
    from ui.main_window import MainWindow
    created = []
    monkeypatch.setattr(MainWindow, "_create_new_folder", lambda self, d: created.append(d))
    w = MainWindow()
    w.closeEvent = lambda e: e.accept()
    w.show()
    try:
        w._navigate_to(tmp_path)
        w.activateWindow()
        assert QTest.qWaitForWindowActive(w, 3000)        # window-level shortcuts need an active window
        QTest.keyClick(w, Qt.Key.Key_6, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert w.content_panel.view_mode == "detail"
        QTest.keyClick(w, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert w.content_panel.view_mode == "large"
        assert w.command_bar.view_actions["large"].isChecked()
        assert w.app_statusbar.btn_large.isChecked() and not w.app_statusbar.btn_details.isChecked()
        QTest.keyClick(w, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert created == [tmp_path]                                      # was ambiguous with the menu action
    finally:
        w.hide()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


@pytest.mark.skipif(not WINDOWS, reason="Windows Shell type names")
def test_type_column_uses_windows_type_names_not_mime(panel, tmp_path):
    from ui.explorer_model import shell_type_name
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "Sub").mkdir()
    panel.load_directory(tmp_path)
    model = panel.model
    _wait(lambda: model.rowCount(model.index(str(tmp_path))) == 2)
    jpg = model.index(str(tmp_path / "a.jpg"))
    sub = model.index(str(tmp_path / "Sub"))
    jpg_type = model.index(jpg.row(), COL_TYPE, jpg.parent()).data()
    assert jpg_type == shell_type_name(".jpg") and "Joint Photographic" not in jpg_type
    assert model.index(sub.row(), COL_TYPE, sub.parent()).data() == shell_type_name("", True)


def test_vietnamese_column_headers(panel):
    m = panel.model
    labels = [m.headerData(c, Qt.Orientation.Horizontal) for c in (COL_NAME, COL_DATE, COL_TYPE, COL_SIZE)]
    assert labels == ["Tên", "Ngày sửa đổi", "Loại", "Kích thước"]


def test_status_bar_skips_size_for_huge_selections(app, tmp_path, monkeypatch):
    import ui.widgets.statusbar as sb
    monkeypatch.setattr(sb, "MAX_SIZED_SELECTION", 3)
    files = []
    for i in range(4):
        f = tmp_path / f"{i}.bin"
        f.write_bytes(b"x" * 2048)
        files.append(f)
    bar = sb.AppStatusBar()
    bar.update_selection(files[:3])
    assert "KB" in bar.lbl_selection.text()
    bar.update_selection(files)
    assert bar.lbl_selection.text() == "4 mục được chọn"


# ── Activation: one navigation per double-click ──────────────────

@pytest.mark.parametrize("view_attr", ["grid_view", "detail_view"])
def test_double_click_on_folder_navigates_once(panel, tmp_path, view_attr):
    """Qt emits both doubleClicked and activated on a double-click; only one may navigate."""
    (tmp_path / "Sub").mkdir()
    panel.load_directory(tmp_path)
    panel.stack.setCurrentIndex(0 if view_attr == "grid_view" else 1)
    view = getattr(panel, view_attr)
    root = view.rootIndex()
    assert _wait(lambda: panel.model.rowCount(root) == 1)
    index = panel.model.index(0, 0, root)
    view.scrollTo(index)
    QTest.qWait(50)

    spy = QSignalSpy(panel.folder_navigated)
    pos = view.visualRect(index).center()
    # A real double-click: Qt ignores the DblClick event unless a press on the same index preceded it
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.qWait(50)

    assert [Path(args[0]).name for args in spy] == ["Sub"]


def test_enter_key_on_folder_still_navigates(panel, tmp_path):
    (tmp_path / "Sub").mkdir()
    panel.load_directory(tmp_path)
    panel.stack.setCurrentIndex(1)
    view = panel.detail_view
    root = view.rootIndex()
    assert _wait(lambda: panel.model.rowCount(root) == 1)
    view.setCurrentIndex(panel.model.index(0, 0, root))
    view.setFocus()

    spy = QSignalSpy(panel.folder_navigated)
    QTest.keyClick(view, Qt.Key.Key_Return)

    assert [Path(args[0]).name for args in spy] == ["Sub"]
