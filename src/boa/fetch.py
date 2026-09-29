"""Download a pinned zip over HTTPS, check its sha256 and extract it."""

import hashlib
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

CHUNK_BYTES = 1 << 20


def fetch_verified_zip(
    url: str,
    sha256: str,
    extract_to: Path,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> None:
    """
    Download ``url``, check it against ``sha256``, extract it into ``extract_to`` and delete the zip.

    The download streams to a ``.part`` file that is always removed afterwards, so an interrupted
    or corrupted download never leaves a zip that looks complete, and a checksum mismatch
    extracts nothing. ``on_progress(done, total)`` is called per chunk; ``total`` is None when
    the server sends no length.
    """
    extract_to.mkdir(parents=True, exist_ok=True)
    part = extract_to / (url.rsplit("/", 1)[-1] + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=60) as response, part.open("wb") as out:
            length = response.headers.get("Content-Length")
            total = int(length) if length else None
            done = 0
            while chunk := response.read(CHUNK_BYTES):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
        if digest.hexdigest() != sha256:
            raise ValueError(f"sha256 mismatch for {url}: expected {sha256}, got {digest.hexdigest()}")
        with zipfile.ZipFile(part) as zf:
            zf.extractall(extract_to)
    finally:
        part.unlink(missing_ok=True)
