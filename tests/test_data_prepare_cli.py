import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from boa.cli import data_prepare
from boa.fetch import fetch_verified_zip

TECHS = ["Solar PV", "Onshore wind", "Battery"]
NE_FOLDERS = ("ne_50m_admin_0_map_subunits", "ne_10m_admin_1_states_provinces")


def _write_workbook(path: Path, europe_solar_capex: float = 700.0, country_code_column: str = "code") -> None:
    """Minimal cost workbook in the canonical layout (sheet and column names as boa reads them)."""
    country = pd.DataFrame(
        {
            "country": ["Germany", "Australia", "France"],
            country_code_column: ["DEU", "AUS", "FRA"],
            "irena region": ["Europe", "Oceania", "Europe"],
        }
    )
    cost_of_capital = pd.DataFrame(
        {
            "country": ["Germany", "Australia", "France"],
            "code": ["DEU", "AUS", "FRA"],
            "tech": ["Renewables"] * 3,
            "cost of capital": [0.05, 0.07, 0.04],
        }
    )
    capex_rows = []
    for region in ("Europe", "Oceania"):
        for tech in TECHS:
            value = europe_solar_capex if (region, tech) == ("Europe", "Solar PV") else 500.0
            capex_rows.append([region, tech, "USD/kW", value, value * 0.9])
    capex = pd.DataFrame(capex_rows, columns=["irena region", "tech", "unit", 2024, 2025])
    opex = pd.DataFrame(
        {
            "region": ["World"] * 3,
            "tech": TECHS,
            "unit": ["% of capex"] * 3,
            "opex": [0.02, 0.03, 0.025],
        }
    )
    with pd.ExcelWriter(path) as writer:
        capex.to_excel(writer, sheet_name="RES CAPEX projections", index=False)
        opex.to_excel(writer, sheet_name="RES OPEX", index=False)
        cost_of_capital.to_excel(writer, sheet_name="Cost of capital", index=False)
        country.to_excel(writer, sheet_name="Country mapping", index=False)


def _core_members(version: str = data_prepare.CORE_DATA_VERSION) -> dict[str, bytes]:
    """A stand-in core data package, marker last as in the real one."""
    members = {}
    for folder in NE_FOLDERS:
        for suffix in (".shp", ".dbf"):
            members[f"{folder}/{folder}{suffix}"] = f"fake-{suffix}".encode()
    members["lsm_025_deg.nc"] = b"fake-nc"
    members[data_prepare.CORE_DATA_MARKER] = json.dumps({"package": "boa-core-data", "version": version}).encode()
    return members


def _zip(path: Path, members: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def boa_root(tmp_path, monkeypatch):
    root = tmp_path / "boa"
    monkeypatch.setenv("BOA_DATA_ROOT", str(root))
    return root


@pytest.fixture(autouse=True)
def core_downloads(monkeypatch):
    """Fake core- and cost-data downloads + stubbed iso3 grid build, so no network or slow sjoin in tests."""
    downloads: list[str] = []

    def fake_fetch(url, sha256, extract_to, on_progress=None):
        downloads.append(url)
        extract_to.mkdir(parents=True, exist_ok=True)
        if url == data_prepare.COST_DATA_URL:
            _write_workbook(extract_to / data_prepare.COST_DATA_WORKBOOK)
            return
        for name, data in _core_members().items():
            (extract_to / name).parent.mkdir(parents=True, exist_ok=True)
            (extract_to / name).write_bytes(data)

    monkeypatch.setattr(data_prepare, "fetch_verified_zip", fake_fetch)

    def fake_build(output_path, *, shapefile_path, resolution=0.25, force=False, on_stage=None):
        assert shapefile_path.exists()
        if on_stage is not None:
            for stage in range(data_prepare.BUILD_STAGE_COUNT):
                on_stage(f"stage {stage}")
        output_path.write_bytes(b"fake-grid")
        return output_path

    monkeypatch.setattr(data_prepare, "build_iso3_grid_from_shapefile", fake_build)
    monkeypatch.setattr(
        data_prepare,
        "iso3_grid_is_current",
        lambda grid_path, shapefile_path: grid_path.exists() and grid_path.read_bytes() == b"fake-grid",
    )
    return downloads


def _run(workbook: Path, scenario: str = "test", *extra: str) -> int:
    return data_prepare.main(["--input-file", str(workbook), "--scenario", scenario, *extra])


def test_copies_workbook_unchanged(tmp_path, boa_root, capsys):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)

    assert _run(workbook) == 0

    assert "Created costs scenario 'test'" in capsys.readouterr().out
    copied = boa_root / "costs" / "test" / "boa_cost_data.xlsx"
    assert copied.read_bytes() == workbook.read_bytes()
    provenance = json.loads((boa_root / "costs" / "test" / "source.json").read_text())
    assert provenance["scenario"] == "test"
    assert provenance["source_workbook"] == str(workbook.resolve())
    assert provenance["source_sha256"] == hashlib.sha256(workbook.read_bytes()).hexdigest()
    assert set(provenance) == {"scenario", "prepared_at", "source_workbook", "source_sha256"}


