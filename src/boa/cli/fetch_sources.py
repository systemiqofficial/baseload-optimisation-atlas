"""
Download the original files that BOA takes input values from, and check their sha256.

Each source in ``boa/config/sources.toml`` is downloaded from its publisher URL into
``<data root>/sources/<id>/<file>``, outside the repository. A file that is already there with the
pinned sha256 is not downloaded again. A download with a different sha256 is kept as
``<file>.mismatch`` for review, and the command exits with an error.

    boa-sources-fetch                         # every source
    boa-sources-fetch irena-rpgc-2024-data    # one source
    boa-sources-fetch --tag capacity-ceiling  # every source with one tag
    boa-sources-fetch --list                  # show the registry and what is on disk
"""

import argparse
import hashlib
import shutil
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

from boa.config.paths import default_root
from boa.config.sources import TAGS, Source, get_source, load_registry, source_path, sources_with_tag

CHUNK_BYTES = 1 << 20
# Some publisher sites refuse requests that send no browser-like User-Agent.
USER_AGENT = "Mozilla/5.0 (compatible; boa-sources-fetch)"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    """Stream ``url`` to ``target`` through a ``.part`` file, so a broken download leaves no file."""
    part = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:
            shutil.copyfileobj(response, out, CHUNK_BYTES)
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)


def fetch_source(
    source: Source,
    root: Path,
    downloader: Callable[[str, Path], None] = download,
) -> str:
    """
    Make sure ``<root>/sources/<id>/<file>`` holds the pinned file. Returns what was done.

    Raises ValueError when the downloaded file has a different sha256; the file is then kept
    as ``<file>.mismatch`` and the pinned path is left as it was.
    """
    target = source_path(root, source)
    if target.exists() and file_sha256(target) == source.sha256:
        return "present"
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(target.name + ".download")
    try:
        downloader(source.url, staged)
        got = file_sha256(staged)
        if got != source.sha256:
            mismatch = target.with_name(target.name + ".mismatch")
            staged.replace(mismatch)
            raise ValueError(
                f"{source.id}: sha256 mismatch for {source.url}\n"
                f"  pinned {source.sha256}\n  got    {got}\n  kept as {mismatch}"
            )
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)
    return "downloaded"


def _list(registry: dict[str, Source], root: Path) -> None:
    for source in registry.values():
        path = source_path(root, source)
        state = "present" if path.exists() and file_sha256(path) == source.sha256 else "missing"
        print(f"{source.id:32} {state:8} {','.join(source.tags):24} {source.licence}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", help="Source ids to fetch (default: every source)")
    parser.add_argument("--root", type=Path, help="Data root (default: $BOA_DATA_ROOT, else ~/.boa)")
    parser.add_argument("--tag", choices=TAGS, help="Only the sources with this tag")
    parser.add_argument("--list", action="store_true", help="List the sources and their state on disk")
    args = parser.parse_args(argv)

    registry = load_registry() if args.tag is None else sources_with_tag(args.tag)
    root = args.root or default_root()
    if args.list:
        _list(registry, root)
        return 0
    try:
        sources = [get_source(i, registry) for i in args.ids] if args.ids else list(registry.values())
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    failed = 0
    for source in sources:
        try:
            print(f"{source.id}: {fetch_source(source, root, download)}")
        except (ValueError, OSError) as exc:
            failed += 1
            print(f"{source.id}: FAILED: {exc}", file=sys.stderr)
    print(f"Sources folder: {root / 'sources'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
