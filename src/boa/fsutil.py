"""Swap a finished folder into the place its readers look, robust to Windows file locks."""

import shutil
import time
import uuid
from pathlib import Path

SWAP_ATTEMPTS = 8
SWAP_DELAY_S = 0.25


def replace_dir(src: Path, dest: Path, attempts: int = SWAP_ATTEMPTS, delay: float = SWAP_DELAY_S) -> None:
    """
    Move the finished folder `src` to `dest`, replacing any folder already there.

    On Windows a folder cannot be renamed while another process (search indexer, antivirus,
    a file watcher) holds a handle in it, and a deleted folder keeps its name until that
    handle closes; both fail as PermissionError. So the old `dest` is renamed aside instead
    of deleted before the swap, which frees its name at once, and each rename is retried
    with exponential backoff (about 32 s in all at the defaults). The old folder is deleted
    last, best effort, under a name unique to this call so a leftover that is still locked
    never blocks a later swap; leftovers from earlier calls are cleared on entry.
    """
    for leftover in dest.parent.glob(f"{dest.name}.old-*"):
        shutil.rmtree(leftover, ignore_errors=True)
    old = dest.with_name(f"{dest.name}.old-{uuid.uuid4().hex[:8]}")
    for attempt in range(attempts):
        try:
            if dest.exists():
                dest.rename(old)
            src.rename(dest)
            break
        except PermissionError as exc:
            if attempt < attempts - 1:
                time.sleep(delay * 2**attempt)
                continue
            replaced = f" The folder it replaces is at {old}." if old.exists() else ""
            raise PermissionError(
                f"Could not move {src} to {dest} after {attempts} attempts: another process holds a file "
                f"in one of them. {src} is complete; rename it to {dest} by hand to keep it.{replaced}"
            ) from exc
    shutil.rmtree(old, ignore_errors=True)
