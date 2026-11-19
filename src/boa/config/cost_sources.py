"""
The registry of original files behind the core cost workbooks: ``cost_sources.toml`` next to this module.

Each ``[[source]]`` names one file as its publisher makes it available for download: ``url``, ``sha256``,
licence, access date and the tables BOA takes values from. ``boa-sources-fetch`` downloads the files
into ``<data root>/sources/<id>/``. A cost workbook row names its source as ``<id>: <ref>``, for example
``irena-rpgc-2024-data: Table 2.1``; ``<ref>`` is the text before the colon of a ``tables`` line.
"""

import datetime as dt
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

REGISTRY_PATH = Path(__file__).with_name("cost_sources.toml")
FIELDS = ("id", "citation", "url", "sha256", "licence", "accessed", "tables")
_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RegistryError(ValueError):
    """The registry file breaks a rule of this module."""


@dataclass(frozen=True)
class Source:
    """One original file, as its publisher makes it available for download."""

    id: str
    citation: str
    url: str
    sha256: str
    licence: str
    accessed: dt.date
    tables: tuple[str, ...]

    @property
    def file(self) -> str:
        """The file name: the last part of the URL path."""
        return PurePosixPath(urlparse(self.url).path).name

    @property
    def refs(self) -> tuple[str, ...]:
        return tuple(line.split(":", 1)[0] for line in self.tables)

    def label(self, ref: str) -> str:
        """The text of a workbook ``source`` column for one table: ``<id>: <ref>``."""
        if ref not in self.refs:
            raise KeyError(f"Source {self.id!r} has no table {ref!r}")
        return f"{self.id}: {ref}"


def _parse_source(entry: dict, index: int) -> Source:
    where = f"source {entry.get('id', f'#{index + 1}')!r}"
    if missing := [key for key in FIELDS if key not in entry]:
        raise RegistryError(f"{where}: missing {', '.join(missing)}")
    if unknown := sorted(set(entry) - set(FIELDS)):
        raise RegistryError(f"{where}: unknown key {', '.join(unknown)}")
    if not _ID.match(str(entry["id"])):
        raise RegistryError(f"{where}: id must be lower-case words joined by '-'")
    if not str(entry["url"]).startswith("https://"):
        raise RegistryError(f"{where}: url must start with https://")
    if not _SHA256.match(str(entry["sha256"])):
        raise RegistryError(f"{where}: sha256 must be 64 lower-case hex digits")
    if not isinstance(entry["accessed"], dt.date):
        raise RegistryError(f"{where}: accessed must be a date (YYYY-MM-DD)")
    tables = entry["tables"]
    if not tables or not all(isinstance(t, str) and ": " in t for t in tables):
        raise RegistryError(f"{where}: tables must be a non-empty list of '<ref>: <what>' lines")
    source = Source(**{**entry, "tables": tuple(tables)})
    if len(set(source.refs)) != len(source.refs):
        raise RegistryError(f"{where}: duplicate table ref")
    if "." not in source.file:
        raise RegistryError(f"{where}: url must end in a file name")
    return source


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Source]:
    """Read and check the registry. Returns the sources by id, in file order."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    sources: dict[str, Source] = {}
    for index, entry in enumerate(data.get("source", [])):
        source = _parse_source(entry, index)
        if source.id in sources:
            raise RegistryError(f"source {source.id!r}: duplicate id")
        sources[source.id] = source
    if not sources:
        raise RegistryError(f"{path.name}: no [[source]] entries")
    return sources


def get_source(source_id: str, registry: dict[str, Source] | None = None) -> Source:
    """One source by id. Raises KeyError with the known ids when the id is not registered."""
    registry = load_registry() if registry is None else registry
    try:
        return registry[source_id]
    except KeyError:
        raise KeyError(f"No source {source_id!r} in the registry; known ids: {', '.join(registry)}") from None


def source_path(root: Path, source: Source) -> Path:
    """Where the fetch step keeps the source's original file: ``<root>/sources/<id>/<file>``."""
    return root / "sources" / source.id / source.file
