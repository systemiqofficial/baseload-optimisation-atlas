"""
How the query uses a frontier store: which stores it refuses, and when it re-derives its outputs.

- **Coverage.** A store is dense only near its anchors, so pricing costs far from all of them
  can return an LCOE well above the optimum with nothing in the output to show it. The build
  rebuilds such a store; the query never builds, so it must stop instead, on exactly the same
  rule (`anchors_for_build`).
- **Staleness.** A rebuilt store can give other designs. Every output records the `built_at` of
  the store it was priced from, so the query, the GLOBAL combine and promotion can tell an old
  file from a current one.

The region build runs for real on a one-pixel synthetic region; only the weather-year lookup,
the land-sea mask read and the cost-key lookup are replaced. The default store is built once per
module, and each test gets a copy under `tmp_path`.
"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import zarr

from boa.config.paths import PathConfig
from boa.model import global_extension
from boa.model.bisection import CostCoefficients, SearchParams
from boa.model.global_extension import FrontierCacheCoverageError, check_frontier_caches_cover

COVERAGE = 0.85
WEATHER_YEAR = 2024
REGION = "TESTREGION"
HORIZON = 25
LOAD_DENSITY = 1.0


@pytest.fixture(scope="module")
def default_store(tmp_path_factory, profiles, anchor_costs):
    """One real build with the default `SearchParams`: (store path, cache directory it sits in)."""
    root = tmp_path_factory.mktemp("default_store")
    with pytest.MonkeyPatch.context() as mp:
        build, path_config = _stage(root, mp, profiles, anchor_costs)
        store = build()
    return store, path_config.frontier_cache_dir(WEATHER_YEAR)


@pytest.fixture
def staged(tmp_path, monkeypatch, profiles, anchor_costs, default_store):
    """
    Returns (build, path_config). `build()` copies the module's default store into `tmp_path`;
    `build(params)` builds a store for those params for real.
    """
    real_build, path_config = _stage(tmp_path, monkeypatch, profiles, anchor_costs)
    store, store_dir = default_store

    def build(params: SearchParams | None = None) -> Path:
        if params is not None:
            return real_build(params)
        target = path_config.frontier_cache_dir(WEATHER_YEAR) / store.relative_to(store_dir)
        shutil.copytree(store, target)
        return target

    return build, path_config


def _rebuild(store: Path) -> None:
    """Stand in for a rebuild: move the store's `built_at` on, which is all the query compares."""
    group = zarr.open_group(str(store), mode="a")
    meta = group.attrs["meta"]
    assert isinstance(meta, dict)
    later = datetime.fromisoformat(str(meta["built_at"])) + timedelta(seconds=1)
    group.attrs["meta"] = {**meta, "built_at": later.isoformat()}


def _stage(root: Path, monkeypatch, profiles, anchor_costs):
    """Point BOA at `root` with the one-pixel region; returns (build, path_config)."""
    monkeypatch.setenv("BOA_DATA_ROOT", str(root))
    path_config = PathConfig.from_root(root)
    lats, lons = np.array([10.0, 10.25]), np.array([20.0, 20.25])
    monkeypatch.setattr(global_extension, "detect_weather_year", lambda _: WEATHER_YEAR)
    monkeypatch.setattr(
        global_extension, "choose_land_points_in_cutout", lambda *_: (np.array([[10.0, 20.0]]), lats, lons)
    )
    monkeypatch.setattr(global_extension, "REGION_COORDS", {REGION: None})
    capex = {t: np.full((1, HORIZON + 1), v) for t, v in (("solar", 9e5), ("wind", 1.4e6), ("battery", 3e5))}
    opex = {t: np.full(1, v) for t, v in (("solar", 0.01), ("wind", 0.02), ("battery", 0.02))}
    monkeypatch.setattr(
        global_extension, "_derive_cost_arrays", lambda *_: (np.array(["DEU"]), capex, opex, np.full(1, 0.08))
    )
    hours = len(profiles["solar"])
    profile = xr.Dataset(
        {
            name: (("time", "y", "x"), np.broadcast_to(profiles[name][:, None, None], (hours, 2, 2)).copy())
            for name in ("solar", "wind")
        },
        coords={"time": np.arange(hours), "y": lats, "x": lons},
    )

    def build(params: SearchParams | None = None) -> Path:
        return global_extension.build_frontier_cache_for_region(
            region=REGION,
            coverage=COVERAGE,
            profile=profile,
            candidates={(2025, "DEU"): anchor_costs},
            path_config=path_config,
            n_workers=1,
            params=params,
        )

    return build, path_config


