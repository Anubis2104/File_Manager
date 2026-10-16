"""
tests/test_file_ops.py
Explorer-style paste on the real filesystem (core/file_ops.py).
"""
from __future__ import annotations

from pathlib import Path

from core.file_ops import explorer_copy_name, paste, summarize, unique_name


def _write(p: Path, data: bytes = b"data") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_copy_into_same_folder_uses_explorer_copy_names(tmp_path):
    f = _write(tmp_path / "photo.jpg", b"1")
    r1 = paste([f], tmp_path, move=False)
    r2 = paste([f], tmp_path, move=False)
    assert r1[0].dst == tmp_path / "photo - Copy.jpg"
    assert r2[0].dst == tmp_path / "photo - Copy (2).jpg"
    assert (tmp_path / "photo - Copy (2).jpg").read_bytes() == b"1"
    assert f.exists()


def test_copy_name_rules_for_dotfiles_and_folders(tmp_path):
    assert explorer_copy_name(tmp_path, ".gitignore", False).name == ".gitignore - Copy"
    assert explorer_copy_name(tmp_path, "archive.tar.gz", False).name == "archive.tar - Copy.gz"
    assert explorer_copy_name(tmp_path, "My.Folder", True).name == "My.Folder - Copy"


def test_copy_to_other_folder_never_overwrites(tmp_path):
    src = _write(tmp_path / "a" / "note.txt", b"new")
    existing = _write(tmp_path / "b" / "note.txt", b"old")
    res = paste([src], tmp_path / "b", move=False)
    assert res[0].dst == tmp_path / "b" / "note (2).txt"
    assert existing.read_bytes() == b"old"
    assert res[0].dst.read_bytes() == b"new"


def test_copy_folder_recursively(tmp_path):
    _write(tmp_path / "src" / "Album" / "1.jpg", b"1")
    _write(tmp_path / "src" / "Album" / "sub" / "2.jpg", b"2")
    (tmp_path / "dest").mkdir()
    res = paste([tmp_path / "src" / "Album"], tmp_path / "dest", move=False)
    assert res[0].ok
    assert (tmp_path / "dest" / "Album" / "sub" / "2.jpg").read_bytes() == b"2"
    assert (tmp_path / "src" / "Album" / "1.jpg").exists()


def test_move_file_and_folder(tmp_path):
    f = _write(tmp_path / "a" / "x.txt")
    d = tmp_path / "a" / "Dir"
    _write(d / "inner.txt")
    (tmp_path / "b").mkdir()
    res = paste([f, d], tmp_path / "b", move=True)
    assert all(r.ok for r in res)
    assert not f.exists() and not d.exists()
    assert (tmp_path / "b" / "x.txt").exists() and (tmp_path / "b" / "Dir" / "inner.txt").exists()


def test_move_into_same_folder_is_a_noop(tmp_path):
    f = _write(tmp_path / "x.txt")
    res = paste([f], tmp_path, move=True)
    assert res[0].ok and res[0].skipped and f.exists()
    assert summarize(res) == (0, [])


def test_folder_cannot_go_into_itself(tmp_path):
    d = tmp_path / "Dir"
    _write(d / "sub" / "f.txt")
    for move in (False, True):
        res = paste([d], d / "sub", move=move)
        assert not res[0].ok and res[0].error
    assert (d / "sub" / "f.txt").exists()
    assert not (d / "sub" / "Dir").exists()


def test_missing_source_reported_and_others_continue(tmp_path):
    ok = _write(tmp_path / "ok.txt")
    (tmp_path / "out").mkdir()
    res = paste([tmp_path / "gone.txt", ok], tmp_path / "out", move=False)
    done, errors = summarize(res)
    assert done == 1 and len(errors) == 1 and "gone.txt" in errors[0]


def test_unique_name(tmp_path):
    _write(tmp_path / "a.txt")
    _write(tmp_path / "a (2).txt")
    assert unique_name(tmp_path, "a.txt", False).name == "a (3).txt"
    assert unique_name(tmp_path, "b.txt", False).name == "b.txt"
