"""The cost source registry and the boa-sources-fetch step."""

import hashlib
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from boa.cli import fetch_sources
from boa.config.cost_sources import RegistryError, Source, get_source, load_registry, source_path

PAYLOAD = b"original file bytes"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()

VALID_ENTRY = f"""
[[source]]
id = "demo-source"
citation = "Demo (2025), A demo source."
url = "https://example.org/files/demo.xlsx"
sha256 = "{PAYLOAD_SHA}"
licence = "CC BY 4.0"
accessed = 2026-11-19
tables = ["Table 1: CAPEX 2024, USD(2024)/kW", "Fig 2: WACC, real"]
"""


def _source(**changes) -> Source:
    base = Source(
        id="demo-source",
        citation="Demo (2025)",
        url="https://example.org/files/demo.xlsx",
        sha256=PAYLOAD_SHA,
        licence="CC BY 4.0",
        accessed=date(2026, 11, 19),
        tables=("Table 1: CAPEX",),
    )
    return replace(base, **changes)


def _write_payload(_url: str, target: Path, payload: bytes = PAYLOAD) -> None:
    target.write_bytes(payload)


def _write_registry(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cost_sources.toml"
    path.write_text(text, encoding="utf-8")
    return path


# --- the tracked registry ---------------------------------------------------------------------


def test_tracked_registry_loads():
    registry = load_registry()
    assert registry
    for source in registry.values():
        assert source.file, source.id


def test_unknown_source_id_names_the_known_ids():
    with pytest.raises(KeyError, match="known ids: .*irena-rpgc-2024-data"):
        get_source("no-such-source")


def test_unknown_table_ref_is_an_error():
    with pytest.raises(KeyError, match="no table"):
        load_registry()["irena-rpgc-2024-data"].label("Table 99")


# --- schema checks ------------------------------------------------------------------------------


def test_valid_entry_parses(tmp_path):
    source = load_registry(_write_registry(tmp_path, VALID_ENTRY))["demo-source"]
    assert source.file == "demo.xlsx"
    assert source.refs == ("Table 1", "Fig 2")
    assert source.label("Fig 2") == "demo-source: Fig 2"


@pytest.mark.parametrize(
    "old, new, message",
    [
        (f'sha256 = "{PAYLOAD_SHA}"\n', "", "missing sha256"),
        (f'sha256 = "{PAYLOAD_SHA}"', 'sha256 = "abc"', "64 lower-case hex"),
        ('url = "https://example.org/files/demo.xlsx"\n', "", "missing url"),
        ('url = "https://', 'url = "http://', "https://"),
        ('url = "https://example.org/files/demo.xlsx"', 'url = "https://example.org/files/"', "file name"),
        ("accessed = 2026-11-19", 'accessed = "yesterday"', "accessed must be a date"),
        ('licence = "CC BY 4.0"\n', "", "missing licence"),
        ('id = "demo-source"', 'id = "Demo Source"', "lower-case words"),
        ('tables = ["Table 1: CAPEX 2024, USD(2024)/kW", "Fig 2: WACC, real"]', "tables = []", "tables must be"),
        ('"Fig 2: WACC, real"', '"Fig 2 WACC"', "tables must be"),
        ('"Fig 2: WACC, real"', '"Table 1: again"', "duplicate table ref"),
        ('licence = "CC BY 4.0"', 'licence = "CC BY 4.0"\nnote = "x"', "unknown key note"),
    ],
)
def test_invalid_entry_is_rejected(tmp_path, old, new, message):
    assert old in VALID_ENTRY
    with pytest.raises(RegistryError, match=message):
        load_registry(_write_registry(tmp_path, VALID_ENTRY.replace(old, new, 1)))


def test_duplicate_id_is_rejected(tmp_path):
    with pytest.raises(RegistryError, match="duplicate id"):
        load_registry(_write_registry(tmp_path, VALID_ENTRY + VALID_ENTRY))


def test_empty_registry_is_rejected(tmp_path):
    with pytest.raises(RegistryError, match="no \\[\\[source\\]\\]"):
        load_registry(_write_registry(tmp_path, "# nothing\n"))


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


def test_cli_unknown_id_exits_2(tmp_path, capsys):
    assert fetch_sources.main(["no-such-source", "--root", str(tmp_path)]) == 2
    assert "known ids" in capsys.readouterr().err


def test_cli_reports_mismatch_and_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch_sources, "download", lambda url, target: target.write_bytes(b"other"))
    assert fetch_sources.main(["irena-rpgc-2024-data", "--root", str(tmp_path)]) == 1
    assert "sha256 mismatch" in capsys.readouterr().err