def _far(c: CostCoefficients) -> CostCoefficients:
    """A mix far from `c` on the cost simplex: solar four times dearer, wind at 40 %."""
    return CostCoefficients(a_s=c.a_s * 4.0, a_w=c.a_w * 0.4, a_b=c.a_b, d0=c.d0)


def test_a_store_that_covers_the_query_passes(staged, anchor_costs):
    build, path_config = staged
    build()
    check_frontier_caches_cover([REGION], COVERAGE, {(2030, "FRA"): anchor_costs}, path_config)


def test_a_store_that_does_not_cover_the_query_is_refused(staged, anchor_costs):
    build, path_config = staged
    build()
    candidates = {(2025, "DEU"): anchor_costs, (2025, "FRA"): _far(anchor_costs)}

    with pytest.raises(FrontierCacheCoverageError, match=r"(?s)TESTREGION: 1 of 2 .*boa-run build-cache"):
        check_frontier_caches_cover([REGION], COVERAGE, candidates, path_config)


def test_a_missing_store_is_refused(staged, anchor_costs):
    _, path_config = staged
    with pytest.raises(FrontierCacheCoverageError, match="TESTREGION: no frontier cache"):
        check_frontier_caches_cover([REGION], COVERAGE, {(2025, "DEU"): anchor_costs}, path_config)


def test_a_store_with_another_version_is_refused(staged, anchor_costs):
    build, path_config = staged
    path = build()
    group = zarr.open_group(str(path), mode="a")
    group.attrs["meta"] = {**dict(group.attrs["meta"]), "cache_version": 0}

    with pytest.raises(FrontierCacheCoverageError, match="another frontier-cache version"):
        check_frontier_caches_cover([REGION], COVERAGE, {(2025, "DEU"): anchor_costs}, path_config)


def test_a_store_at_the_anchor_cap_passes_as_the_build_reuses_it(staged, anchor_costs):
    """The build can add no anchor to such a store, so refusing it would leave no way forward."""
    build, path_config = staged
    params = SearchParams(max_anchors=1)
    build(params)
    candidates = {(2025, "DEU"): anchor_costs, (2025, "FRA"): _far(anchor_costs)}

    check_frontier_caches_cover([REGION], COVERAGE, candidates, path_config, params)


# --------------------------------------------------------------------------
# Outputs priced from an earlier build of the store
# --------------------------------------------------------------------------


def _query(path_config, year: int = 2025):
    return global_extension.query_frontier_cache_for_region(
        year=year,
        region=REGION,
        load_density=LOAD_DENSITY,
        coverage=COVERAGE,
        costs=None,
        investment_horizon=HORIZON,
        path_config=path_config,
        n_workers=1,
    )


def _combine(path_config, year: int = 2025):
    return global_extension.combine_regional_datasets_into_global_dataset(
        year, COVERAGE, LOAD_DENSITY, path_config, WEATHER_YEAR
    )


def _attr(path, name: str):
    with xr.open_dataset(path) as ds:
        return ds.attrs.get(name)


def _close(ds) -> None:
    """The query and the combine return an open dataset; Windows can't overwrite an open file."""
    if ds is not None:
        ds.close()


def test_a_regional_file_records_the_build_it_was_priced_from(staged):
    from boa.model.frontier_cache import read_frontier_built_at

    build, path_config = staged
    store = build()
    _close(_query(path_config))
    out = path_config.optimal_sol_path(WEATHER_YEAR, LOAD_DENSITY, COVERAGE, REGION, 2025)

    assert _attr(out, "frontier_cache_built_at") == read_frontier_built_at(store)


