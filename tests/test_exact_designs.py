"""
Exact designs: a frontier whose stored designs are the ones the search dispatched.

The store keeps a design's solar, wind and battery sizes as float32, while the search works in
float64. Without `exact`, rounding a design to float32 can cost it the last hour it needed, so
a stored design can miss the coverage target its own stored fractions say it meets. With
`exact`, the patch search dispatches only float32 sizes, and every stored design meets the
target with fractions that are its own until a region store quantises them to 16 bits.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from functools import partial

import numpy as np
import pytest
import xarray as xr

from boa.cli.run_simulation import _validate_cost_set
from boa.config.paths import PathConfig
from boa.config.physical_parameters import ERA5_DATA_RESOLUTION
from boa.inputs.profiles import open_regional_dataset
from boa.model import global_extension, single_point_run
from boa.model.anchors import cost_candidates
from boa.model.bisection import STATUS_OK, SearchParams, b_min_at, build_pixel_frontier, dispatch_metrics
from boa.model.frontier_cache import (
    build_frontier_meta,
    frontier_at,
    frontier_cache_path,
    read_frontier_anchors,
    read_frontier_cache,
    stack_pixel_frontiers,
    write_frontier_cache,
)
from boa.model.global_extension import (
    build_frontier_cache_for_region,
    combine_regional_datasets_into_global_dataset,
    query_frontier_cache_for_region,
)
from boa.model.single_point_run import execute_single_point_baseload_power_simulation
from boa.store_schema import profile_store_stem

SIZES = ("s_patch", "w_patch", "b_patch")


def _designs(frontier, profiles) -> Iterator[tuple[tuple[float, float], tuple[float, float]]]:
    """Each stored design's `(hours, energy)` as stored, and as replayed hour by hour from its stored sizes."""
    for slot in range(frontier.n_patches):
        n_s, n_w = (int(x) for x in frontier.patch_points[slot])
        for a in range(n_s):
            for b in range(n_w):
                for r in range(frontier.b_patch.shape[-1]):
                    battery = float(frontier.b_patch[slot, a, b, r])
                    if not (np.isfinite(battery) and frontier.energy_served_frac[slot, a, b, r] > 0):
                        continue
                    stored = (
                        float(frontier.hours_covered_frac[slot, a, b, r]),
                        float(frontier.energy_served_frac[slot, a, b, r]),
                    )
                    replayed = dispatch_metrics(
                        profiles["solar"],
                        profiles["wind"],
                        float(frontier.s_patch[slot, a]),
                        float(frontier.w_patch[slot, b]),
                        battery,
                    )
                    yield stored, replayed


def test_without_exact_designs_the_store_rounds_a_design_below_its_target(rounding_profiles, anchor_costs):
    """The defect: a stored design misses the target its own stored hours claim to meet."""
    frontier = build_pixel_frontier(
        rounding_profiles["solar"], rounding_profiles["wind"], 0.9, SearchParams(), anchor_costs
    )
    short = [stored for stored, (hours, _) in _designs(frontier, rounding_profiles) if hours < 0.9]
    assert short, "the rounding case moved; search the wind seeds again for `rounding_profiles`"
    assert all(hours >= 0.9 for hours, _ in short)


@pytest.mark.parametrize("coverage", [0.85, 0.9])
@pytest.mark.parametrize("params", [SearchParams(), SearchParams(ladder_rungs=6, ladder_max_span=3.0)])
def test_with_exact_designs_every_stored_design_meets_its_target_with_its_own_metrics(
    rounding_profiles, anchor_costs, coverage, params
):
    frontier = build_pixel_frontier(
        rounding_profiles["solar"], rounding_profiles["wind"], coverage, params, anchor_costs, exact=True
    )
    designs = list(_designs(frontier, rounding_profiles))
    assert designs
    for stored, replayed in designs:
        assert replayed == stored
        assert replayed[0] >= coverage


def _windless_days() -> tuple[np.ndarray, np.ndarray]:
    """Three weeks of daily sun and steady wind, with five windless days that make the battery large."""
    hours = np.arange(24 * 21)
    solar = np.clip(0.55 * np.sin((hours % 24 - 6) * np.pi / 12), 0.0, None)
    wind = np.where((hours >= 216) & (hours < 336), 0.0, 0.6)
    return solar, wind


def test_exact_designs_stop_once_float32_cannot_split_the_battery_bracket():
    """
    With no relative tolerance the bracket closes towards the 1e-6 floor, finer than float32's
    step above a battery of 16 hours, so the float32 midpoint lands on an end and the search must
    stop rather than loop.
    """
    solar, wind = _windless_days()
    params = SearchParams(tol_rel_patch=0.0)
    battery, covered, _ = b_min_at(solar, wind, 4.0, 2.0, 0.97, params, exact=True)
    assert 16.0 < battery < np.inf, "the case needs a battery whose float32 step exceeds 1e-6"
    assert battery == float(np.float32(battery))
    assert covered >= 0.97


