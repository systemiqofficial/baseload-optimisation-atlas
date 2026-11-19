"""
The registry of original source files behind the cost workbook (CAPEX, OPEX, cost of capital).

The registry is ``cost_sources.toml`` next to this module. It has one ``[[source]]`` entry per
original file, as the publisher makes it available for download. Each entry records where the
file comes from (``url``), how to check it (``sha256``), its licence, and the basis of the values
that BOA takes from it (one ``[[source.item]]`` per table or figure).

``boa-sources-fetch`` downloads the files into ``<data root>/sources/<id>/``. A cost workbook row
names its source as ``<id>: <item ref>``, for example ``irena-rpgc-2024-data: Table 2.1``.

An entry with ``status = "unresolved"`` is a source that a cost package uses but whose original
file is not yet found. It has no ``url`` or ``sha256``, and the fetch step skips it.
"""

import datetime as dt
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("cost_sources.toml")

STATUSES = ("pinned", "unresolved")
PRICE_BASES = ("real", "nominal", "not applicable", "unknown")
TAX_BASES = ("pre-tax", "after-tax", "not applicable", "unknown")
_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RegistryError(ValueError):
    """The registry file breaks a rule of the schema in this module."""


@dataclass(frozen=True)
class SourceItem:
    """One table or figure of a source that a cost package reads values from."""

    ref: str
    content: str
    unit: str
    price_basis: str
    tax: str
    currency_year: int | None = None


@dataclass(frozen=True)
class Source:
    """One original file, as its publisher makes it available for download."""

    id: str
    status: str
    citation: str
    publisher: str
    licence: str
    redistribute: bool
    used_by: tuple[str, ...]
    landing_page: str = ""
    url: str = ""
    file: str = ""
    accessed: dt.date | None = None
    sha256: str = ""
    note: str = ""
    items: tuple[SourceItem, ...] = field(default_factory=tuple)

    @property
    def pinned(self) -> bool:
        return self.status == "pinned"

    def item(self, ref: str) -> SourceItem:
        """The item with this ref, for example ``Table 2.1``."""
        for item in self.items:
            if item.ref == ref:
                return item
        raise KeyError(f"Source {self.id!r} has no item {ref!r}")

    def label(self, ref: str) -> str:
        """The text that a workbook ``source`` column holds for one item: ``<id>: <ref>``."""
        self.item(ref)
        return f"{self.id}: {ref}"


def _require(entry: dict, key: str, where: str, kind: type) -> object:
    if key not in entry:
        raise RegistryError(f"{where}: missing {key!r}")
    value = entry[key]
    if not isinstance(value, kind) or (kind is str and not value.strip()):
        raise RegistryError(f"{where}: {key!r} must be a non-empty {kind.__name__}")
    return value


def _parse_item(entry: dict, where: str) -> SourceItem:
    ref = _require(entry, "ref", where, str)
    where = f"{where} item {ref!r}"
    price_basis = _require(entry, "price_basis", where, str)
    if price_basis not in PRICE_BASES:
        raise RegistryError(f"{where}: price_basis must be one of {PRICE_BASES}, not {price_basis!r}")
    tax = _require(entry, "tax", where, str)
    if tax not in TAX_BASES:
        raise RegistryError(f"{where}: tax must be one of {TAX_BASES}, not {tax!r}")
    currency_year = entry.get("currency_year")
    if currency_year is not None and not isinstance(currency_year, int):
        raise RegistryError(f"{where}: currency_year must be an integer year")
    return SourceItem(
        ref=ref,
        content=_require(entry, "content", where, str),
        unit=_require(entry, "unit", where, str),
        price_basis=price_basis,
        tax=tax,
        currency_year=currency_year,
    )


def _parse_source(entry: dict, index: int) -> Source:
    source_id = _require(entry, "id", f"source #{index + 1}", str)
    where = f"source {source_id!r}"
    if not _ID.match(source_id):
        raise RegistryError(f"{where}: id must be lower-case words joined by '-'")
    status = _require(entry, "status", where, str)
    if status not in STATUSES:
        raise RegistryError(f"{where}: status must be one of {STATUSES}, not {status!r}")
    redistribute = entry.get("redistribute")
    if not isinstance(redistribute, bool):
        raise RegistryError(f"{where}: 'redistribute' must be true or false")
    used_by = entry.get("used_by")
    if not isinstance(used_by, list) or not used_by or not all(isinstance(u, str) for u in used_by):
        raise RegistryError(f"{where}: 'used_by' must be a non-empty list of package names")
    items = tuple(_parse_item(item, where) for item in entry.get("item", []))
    if not items:
        raise RegistryError(f"{where}: needs at least one [[source.item]]")
    refs = [item.ref for item in items]
    if len(set(refs)) != len(refs):
        raise RegistryError(f"{where}: duplicate item ref")
    fields = {
        "url": entry.get("url", ""),
        "file": entry.get("file", ""),
        "sha256": entry.get("sha256", ""),
        "accessed": entry.get("accessed"),
    }
    if status == "pinned":
        for key in ("url", "file", "sha256"):
            _require(entry, key, where, str)
        if not isinstance(fields["accessed"], dt.date):
            raise RegistryError(f"{where}: 'accessed' must be a date (YYYY-MM-DD)")
        if not _SHA256.match(fields["sha256"]):
            raise RegistryError(f"{where}: sha256 must be 64 lower-case hex digits")
        if not fields["url"].startswith("https://"):
            raise RegistryError(f"{where}: url must start with https://")
        if "/" in fields["file"] or "\\" in fields["file"]:
            raise RegistryError(f"{where}: file must be a bare file name")
    elif fields["sha256"]:
        raise RegistryError(f"{where}: an unresolved source has no sha256")
    return Source(
        id=source_id,
        status=status,
        citation=_require(entry, "citation", where, str),
        publisher=_require(entry, "publisher", where, str),
        licence=_require(entry, "licence", where, str),
        redistribute=redistribute,
        used_by=tuple(used_by),
        landing_page=entry.get("landing_page", ""),
        note=entry.get("note", ""),
        items=items,
        **fields,
    )


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
