import hashlib
import zipfile

import pytest

from boa.fetch import fetch_verified_zip


def _write_zip(path, members: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fetch_extracts_and_leaves_no_zip_behind(tmp_path):
    source = tmp_path / "package.zip"
    sha256 = _write_zip(source, {"folder/jan.nc": b"jan", "package.json": b"{}"})
    dest = tmp_path / "dest"
    progress = []

    fetch_verified_zip(source.as_uri(), sha256, dest, on_progress=lambda done, total: progress.append((done, total)))

    assert (dest / "folder" / "jan.nc").read_bytes() == b"jan"
    assert sorted(p.name for p in dest.iterdir()) == ["folder", "package.json"]
    assert progress[-1] == (source.stat().st_size, source.stat().st_size)


def test_fetch_refuses_a_checksum_mismatch_and_extracts_nothing(tmp_path):
    source = tmp_path / "package.zip"
    _write_zip(source, {"folder/jan.nc": b"jan"})
    dest = tmp_path / "dest"

    with pytest.raises(ValueError, match="sha256 mismatch"):
        fetch_verified_zip(source.as_uri(), "0" * 64, dest)

    assert list(dest.iterdir()) == []