def test_exact_designs_round_a_hint_that_is_not_a_float32_value():
    """The build's own hints are float32 values already, but a caller's hint need not be."""
    solar, wind = _windless_days()
    battery, _, _ = b_min_at(solar, wind, 4.0, 2.0, 0.97, SearchParams(), exact=True)
    hint = battery * 1.001
    assert hint != float(np.float32(hint))
    hinted, covered, _ = b_min_at(solar, wind, 4.0, 2.0, 0.97, SearchParams(), hint=hint, exact=True)
    assert hinted == float(np.float32(hinted))
    assert covered >= 0.97


# Compiles in a fresh numba cache, since numba refuses to inspect code it loaded from one.
PRUNING_CHECK = """
import json
import numpy as np
from boa.model.bisection import SearchParams, _b_min_jit, _rung_metrics_jit, b_min_at, battery_rungs

hours = np.arange(24 * 21)
solar = np.clip(0.55 * np.sin((hours % 24 - 6) * np.pi / 12), 0.0, None)
wind = np.full(hours.shape, 0.3)
params = SearchParams(ladder_rungs=3, ladder_max_span=1.5)
for exact in (False, True):
    b, cov, sf = b_min_at(solar, wind, 3.0, 2.0, 0.85, params, exact=exact)
    battery_rungs(solar, wind, 3.0, 2.0, b, cov, sf, params, exact=exact)
counts = {
    f.__name__: {
        str(sig[f.py_func.__code__.co_varnames.index("exact")]): f.inspect_llvm(sig).count("fptrunc double")
        for sig in f.signatures
    }
    for f in (_b_min_jit, _rung_metrics_jit)
}
print(json.dumps(counts))
"""


