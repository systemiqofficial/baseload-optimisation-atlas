"""
The registry of originals that BOA takes input values from: ``sources.toml`` next to this module.

Each ``[[source]]`` names one original as its publisher makes it available: ``url``, licence, access
date, ``tags`` for the inputs that use it (from ``TAGS``) and the tables BOA takes values from.
``access`` (from ``ACCESS``, default ``"download"``) says how BOA gets it:

- ``"download"``: one file at ``url``, pinned by ``sha256``. ``boa-sources-fetch`` downloads it into
  ``<data root>/sources/<id>/``.
- ``"cds-api"``: a data set of the Copernicus Climate Data Store. ``url`` is the data set page and
  ``dataset`` the data set name of the CDS API request. ``boa-cds-download`` gets it, not
  ``boa-sources-fetch``, so there is no ``sha256``.

A value names
its source as ``<id>: <ref>``, for example ``irena-rpgc-2024-data: Table 2.1``; ``<ref>`` is the text
before the colon of a ``tables`` line.
"""

import datetime as dt
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

REGISTRY_PATH = Path(__file__).with_name("sources.toml")
FIELDS = ("id", "citation", "url", "licence", "accessed", "tags", "tables")
# Fields that only some entries have: sha256 for access "download", dataset for access "cds-api".
OPTIONAL_FIELDS = ("access", "sha256", "dataset")
# How BOA gets the original. Only a "download" source is a file that boa-sources-fetch downloads.
ACCESS = ("download", "cds-api")
# What a source is used for. A closed set, so a misspelt tag fails instead of hiding a source.
TAGS = ("costs", "capacity-ceiling", "hydrogen")
_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RegistryError(ValueError):
    """The registry file breaks a rule of this module."""


@dataclass(frozen=True)
class Source:
    """One original, as its publisher makes it available: a file to download or a CDS data set."""

    id: str
    citation: str
    url: str
    licence: str
    accessed: dt.date
    tags: tuple[str, ...]
    tables: tuple[str, ...]
    access: str = "download"
    sha256: str = ""
    dataset: str = ""

    @property
    def downloadable(self) -> bool:
        """True for a file that boa-sources-fetch downloads."""
        return self.access == "download"

    @property
    def file(self) -> str:
        """The file name: the last part of the URL path. Empty for a source that is not a file."""
        if not self.downloadable:
            return ""
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
    if unknown := sorted(set(entry) - set(FIELDS) - set(OPTIONAL_FIELDS)):
        raise RegistryError(f"{where}: unknown key {', '.join(unknown)}")
    if not _ID.match(str(entry["id"])):
        raise RegistryError(f"{where}: id must be lower-case words joined by '-'")
    if not str(entry["url"]).startswith("https://"):
        raise RegistryError(f"{where}: url must start with https://")
    access = entry.get("access", "download")
    if access not in ACCESS:
        raise RegistryError(f"{where}: access must be one of {', '.join(ACCESS)}")
    if access == "download":
        if "sha256" not in entry:
            raise RegistryError(f"{where}: missing sha256")
        if not _SHA256.match(str(entry["sha256"])):
            raise RegistryError(f"{where}: sha256 must be 64 lower-case hex digits")
        if "dataset" in entry:
            raise RegistryError(f"{where}: dataset is only for access cds-api")
    else:
        if "sha256" in entry:
            raise RegistryError(f"{where}: sha256 is only for access download")
        if not str(entry.get("dataset", "")).strip():
            raise RegistryError(f"{where}: access cds-api needs the CDS dataset name")
    if not isinstance(entry["accessed"], dt.date):
        raise RegistryError(f"{where}: accessed must be a date (YYYY-MM-DD)")
    tags = entry["tags"]
    if not isinstance(tags, list) or not tags or len(set(tags)) != len(tags):
        raise RegistryError(f"{where}: tags must be a non-empty list without duplicates")
    if unknown_tags := sorted(set(tags) - set(TAGS)):
        raise RegistryError(f"{where}: unknown tag {', '.join(map(str, unknown_tags))}; known: {', '.join(TAGS)}")
    tables = entry["tables"]
    if not tables or not all(isinstance(t, str) and ": " in t for t in tables):
        raise RegistryError(f"{where}: tables must be a non-empty list of '<ref>: <what>' lines")
    source = Source(**{**entry, "tags": tuple(tags), "tables": tuple(tables)})
    if len(set(source.refs)) != len(source.refs):
        raise RegistryError(f"{where}: duplicate table ref")
    if source.downloadable and "." not in source.file:
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


def sources_with_tag(tag: str, registry: dict[str, Source] | None = None) -> dict[str, Source]:
    """The sources that carry ``tag``, by id, in file order."""
    if tag not in TAGS:
        raise KeyError(f"Unknown tag {tag!r}; known: {', '.join(TAGS)}")
    registry = load_registry() if registry is None else registry
    return {source_id: source for source_id, source in registry.items() if tag in source.tags}


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