def test_rerun_with_unchanged_workbook_is_noop_and_keeps_cache(tmp_path, boa_root, capsys):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)
    _run(workbook)

    copied = boa_root / "costs" / "test" / "boa_cost_data.xlsx"
    cache_marker = boa_root / "costs" / "test" / "cache_costs" / "marker.nc"
    cache_marker.touch()
    mtime = copied.stat().st_mtime_ns
    capsys.readouterr()

    assert _run(workbook) == 0

    assert "already up to date" in capsys.readouterr().out
    assert copied.stat().st_mtime_ns == mtime
    assert cache_marker.exists()


def test_changed_workbook_replaces_copy_and_rebuilds_cache(tmp_path, boa_root, capsys):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)
    _run(workbook)

    cache_dir = boa_root / "costs" / "test" / "cache_costs"
    stale_marker = cache_dir / "marker.nc"
    stale_marker.touch()
    _write_workbook(workbook, europe_solar_capex=350.0)
    capsys.readouterr()

    assert _run(workbook) == 0

    assert "Updated costs scenario 'test'" in capsys.readouterr().out
    assert not stale_marker.exists()  # stale cache cleared before the rebuild
    assert sorted(p.name for p in cache_dir.iterdir()) == [
        "cost_of_renewables_2024_investment_year.nc",
        "cost_of_renewables_2025_investment_year.nc",
    ]
    assert (boa_root / "costs" / "test" / "boa_cost_data.xlsx").read_bytes() == workbook.read_bytes()


def test_builds_cost_cache_for_all_sheet_years(tmp_path, boa_root):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)

    assert _run(workbook) == 0

    cache_dir = boa_root / "costs" / "test" / "cache_costs"
    assert sorted(p.name for p in cache_dir.iterdir()) == [
        "cost_of_renewables_2024_investment_year.nc",
        "cost_of_renewables_2025_investment_year.nc",
    ]


def test_year_flags_narrow_cache(tmp_path, boa_root):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)

    assert _run(workbook, "test", "--year_start", "2025") == 0

    cache_dir = boa_root / "costs" / "test" / "cache_costs"
    assert sorted(p.name for p in cache_dir.iterdir()) == ["cost_of_renewables_2025_investment_year.nc"]


def test_core_data_installed_and_grid_built(tmp_path, boa_root, core_downloads):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)

    _run(workbook)

    assert core_downloads == [data_prepare.CORE_DATA_URL]
    data_dir = boa_root / "data"
    assert (data_dir / "ne_50m_admin_0_map_subunits" / "ne_50m_admin_0_map_subunits.shp").exists()
    assert (data_dir / "ne_10m_admin_1_states_provinces" / "ne_10m_admin_1_states_provinces.shp").exists()
    assert (data_dir / "lsm_025_deg.nc").exists()
    assert (data_dir / "iso3_grid.nc").read_bytes() == b"fake-grid"


def test_core_data_skips_download_and_build_when_current(tmp_path, boa_root, core_downloads):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)
    _run(workbook)
    core_downloads.clear()
    grid = boa_root / "data" / "iso3_grid.nc"
    grid_mtime = grid.stat().st_mtime_ns

    _run(workbook)

    assert core_downloads == []
    assert grid.stat().st_mtime_ns == grid_mtime


@pytest.mark.parametrize("marker", [json.dumps({"version": "0.0"}), "not json"])
def test_core_data_refetched_unless_pinned_version_installed(tmp_path, boa_root, core_downloads, marker):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)
    _run(workbook)
    core_downloads.clear()
    (boa_root / "data" / data_prepare.CORE_DATA_MARKER).write_text(marker)

    _run(workbook)

    assert core_downloads == [data_prepare.CORE_DATA_URL]