def test_numba_compiles_the_rounding_out_of_the_default_path(tmp_path):
    """
    BOA's defaults pass `None`, and numba resolves `exact is None` when it compiles, so the
    default path holds no float32 conversion. A numba release that stopped pruning the branch
    would slow every default build, and this fails first.
    """
    result = subprocess.run(
        [sys.executable, "-c", PRUNING_CHECK],
        env={**os.environ, "NUMBA_CACHE_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    counts = json.loads(result.stdout.strip().splitlines()[-1])
    for name, by_type in counts.items():
        assert by_type["none"] == 0, name
        assert by_type["bool"] > 0, name


# --------------------------------------------------------------------------
# The query and the GLOBAL combine, on hand-made stores and outputs
# --------------------------------------------------------------------------


def _bare_config(tmp_path) -> PathConfig:
    """A data root whose only content is an empty 2024 profile store, which is all the query reads before its store."""
    config = PathConfig.from_root(tmp_path, input_set="cds-2024", cost_set="default", run="r")
    (config.zarr_dir / (profile_store_stem("EUROPE", 2024) + ".zarr")).mkdir(parents=True)
    return config


def test_a_query_with_exact_designs_refuses_a_default_store_under_the_exact_name(tmp_path, profiles, anchor_costs):
    config = _bare_config(tmp_path)
    frontier = build_pixel_frontier(profiles["solar"], profiles["wind"], 0.95, SearchParams(), anchor_costs)
    point = np.zeros(1, dtype=np.int32)
    cache = stack_pixel_frontiers(
        [frontier],
        region="EUROPE",
        all_lats=np.array([40.0], dtype=np.float32),
        all_lons=np.array([-3.0], dtype=np.float32),
        lats=np.array([40.0], dtype=np.float32),
        lons=np.array([-3.0], dtype=np.float32),
        iy=point,
        ix=point,
        meta=build_frontier_meta("EUROPE", 1, 0.95, SearchParams(), 2024, ERA5_DATA_RESOLUTION, [anchor_costs]),
    )
    cache_dir = config.frontier_cache_dir(2024)
    write_frontier_cache(
        cache, frontier_cache_path(cache_dir, "EUROPE", 0.95, SearchParams(), 2024, ERA5_DATA_RESOLUTION, exact=True)
    )
    with pytest.raises(ValueError, match="without exact designs"):
        query_frontier_cache_for_region(2025, "EUROPE", 1.0, 0.95, None, 25, config, n_workers=1, exact=True)


@pytest.mark.parametrize("written_exact", [False, True])
def test_a_query_refuses_an_existing_output_written_the_other_way(tmp_path, written_exact):
    config = _bare_config(tmp_path)
    output = config.optimal_sol_path(2024, 1.0, 0.95, "EUROPE", 2025)
    output.parent.mkdir(parents=True)
    xr.Dataset(attrs={"exact_designs": 1} if written_exact else {}).to_netcdf(output)
    query = partial(query_frontier_cache_for_region, 2025, "EUROPE", 1.0, 0.95, None, 25, config, 1)

    with pytest.raises(ValueError, match=f"exists {'with' if written_exact else 'without'} exact designs"):
        query(exact=not written_exact)
    with query(exact=written_exact) as existing:
        assert existing.attrs.get("exact_designs", 0) == int(written_exact)


def test_the_global_combine_refuses_regions_that_disagree_on_exact_designs(tmp_path, monkeypatch):
    monkeypatch.setattr(global_extension, "REGION_COORDS", dict.fromkeys(("NORTH", "SOUTH")))
    config = PathConfig.from_root(tmp_path, run="r")

    def write(n: int, region: str, exact: bool) -> None:
        output = config.optimal_sol_path(2024, 1.0, 0.95, region, 2025)
        output.parent.mkdir(parents=True, exist_ok=True)
        xr.Dataset(
            {"lcoe": (("lat", "lon"), np.full((2, 2), 50.0))},
            coords={"lat": [10.0 + n, 10.25 + n], "lon": [20.0, 20.25]},
            attrs={"search_params_hash": "a7d2c707", "region": region, **({"exact_designs": 1} if exact else {})},
        ).to_netcdf(output)

    write(0, "NORTH", exact=True)
    write(1, "SOUTH", exact=False)
    with pytest.raises(ValueError, match=r"only \['NORTH'\] were queried with exact designs"):
        combine_regional_datasets_into_global_dataset(2025, 0.95, 1.0, config, 2024)

    write(1, "SOUTH", exact=True)
    assert combine_regional_datasets_into_global_dataset(2025, 0.95, 1.0, config, 2024).attrs["exact_designs"] == 1


# --------------------------------------------------------------------------
# The region build, its query and point mode, on the weather extract
# --------------------------------------------------------------------------


def test_exact_designs_reach_the_region_build_and_its_query(extract_data_root):
    candidates = cost_candidates((2025,), lambda year: _validate_cost_set(extract_data_root, year))
    profile = open_regional_dataset("profile", "EUROPE", extract_data_root)
    store = build_frontier_cache_for_region("EUROPE", 0.95, profile, candidates, extract_data_root, n_workers=1, exact=True)
    assert store.name.endswith("_exact.zarr")

    cache = read_frontier_cache(store, SearchParams(), 0.95, 2024, exact=True)
    assert cache.meta["run_params"]["exact"] is True
    anchors = read_frontier_anchors(store)
    default_differs = []
    for k in np.flatnonzero(cache.status == STATUS_OK):
        cell = profile.sel(x=float(cache.lons[k]), y=float(cache.lats[k]), method="nearest")
        weather = {
            name: np.ascontiguousarray(cell[name].values.flatten(), dtype=np.float64) for name in ("solar", "wind")
        }
        stored = frontier_at(cache, int(k))
        for _, (hours, _) in _designs(stored, weather):
            assert hours >= 0.95
        # The store holds what an exact build of the cell holds, which a default build does not.
        exact = build_pixel_frontier(weather["solar"], weather["wind"], 0.95, SearchParams(), anchors, exact=True)
        for name in SIZES:
            np.testing.assert_array_equal(getattr(stored, name), getattr(exact, name), err_msg=name)
        default = build_pixel_frontier(weather["solar"], weather["wind"], 0.95, SearchParams(), anchors)
        default_differs.append(any(not np.array_equal(getattr(default, n), getattr(exact, n)) for n in SIZES))
    assert any(default_differs), "no cell's default build differs from its exact one, so the comparison cannot fail"

    costs, horizon = _validate_cost_set(extract_data_root, 2025)
    solution = query_frontier_cache_for_region(
        2025, "EUROPE", 1.0, 0.95, costs, horizon, extract_data_root, n_workers=1, exact=True
    )
    assert solution.attrs["exact_designs"] == 1
    # A default query neither returns this output nor falls back on the exact store.
    with pytest.raises(ValueError, match="exists with exact designs"):
        query_frontier_cache_for_region(2025, "EUROPE", 1.0, 0.95, costs, horizon, extract_data_root, 1)
    with pytest.raises(FileNotFoundError):
        query_frontier_cache_for_region(2025, "EUROPE", 1.0, 0.95, costs, horizon, extract_data_root, 1, force=True)


def test_exact_designs_reach_point_mode(extract_data_root, monkeypatch):
    build, seen = single_point_run.build_pixel_frontier, []

    def recording(*args, **kwargs):
        seen.append(kwargs.get("exact"))
        return build(*args, **kwargs)

    monkeypatch.setattr(single_point_run, "build_pixel_frontier", recording)
    execute_single_point_baseload_power_simulation(
        extract_data_root, 2025, 39.5, -3.0, 1.0, 0.95, generate_plots=False, exact=True
    )
    assert seen == [True]
