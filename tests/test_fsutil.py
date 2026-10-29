"""
Contracts for `replace_dir`, the folder swap every store writer uses.

Windows refuses a rename while another process (indexer, antivirus) holds a handle in
either folder, and keeps a deleted folder's name until that handle closes. CI cannot
reproduce that race, so these tests stand it in with a `Path.rename` that raises
PermissionError a set number of times.
"""

from pathlib import Path

import pytest

from boa.fsutil import replace_dir


def _folder(path: Path, content: str) -> Path:
    path.mkdir()
    (path / "data.txt").write_text(content)
    return path


@pytest.fixture
def flaky_rename(monkeypatch):
    """Make the next `fails` calls to `Path.rename` raise PermissionError."""
    real_rename = Path.rename
    state = {"fails": 0}

    def rename(self, target):
        if state["fails"] > 0:
            state["fails"] -= 1
            raise PermissionError(13, "Access is denied", str(self))
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    return state


def test_replaces_an_existing_folder_and_leaves_nothing_beside_it(tmp_path):
    src = _folder(tmp_path / "store.zarr.tmp", "new")
    dest = _folder(tmp_path / "store.zarr", "old")
    replace_dir(src, dest)
    assert (dest / "data.txt").read_text() == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["store.zarr"]


def test_moves_into_a_free_name(tmp_path):
    src = _folder(tmp_path / "store.zarr.tmp", "new")
    replace_dir(src, tmp_path / "store.zarr")
    assert (tmp_path / "store.zarr" / "data.txt").read_text() == "new"
    assert not src.exists()


def test_retries_a_locked_rename_until_it_succeeds(tmp_path, flaky_rename):
    src = _folder(tmp_path / "store.zarr.tmp", "new")
    dest = _folder(tmp_path / "store.zarr", "old")
    flaky_rename["fails"] = 3
    replace_dir(src, dest, delay=0)
    assert (dest / "data.txt").read_text() == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["store.zarr"]


def test_gives_up_naming_the_complete_folder_and_the_replaced_one(tmp_path, monkeypatch):
    """
    The old folder moves aside on the first attempt, then the new one stays locked. Neither
    may be deleted: the new one is a finished build the user can still rename by hand.
    """
    src = _folder(tmp_path / "store.zarr.tmp", "new")
    dest = _folder(tmp_path / "store.zarr", "old")
    real_rename = Path.rename

    def rename(self, target):
        if self == src:
            raise PermissionError(13, "Access is denied", str(self))
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(PermissionError, match="rename it to .* by hand") as err:
        replace_dir(src, dest, attempts=3, delay=0)
    assert (src / "data.txt").read_text() == "new"
    assert not dest.exists()
    (old,) = tmp_path.glob("store.zarr.old-*")
    assert (old / "data.txt").read_text() == "old"
    assert str(old) in str(err.value)


def test_clears_leftovers_from_an_earlier_swap(tmp_path):
    """A leftover from a swap whose cleanup was blocked must not stop the next one."""
    _folder(tmp_path / "store.zarr.old-deadbeef", "older")
    src = _folder(tmp_path / "store.zarr.tmp", "new")
    dest = _folder(tmp_path / "store.zarr", "old")
    replace_dir(src, dest)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["store.zarr"]
