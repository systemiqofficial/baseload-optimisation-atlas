"""
A frontier store records the code version that built it, so one built by older physics is rebuilt.

The region build runs for real on a one-pixel synthetic region under `tmp_path`; only the
weather-year lookup and the land-sea mask read are replaced.
"""

import logging

import numpy as np
import pytest
import xarray as xr
import zarr

from boa.config.paths import PathConfig
from boa.model import frontier_cache, global_extension
from boa.model.bisection import SearchParams

COVERAGE = 0.85
WEATHER_YEAR = 2024
# Older than every real version: they start at 1.
OLD_VERSION = 0


@pytest.fixture
def build_region(tmp_path, monkeypatch, profiles, anchor_costs):
    """Returns a function that runs the region build on a one-pixel region and returns the store path."""
    monkeypatch.setenv("BOA_DATA_ROOT", str(tmp_path))
    path_config = PathConfig.from_root(tmp_path)
    lats, lons = np.array([10.0, 10.25]), np.array([20.0, 20.25])
    monkeypatch.setattr(global_extension, "detect_weather_year", lambda _: WEATHER_YEAR)
    monkeypatch.setattr(
        global_extension, "choose_land_points_in_cutout", lambda *_: (np.array([[10.0, 20.0]]), lats, lons)
    )
    hours = len(profiles["solar"])
    profile = xr.Dataset(
        {
            name: (("time", "y", "x"), np.broadcast_to(profiles[name][:, None, None], (hours, 2, 2)).copy())
            for name in ("solar", "wind")
        },
        coords={"time": np.arange(hours), "y": lats, "x": lons},
    )

    def build():
        return global_extension.build_frontier_cache_for_region(
            region="TESTREGION",
            coverage=COVERAGE,
            profile=profile,
            candidates={(2025, "DEU"): anchor_costs},
            path_config=path_config,
            n_workers=1,
        )

    return build


def _meta(path) -> dict:
    return dict(zarr.open_group(str(path), mode="r").attrs["meta"])


def _set_meta(path, meta: dict) -> None:
    zarr.open_group(str(path), mode="a").attrs["meta"] = meta


def test_build_rebuilds_a_store_with_another_version(build_region, caplog):
    path = build_region()
    meta = _meta(path)
    _set_meta(path, {**meta, "cache_version": OLD_VERSION})

    with caplog.at_level(logging.INFO):
        assert build_region() == path

    assert _meta(path)["built_at"] != meta["built_at"]
    assert frontier_cache.read_frontier_cache_version(path) == frontier_cache.FRONTIER_CACHE_VERSION
    reasons = [m for m in caplog.messages if "rebuilding it" in m]
    assert len(reasons) == 1
    assert f"frontier-cache version {OLD_VERSION}" in reasons[0]


def test_build_reuses_a_current_store(build_region, caplog):
    path = build_region()
    meta = _meta(path)
    assert meta["cache_version"] == frontier_cache.FRONTIER_CACHE_VERSION

    with caplog.at_level(logging.INFO):
        assert build_region() == path

    assert _meta(path)["built_at"] == meta["built_at"]
    assert not [m for m in caplog.messages if "rebuilding it" in m]


def test_a_store_without_the_field_reads_as_version_1_and_is_reused(build_region):
    """Stores built before the field existed stay valid while the version is 1."""
    path = build_region()
    meta = _meta(path)
    del meta["cache_version"]
    _set_meta(path, meta)

    assert frontier_cache.read_frontier_cache_version(path) == 1
    assert build_region() == path
    assert _meta(path)["built_at"] == meta["built_at"]
    frontier_cache.read_frontier_cache(path, SearchParams(), COVERAGE, WEATHER_YEAR)


def test_read_refuses_a_store_with_another_version(build_region):
    """The query path never rebuilds, so it refuses such a store rather than price older physics."""
    path = build_region()
    _set_meta(path, {**_meta(path), "cache_version": OLD_VERSION})

    with pytest.raises(ValueError, match=f"frontier-cache version {OLD_VERSION}"):
        frontier_cache.read_frontier_cache(path, SearchParams(), COVERAGE, WEATHER_YEAR)
