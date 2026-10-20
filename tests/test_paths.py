import os

import pytest

from fileconverter.utils.paths import expand_inputs


def test_absolute_glob(work):
    (work / "a.png").write_bytes(b"x")
    (work / "b.png").write_bytes(b"x")
    (work / "c.txt").write_bytes(b"x")
    found = expand_inputs([str(work / "*.png")])
    assert [p.name for p in found] == ["a.png", "b.png"]


def test_recursive_glob(work, monkeypatch):
    (work / "sub").mkdir()
    (work / "top.png").write_bytes(b"x")
    (work / "sub" / "deep.png").write_bytes(b"x")
    monkeypatch.chdir(work)
    assert sorted(p.name for p in expand_inputs(["*.png"], recursive=True)) == [
        "deep.png",
        "top.png",
    ]
    assert [p.name for p in expand_inputs(["*.png"])] == ["top.png"]


def test_file_name_with_glob_characters(work):
    path = work / "photo [1].png"
    path.write_bytes(b"x")
    assert expand_inputs([str(path)]) == [path]


def test_directory_skips_hidden_files_and_can_be_kept(work):
    folder = work / "folder"
    (folder / ".git").mkdir(parents=True)
    (folder / ".git" / "config").write_text("x")
    (folder / ".DS_Store").write_text("x")
    (folder / "real.txt").write_text("x")
    assert [p.name for p in expand_inputs([str(folder)], recursive=True)] == ["real.txt"]
    assert expand_inputs([str(folder)], keep_dirs=True) == [folder]


def test_missing_input_raises(work):
    with pytest.raises(FileNotFoundError):
        expand_inputs([os.path.join(str(work), "nope.png")])
