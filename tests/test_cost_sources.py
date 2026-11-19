"""The cost source registry and the boa-sources-fetch step."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from boa.cli import fetch_sources
from boa.config.cost_sources import (
    RegistryError,
    Source,
    SourceItem,
    get_source,
    load_registry,
    source_path,
)

PAYLOAD = b"original file bytes"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()

VALID_ENTRY = f"""
[[source]]
id = "demo-source"
status = "pinned"
citation = "Demo (2025), A demo source."
publisher = "Demo"
licence = "CC BY 4.0"
redistribute = true
used_by = ["boa-cost-data-irena"]
url = "https://example.org/demo.xlsx"
file = "demo.xlsx"
accessed = 2026-11-19
sha256 = "{PAYLOAD_SHA}"

[[source.item]]
ref = "Table 1"
content = "CAPEX"
unit = "USD/kW"
currency_year = 2024
price_basis = "real"
tax = "not applicable"
"""


def _source(**changes) -> Source:
    item = SourceItem(ref="Table 1", content="CAPEX", unit="USD/kW", price_basis="real", tax="not applicable")
    base = Source(
        id="demo-source",
        status="pinned",
        citation="Demo (2025)",
        publisher="Demo",
        licence="CC BY 4.0",
        redistribute=True,
        used_by=("boa-cost-data-irena",),
        url="https://example.org/demo.xlsx",
        file="demo.xlsx",
        sha256=PAYLOAD_SHA,
        items=(item,),
    )
    return replace(base, **changes)


def _write_payload(_url: str, target: Path, payload: bytes = PAYLOAD) -> None:
    target.write_bytes(payload)


def _write_registry(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cost_sources.toml"
    path.write_text(text, encoding="utf-8")
    return path


# --- the tracked registry ---------------------------------------------------------------------


def test_tracked_registry_loads_and_every_pinned_source_is_complete():
    registry = load_registry()
    pinned = [s for s in registry.values() if s.pinned]
    assert pinned, "the registry pins no source"
    for source in pinned:
        assert source.url.startswith("https://"), source.id
        assert len(source.sha256) == 64, source.id
        assert source.file and source.accessed, source.id


def test_tracked_registry_covers_every_source_the_irena_build_reads():
    registry = load_registry()
    for source_id, ref in [
        ("irena-rpgc-2024-data", "Table 2.1"),
        ("irena-rpgc-2024-data", "Table 3.1"),
        ("irena-rpgc-2024-data", "Table S.1"),
        ("irena-rpgc-2024-data", "Table A3"),
        ("irena-rpgc-2024-data", "Table A4"),
        ("irena-rpgc-2024-data", "Fig A1"),
        ("iea-weo-2025", "Table A.3a"),
        ("iea-weo-2025", "Table A.3b"),
        ("iea-weo-2025", "Table A.3c"),
        ("iea-batteries-2024", "p. 98"),
    ]:
        assert registry[source_id].label(ref) == f"{source_id}: {ref}"


def test_unknown_source_id_names_the_known_ids():
    with pytest.raises(KeyError, match="known ids: .*irena-rpgc-2024-data"):
        get_source("no-such-source")


def test_unknown_item_ref_is_an_error():
    with pytest.raises(KeyError, match="no item"):
        load_registry()["irena-rpgc-2024-data"].label("Table 99")


# --- schema checks ------------------------------------------------------------------------------


def test_valid_entry_parses(tmp_path):
    source = load_registry(_write_registry(tmp_path, VALID_ENTRY))["demo-source"]
    assert source.pinned and source.items[0].currency_year == 2024


@pytest.mark.parametrize(
    "old, new, message",
    [
        (f'sha256 = "{PAYLOAD_SHA}"\n', "", "missing 'sha256'"),
        (f'sha256 = "{PAYLOAD_SHA}"', 'sha256 = "abc"', "64 lower-case hex"),
        ('url = "https://example.org/demo.xlsx"\n', "", "missing 'url'"),
        ('url = "https://', 'url = "http://', "https://"),
        ("accessed = 2026-11-19\n", "", "'accessed' must be a date"),
        ('price_basis = "real"', 'price_basis = "constant"', "price_basis must be one of"),
        ('tax = "not applicable"', 'tax = "post-tax"', "tax must be one of"),
        ('licence = "CC BY 4.0"\n', "", "missing 'licence'"),
        ("redistribute = true\n", "", "'redistribute' must be true or false"),
        ('used_by = ["boa-cost-data-irena"]', "used_by = []", "'used_by' must be"),
        ('id = "demo-source"', 'id = "Demo Source"', "lower-case words"),
        ('file = "demo.xlsx"', 'file = "sub/demo.xlsx"', "bare file name"),
    ],
)
def test_invalid_entry_is_rejected(tmp_path, old, new, message):
    assert old in VALID_ENTRY
    with pytest.raises(RegistryError, match=message):
        load_registry(_write_registry(tmp_path, VALID_ENTRY.replace(old, new, 1)))


def test_entry_without_items_is_rejected(tmp_path):
    text = VALID_ENTRY.split("[[source.item]]")[0]
    with pytest.raises(RegistryError, match=r"at least one \[\[source.item\]\]"):
        load_registry(_write_registry(tmp_path, text))


def test_duplicate_id_is_rejected(tmp_path):
    with pytest.raises(RegistryError, match="duplicate id"):
        load_registry(_write_registry(tmp_path, VALID_ENTRY + VALID_ENTRY))


def test_unresolved_entry_needs_no_url_but_has_no_sha256(tmp_path):
    text = VALID_ENTRY.replace('status = "pinned"', 'status = "unresolved"')
    for key in ("url", "file", "accessed"):
        text = "\n".join(line for line in text.splitlines() if not line.startswith(f"{key} ="))
    with pytest.raises(RegistryError, match="unresolved source has no sha256"):
        load_registry(_write_registry(tmp_path, text))
    text = "\n".join(line for line in text.splitlines() if not line.startswith("sha256 ="))
    assert not load_registry(_write_registry(tmp_path, text))["demo-source"].pinned


# --- fetch step ---------------------------------------------------------------------------------


def test_fetch_downloads_into_sources_id_folder(tmp_path):
    source = _source()
    assert fetch_sources.fetch_source(source, tmp_path, _write_payload) == "downloaded"
    target = tmp_path / "sources" / "demo-source" / "demo.xlsx"
    assert source_path(tmp_path, source) == target
    assert target.read_bytes() == PAYLOAD


def test_fetch_skips_a_file_already_present_with_the_pinned_sha256(tmp_path):
    source = _source()
    fetch_sources.fetch_source(source, tmp_path, _write_payload)

    def fail(_url, _target):
        raise AssertionError("downloaded again")

    assert fetch_sources.fetch_source(source, tmp_path, fail) == "present"


def test_fetch_replaces_a_present_file_with_a_wrong_sha256(tmp_path):
    source = _source()
    target = source_path(tmp_path, source)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"edited by hand")
    assert fetch_sources.fetch_source(source, tmp_path, _write_payload) == "downloaded"
    assert target.read_bytes() == PAYLOAD


def test_fetch_sha256_mismatch_keeps_the_download_aside_and_fails(tmp_path):
    source = _source(sha256="0" * 64)
    with pytest.raises(ValueError, match="sha256 mismatch"):
        fetch_sources.fetch_source(source, tmp_path, _write_payload)
    folder = tmp_path / "sources" / "demo-source"
    assert not (folder / "demo.xlsx").exists()
    assert (folder / "demo.xlsx.mismatch").read_bytes() == PAYLOAD
    assert not (folder / "demo.xlsx.download").exists()


def test_fetch_failed_download_leaves_no_file(tmp_path):
    def broken(_url, target):
        target.write_bytes(b"part")
        raise OSError("connection reset")

    with pytest.raises(OSError):
        fetch_sources.fetch_source(_source(), tmp_path, broken)
    assert list((tmp_path / "sources" / "demo-source").iterdir()) == []


def test_fetch_skips_unresolved_source(tmp_path):
    source = _source(status="unresolved", url="", file="", sha256="")
    assert fetch_sources.fetch_source(source, tmp_path).startswith("skipped")
    assert not (tmp_path / "sources").exists()


def test_cli_unknown_id_exits_2(tmp_path, capsys):
    assert fetch_sources.main(["no-such-source", "--root", str(tmp_path)]) == 2
    assert "known ids" in capsys.readouterr().err


def test_cli_reports_mismatch_and_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch_sources, "download", lambda url, target: target.write_bytes(b"other"))
    assert fetch_sources.main(["irena-rpgc-2024-data", "--root", str(tmp_path)]) == 1
    assert "sha256 mismatch" in capsys.readouterr().err
