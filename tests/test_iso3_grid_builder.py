import xarray as xr

from boa.geo import iso3_grid_builder
from boa.geo.iso3_grid_builder import iso3_grid_fingerprint, iso3_grid_is_current


def _write_shapefile_pair(directory, shp=b"shp-bytes", dbf=b"dbf-bytes"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "subunits.shp"
    path.write_bytes(shp)
    path.with_suffix(".dbf").write_bytes(dbf)
    return path


def _write_grid(path, attrs):
    xr.Dataset(attrs=attrs).to_netcdf(path)


def test_fingerprint_covers_geometry_and_attribute_table(tmp_path):
    shapefile = _write_shapefile_pair(tmp_path / "a")
    same = _write_shapefile_pair(tmp_path / "b")
    different_dbf = _write_shapefile_pair(tmp_path / "c", dbf=b"other-attributes")

    assert iso3_grid_fingerprint(shapefile) == iso3_grid_fingerprint(same)
    assert iso3_grid_fingerprint(shapefile) != iso3_grid_fingerprint(different_dbf)


def test_fingerprint_covers_the_iso3_remap(tmp_path, monkeypatch):
    shapefile = _write_shapefile_pair(tmp_path / "ne")
    grid = tmp_path / "iso3_grid.nc"
    _write_grid(grid, {"source_sha256": iso3_grid_fingerprint(shapefile)})

    monkeypatch.setitem(iso3_grid_builder.NE_TO_BOA, "CYN", "XCY")

    assert not iso3_grid_is_current(grid, shapefile)


def test_grid_is_current_only_on_matching_fingerprint(tmp_path):
    shapefile = _write_shapefile_pair(tmp_path / "ne")
    grid = tmp_path / "iso3_grid.nc"

    assert not iso3_grid_is_current(grid, shapefile)  # missing grid

    _write_grid(grid, {"source_sha256": iso3_grid_fingerprint(shapefile)})
    assert iso3_grid_is_current(grid, shapefile)

    _write_grid(grid, {"source_sha256": "0" * 64})
    assert not iso3_grid_is_current(grid, shapefile)  # built from another shapefile

    _write_grid(grid, {})
    assert not iso3_grid_is_current(grid, shapefile)  # pre-fingerprint grid counts as stale

    grid.write_bytes(b"not-a-netcdf")
    assert not iso3_grid_is_current(grid, shapefile)  # unreadable counts as stale