def test_core_data_installs_from_pinned_zip(tmp_path, boa_root, monkeypatch):
    """The real download path: fetch_verified_zip checks the pinned sha256 and unzips into data/."""
    package = tmp_path / "boa-core-data.zip"
    sha256 = _zip(package, _core_members())
    monkeypatch.setattr(data_prepare, "fetch_verified_zip", fetch_verified_zip)
    monkeypatch.setattr(data_prepare, "CORE_DATA_URL", package.as_uri())
    monkeypatch.setattr(data_prepare, "CORE_DATA_SHA256", sha256)
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)

    assert _run(workbook) == 0

    data_dir = boa_root / "data"
    assert (
        json.loads((data_dir / data_prepare.CORE_DATA_MARKER).read_text())["version"] == data_prepare.CORE_DATA_VERSION
    )
    assert (data_dir / "lsm_025_deg.nc").read_bytes() == b"fake-nc"
    assert not list(data_dir.glob("*.part"))


def test_stale_iso3_grid_is_rebuilt(tmp_path, boa_root):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)
    _run(workbook)
    grid = boa_root / "data" / "iso3_grid.nc"
    grid.write_bytes(b"grid-from-old-ne-shapefile")

    _run(workbook)

    assert grid.read_bytes() == b"fake-grid"


def test_missing_sheet_fails(tmp_path, boa_root, capsys):
    workbook = tmp_path / "boa-cost-data.xlsx"
    pd.DataFrame({"code": ["DEU"]}).to_excel(workbook, sheet_name="Country mapping", index=False)

    assert data_prepare.main(["--input-file", str(workbook)]) == 1
    assert "missing sheet 'RES OPEX'" in " ".join(capsys.readouterr().out.split())


def test_missing_column_fails_and_keeps_previous_copy(tmp_path, boa_root, capsys):
    workbook = tmp_path / "boa-cost-data.xlsx"
    _write_workbook(workbook)
    _run(workbook)
    copied = boa_root / "costs" / "test" / "boa_cost_data.xlsx"
    previous = copied.read_bytes()
    _write_workbook(workbook, country_code_column="Code")
    capsys.readouterr()

    assert _run(workbook) == 1

    out = " ".join(capsys.readouterr().out.split())
    assert "sheet 'Country mapping' is missing column(s) ['code']" in out
    assert copied.read_bytes() == previous


def test_without_input_file_records_the_pinned_cost_package(boa_root, core_downloads):
    assert data_prepare.main(["--scenario", "test"]) == 0

    assert data_prepare.COST_DATA_URL in core_downloads
    assert (boa_root / "costs" / "test" / "boa_cost_data.xlsx").exists()
    provenance = json.loads((boa_root / "costs" / "test" / "source.json").read_text())
    assert provenance["source_workbook"] == data_prepare.COST_DATA_WORKBOOK
    assert provenance["source_package"] == {
        "version": data_prepare.COST_DATA_VERSION,
        "url": data_prepare.COST_DATA_URL,
        "sha256": data_prepare.COST_DATA_SHA256,
    }


def test_without_input_file_installs_the_pinned_cost_package(tmp_path, boa_root, monkeypatch):
    """The real download path: the pinned zip is checked, unpacked and its workbook copied unchanged."""
    workbook = tmp_path / "package-src" / data_prepare.COST_DATA_WORKBOOK
    workbook.parent.mkdir()
    _write_workbook(workbook)
    cost_zip, core_zip = tmp_path / "boa-cost-data.zip", tmp_path / "boa-core-data.zip"
    cost_sha = _zip(cost_zip, {workbook.name: workbook.read_bytes(), "boa-cost-data.json": b"{}"})
    core_sha = _zip(core_zip, _core_members())
    monkeypatch.setattr(data_prepare, "fetch_verified_zip", fetch_verified_zip)
    monkeypatch.setattr(data_prepare, "COST_DATA_URL", cost_zip.as_uri())
    monkeypatch.setattr(data_prepare, "COST_DATA_SHA256", cost_sha)
    monkeypatch.setattr(data_prepare, "CORE_DATA_URL", core_zip.as_uri())
    monkeypatch.setattr(data_prepare, "CORE_DATA_SHA256", core_sha)

    assert data_prepare.main(["--scenario", "test"]) == 0

    assert (boa_root / "costs" / "test" / "boa_cost_data.xlsx").read_bytes() == workbook.read_bytes()