def test_a_regional_file_is_reused_while_the_store_is_unchanged(staged):
    build, path_config = staged
    build()
    _close(_query(path_config))
    out = path_config.optimal_sol_path(WEATHER_YEAR, LOAD_DENSITY, COVERAGE, REGION, 2025)
    created = _attr(out, "created_at")

    _close(_query(path_config))

    assert _attr(out, "created_at") == created


def test_a_regional_file_is_re_derived_after_the_store_is_rebuilt(staged):
    """Without this, a re-run after a rebuild keeps the old LCOE beside new years, and nothing shows it."""
    from boa.model.frontier_cache import read_frontier_built_at

    build, path_config = staged
    store = build()
    _close(_query(path_config))
    out = path_config.optimal_sol_path(WEATHER_YEAR, LOAD_DENSITY, COVERAGE, REGION, 2025)
    created = _attr(out, "created_at")

    _rebuild(store)
    _close(_query(path_config))

    assert _attr(out, "created_at") != created
    assert _attr(out, "frontier_cache_built_at") == read_frontier_built_at(store)


def test_the_global_file_is_combined_again_after_a_region_is_re_derived(staged):
    build, path_config = staged
    store = build()
    _close(_query(path_config))
    _close(_combine(path_config))
    out = path_config.optimal_sol_path(WEATHER_YEAR, LOAD_DENSITY, COVERAGE, "GLOBAL", 2025)
    created = _attr(out, "created_at")

    _close(_combine(path_config))
    assert _attr(out, "created_at") == created, "an unchanged region must not force a new combine"

    _rebuild(store)
    _close(_query(path_config))
    _close(_combine(path_config))
    assert _attr(out, "created_at") != created
    regional = path_config.optimal_sol_path(WEATHER_YEAR, LOAD_DENSITY, COVERAGE, REGION, 2025)
    assert _attr(out, "frontier_cache_built_at") == f"{REGION}={_attr(regional, 'frontier_cache_built_at')}"


# --------------------------------------------------------------------------
# The CLI stops before the first file
# --------------------------------------------------------------------------


def test_query_all_years_stops_before_it_queries_any_year(staged, anchor_costs, monkeypatch):
    """A check inside the year loop would write the first year and then stop; this one writes nothing."""
    from boa.cli import run_simulation

    build, path_config = staged
    build()
    monkeypatch.setattr(run_simulation, "REGION_COORDS", {REGION: None})
    monkeypatch.setattr(run_simulation, "_validate_cost_set", lambda *_: (None, HORIZON))
    candidates = {(2025, "DEU"): anchor_costs, (2030, "DEU"): _far(anchor_costs)}
    monkeypatch.setattr(run_simulation, "cost_candidates", lambda *_: candidates)
    queried: list[int] = []
    monkeypatch.setattr(run_simulation, "query_frontier_cache_for_region", lambda **kw: queried.append(kw["year"]))

    with pytest.raises(FrontierCacheCoverageError):
        run_simulation.query_all_years(
            path_config, [2025, 2030], LOAD_DENSITY, COVERAGE, 1, WEATHER_YEAR, generate_plots=False
        )
    assert queried == []


def test_boa_run_query_exits_1_when_the_caches_do_not_cover_the_run(tmp_path, monkeypatch):
    from boa.cli import run_simulation

    def refuse(*_args, **_kwargs):
        raise FrontierCacheCoverageError("TESTREGION: no frontier cache")

    monkeypatch.setenv("BOA_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(run_simulation, "preflight", lambda *_args, **_kwargs: WEATHER_YEAR)
    monkeypatch.setattr(run_simulation.run_manifest, "record_invocation", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(run_simulation, "query_all_years", refuse)

    assert run_simulation.main_query(["--load-density", str(LOAD_DENSITY), "--coverage", str(COVERAGE)]) == 1
