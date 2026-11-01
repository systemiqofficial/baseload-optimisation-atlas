"""
A minimum load in the dispatch kernel: a process that runs whenever solar, wind and the battery
reach its minimum load, and stops below it, storing the hour's generation.

`min_load` is `None` by default, and numba resolves that branch when it compiles, so BOA's
flat demand keeps its arithmetic. These tests check the minimum-load kernel against its
readable reference, that the default path compiles without it, the battery search and the
coarse tier under it, and that the kernel dispatched every design the build stores under it
and found it to meet its target. A sweep looks for a fall in hours run as the battery grows.
The last tests follow the minimum load through the query, the GLOBAL combine, the region
build, the plots and point mode.
"""

import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from boa.cli.run_simulation import _validate_cost_set
from boa.config.paths import PathConfig
from boa.inputs.profiles import open_regional_dataset
from boa.model import global_extension
from boa.model.anchors import cost_candidates
from boa.model.bisection import (
    SearchParams,
    b_min_at,
    battery_rungs,
    build_pixel_frontier,
    corner_cut_mask,
    dispatch_metrics_min_load,
    search_box,
)
from boa.model.diagnostics import (
    plot_global_optimum_baseload_power_simulation_map,
    plot_regional_optimum_baseload_power_simulation_map,
)
from boa.model.frontier_cache import frontier_at, read_frontier_cache
from boa.model.global_extension import (
    build_frontier_cache_for_region,
    combine_regional_datasets_into_global_dataset,
    query_frontier_cache_for_region,
)
from boa.model.logic import minimum_load_dispatch
from boa.model.single_point_run import execute_single_point_baseload_power_simulation
from boa.store_schema import profile_store_stem

EXTRACT = Path(__file__).parent / "data" / "cds-2024" / "cds-zarr" / "pv_and_wind_potential_EUROPE_2024_025_deg.zarr"
SPANISH_CELLS = {"central Spain": (39.5, -3.0), "north-west coast of Spain": (43.75, -7.75)}
MIN_LOADS = (0.2, 0.3, 0.6)


def _stored_designs(frontier):
    """Each stored design as `(s, w, b, hours, energy)`, read as the store keeps it."""
    for slot in range(frontier.n_patches):
        n_s, n_w = (int(x) for x in frontier.patch_points[slot])
        for a in range(n_s):
            for b in range(n_w):
                for r in range(frontier.b_patch.shape[-1]):
                    battery = float(frontier.b_patch[slot, a, b, r])
                    if np.isfinite(battery) and frontier.energy_served_frac[slot, a, b, r] > 0:
                        yield (
                            float(frontier.s_patch[slot, a]),
                            float(frontier.w_patch[slot, b]),
                            battery,
                            float(frontier.hours_covered_frac[slot, a, b, r]),
                            float(frontier.energy_served_frac[slot, a, b, r]),
                        )


@pytest.fixture(scope="module")
def spanish_weather() -> dict[str, dict[str, np.ndarray]]:
    """The 2024 weather of two Spanish cells, from the weather extract in `tests/data/`."""
    store = xr.open_zarr(EXTRACT, consolidated=True)
    weather = {}
    for name, (lat, lon) in SPANISH_CELLS.items():
        cell = store.sel(y=lat, x=lon, method="nearest")
        weather[name] = {
            variable: np.ascontiguousarray(cell[variable].values, dtype=np.float64) for variable in ("solar", "wind")
        }
    return weather


@pytest.mark.parametrize("min_load", MIN_LOADS)
def test_the_compiled_dispatch_equals_its_reference(profiles, rounding_profiles, min_load):
    rng = np.random.default_rng(0)
    for weather in (profiles, rounding_profiles):
        for _ in range(40):
            s, w, b = rng.uniform(0.0, 6.0), rng.uniform(0.0, 4.0), rng.choice([0.0, rng.uniform(0.0, 30.0)])
            generation = s * weather["solar"] + w * weather["wind"]
            expected = minimum_load_dispatch(generation, b, min_load)
            assert dispatch_metrics_min_load(weather["solar"], weather["wind"], s, w, b, min_load) == expected


@pytest.mark.parametrize("min_load", MIN_LOADS)
def test_an_hour_that_reaches_the_minimum_load_exactly_runs(min_load):
    solar, wind = np.zeros(24), np.zeros(24)
    solar[12] = min_load
    expected = (1 / 24, min_load / 24)
    assert dispatch_metrics_min_load(solar, wind, 1.0, 0.0, 0.0, min_load) == expected
    assert minimum_load_dispatch(solar, 0.0, min_load) == expected


# Compiles in a fresh numba cache, since numba refuses to inspect code it loaded from one.
PRUNING_CHECK = """
import json
import numpy as np
from boa.model.bisection import (
    SearchParams, _b_min_bound_jit, _b_min_jit, _bracket_jit, _metrics, _rung_metrics_jit,
    b_min_at, battery_rungs, coarse_b_min_grid,
)

hours = np.arange(24 * 21)
solar = np.clip(0.55 * np.sin((hours % 24 - 6) * np.pi / 12), 0.0, None)
wind = np.full(hours.shape, 0.3)
params = SearchParams(ladder_rungs=3, ladder_max_span=1.5)
axis = np.linspace(0.0, 6.0, 25)
for min_load in (None, 0.3):
    b, cov, sf = b_min_at(solar, wind, 3.0, 2.0, 0.85, params, min_load=min_load)
    battery_rungs(solar, wind, 3.0, 2.0, b, cov, sf, params, min_load=min_load, coverage=0.85)
    coarse_b_min_grid(solar, wind, axis, axis, 0.85, params, min_load=min_load)
counts = {
    f.__name__: {
        str(sig[f.py_func.__code__.co_varnames.index("m")]): {
            "references": f.inspect_llvm(sig).count("dispatch_metrics_min_load"),
            "infinities": f.inspect_llvm(sig).count("0x7FF0000000000000"),
        }
        for sig in f.signatures
    }
    for f in (_metrics, _bracket_jit, _b_min_jit, _b_min_bound_jit, _rung_metrics_jit)
}
print(json.dumps(counts))
"""


def test_numba_compiles_the_minimum_load_out_of_the_default_path(tmp_path):
    """
    BOA's defaults pass `min_load=None`, and numba resolves `m is None` when it compiles, so the
    default path holds no reference to the minimum-load dispatch and no check of battery sizes
    against the target (whose infeasible size is the only infinity `_rung_metrics_jit` writes).
    LLVM inlines the dispatch, so the test counts references to it in the LLVM code that numba
    emits, not calls.
    Without the pruning, numba cannot type the minimum-load branch with `m=None`, so default
    builds would fail to compile; they would not slow down.
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
        assert by_type["none"]["references"] == 0, name
        assert by_type["float64"]["references"] > 0, name
    assert counts["_rung_metrics_jit"]["none"]["infinities"] == 0
    assert counts["_rung_metrics_jit"]["float64"]["infinities"] > 0


@pytest.mark.parametrize("min_load", MIN_LOADS)
def test_b_min_under_a_minimum_load_is_the_jump_point(profiles, min_load):
    """
    The minimum-load twin of `test_b_min_is_the_coverage_jump_point`, at every node of a grid
    that needs a battery: the process runs in enough hours at `b_min`, and not at nine tenths
    of it.
    """
    solar, wind = profiles["solar"], profiles["wind"]
    tested = 0
    for s in np.linspace(0.25, 6.0, 24):
        for w in np.linspace(0.25, 4.0, 16):
            b_min, _, _ = b_min_at(solar, wind, s, w, 0.95, SearchParams(), min_load=min_load)
            if not 0.0 < b_min < np.inf:
                continue
            tested += 1
            assert dispatch_metrics_min_load(solar, wind, s, w, b_min, min_load)[0] >= 0.95
            assert dispatch_metrics_min_load(solar, wind, s, w, 0.9 * b_min, min_load)[0] < 0.95
    assert tested >= 20


@pytest.mark.parametrize("min_load", MIN_LOADS)
def test_the_coarse_tier_lies_at_or_below_the_minimum_load_battery(profiles, anchor_costs, min_load):
    """
    A regression check on this weather: at every coarse node outside the corner cut, the build's
    coarse tier lies at or below the battery `b_min_at` finds there under the same minimum load.
    A coarse sweep that dispatched by another rule would break it.
    """
    solar, wind = profiles["solar"], profiles["wind"]
    params = SearchParams()
    frontier = build_pixel_frontier(solar, wind, 0.95, params, anchor_costs, min_load=min_load)
    s_max, w_max = (min(x * 2**frontier.box_widenings, params.box_abs_max) for x in search_box(solar, wind, params))
    s_axis, w_axis = np.linspace(0.0, s_max, params.coarse_grid), np.linspace(0.0, w_max, params.coarse_grid)
    assert np.array_equal(s_axis.astype(np.float32), frontier.s_coarse)
    assert np.array_equal(w_axis.astype(np.float32), frontier.w_coarse)
    cut = corner_cut_mask(s_axis, w_axis, s_max, w_max, params.corner_cut_threshold)
    needing = 0
    for i, j in zip(*np.nonzero(~cut)):
        b_min, _, _ = b_min_at(solar, wind, s_axis[i], w_axis[j], 0.95, params, min_load=min_load)
        assert float(frontier.b_coarse[i, j]) <= b_min, (i, j)
        if 0.0 < b_min < np.inf:
            needing += 1
    assert needing >= 10


@pytest.mark.parametrize("min_load", MIN_LOADS)
@pytest.mark.parametrize("params", [SearchParams(), SearchParams(ladder_rungs=6, ladder_max_span=3.0)])
def test_every_design_stored_under_a_minimum_load_was_dispatched_and_meets_its_target(
    spanish_weather, anchor_costs, min_load, params
):
    """
    The minimum load turns exact designs on, so each stored design replays, from the sizes the
    store keeps, to the hours and energy the build stores with it. On this weather at least nine
    in ten stored designs hold a battery, so the build dispatches and checks the battery sizes
    above the smallest rather than copying a zero battery.
    """
    for name, weather in spanish_weather.items():
        solar, wind = weather["solar"], weather["wind"]
        frontier = build_pixel_frontier(solar, wind, 0.95, params, anchor_costs, min_load=min_load)
        designs = list(_stored_designs(frontier))
        assert designs, name
        with_battery = sum(b > 0.0 for _, _, b, _, _ in designs)
        assert with_battery >= 0.9 * len(designs), (name, with_battery, len(designs))
        for s, w, b, hours, energy in designs:
            assert dispatch_metrics_min_load(solar, wind, s, w, b, min_load) == (hours, energy)
            assert hours >= 0.95


@pytest.mark.parametrize("min_load, s, w", [(0.3, 1.0, 1.0), (None, 2.5, 2.0)])
def test_a_battery_size_that_misses_the_target_under_a_minimum_load_is_stored_as_infeasible(profiles, min_load, s, w):
    """
    No size above the smallest missed the target in the sweep below, so the test takes a size
    below it: `battery_rungs` gets a quarter of `b_min`, and its next size, 1.05 times that,
    misses the target. Under a minimum load that size comes back as infeasible; flat demand has
    no check.
    """
    solar, wind = profiles["solar"], profiles["wind"]
    b_min, cov, sf = b_min_at(solar, wind, s, w, 0.85, SearchParams(), min_load=min_load)
    assert 0.0 < b_min < np.inf
    params = SearchParams(ladder_rungs=2, ladder_max_span=1.05)
    b, hours, energy = battery_rungs(solar, wind, s, w, 0.25 * b_min, cov, sf, params, min_load=min_load, coverage=0.85)
    if min_load is None:
        assert np.isfinite(b[1]) and hours[1] < 0.85
    else:
        assert (b[1], hours[1], energy[1]) == (np.inf, 0.0, 0.0)


def test_a_minimum_load_alone_makes_every_battery_a_float32_value(profiles):
    """
    `b_min_at` and `battery_rungs` turn exact designs on under a minimum load, without `exact`.
    Neither the hint 0.3 nor most multiples of `b_min` are float32 values, so without the
    rounding the battery and the five larger sizes would come back as values that float32
    cannot hold.
    """
    solar, wind = profiles["solar"], profiles["wind"]
    b_min, cov, sf = b_min_at(solar, wind, 1.0, 1.0, 0.85, SearchParams(), hint=0.3, min_load=0.3)
    assert 0.0 < b_min < np.inf
    params = SearchParams(ladder_rungs=6, ladder_max_span=3.0)
    batteries, _, _ = battery_rungs(solar, wind, 1.0, 1.0, b_min, cov, sf, params, min_load=0.3, coverage=0.85)
    for battery in (b_min, *batteries):
        assert battery == float(np.float32(battery))


@pytest.mark.parametrize("min_load", [0.0, 1.0, -0.1, 1.5])
def test_a_minimum_load_outside_zero_to_one_is_refused(profiles, anchor_costs, min_load):
    with pytest.raises(ValueError, match="min_load"):
        b_min_at(profiles["solar"], profiles["wind"], 3.0, 2.0, 0.85, SearchParams(), min_load=min_load)
    with pytest.raises(ValueError, match="min_load"):
        build_pixel_frontier(profiles["solar"], profiles["wind"], 0.85, SearchParams(), anchor_costs, min_load=min_load)


def test_battery_sizes_under_a_minimum_load_need_the_target(profiles):
    with pytest.raises(ValueError, match="coverage target"):
        battery_rungs(profiles["solar"], profiles["wind"], 3.0, 2.0, 1.0, 0.9, 0.9, SearchParams(), min_load=0.3)


@pytest.mark.parametrize("min_load", MIN_LOADS)
def test_hours_run_never_fall_as_the_battery_grows(spanish_weather, min_load):
    """
    The sweep the minimum load's guards ask for: 200 random designs per cell, each with a battery
    from 0 to 40 hours of full load in 400 steps.
    """
    rng = np.random.default_rng(0)
    batteries = np.linspace(0.0, 40.0, 401)
    for name, weather in spanish_weather.items():
        s_max, w_max = search_box(weather["solar"], weather["wind"], SearchParams())
        for _ in range(200):
            s, w = rng.uniform(0.0, s_max), rng.uniform(0.0, w_max)
            hours = [
                dispatch_metrics_min_load(weather["solar"], weather["wind"], s, w, b, min_load)[0] for b in batteries
            ]
            assert np.all(np.diff(hours) >= 0.0), (name, s, w)


@pytest.mark.parametrize("asked, written", [(0.3, None), (0.3, 0.2), (None, 0.3)])
def test_a_query_refuses_an_existing_output_written_at_another_minimum_load(tmp_path, asked, written):
    """The output records exact designs as the query asks for them, so only the minimum load differs."""
    config = PathConfig.from_root(tmp_path, input_set="cds-2024", cost_set="default", run="r")
    (config.zarr_dir / (profile_store_stem("EUROPE", 2024) + ".zarr")).mkdir(parents=True)
    output = config.optimal_sol_path(2024, 1.0, 0.85, "EUROPE", 2025, asked)
    output.parent.mkdir(parents=True)
    query = partial(query_frontier_cache_for_region, 2025, "EUROPE", 1.0, 0.85, None, 25, config, 1, min_load=asked)

    def write(min_load: float | None) -> None:
        exact = {} if asked is None else {"exact_designs": 1}
        xr.Dataset(attrs={**exact, **({} if min_load is None else {"min_load": min_load})}).to_netcdf(output)

    write(written)
    with pytest.raises(ValueError, match="minimum load"):
        query()
    write(asked)
    with query() as existing:
        assert existing.attrs.get("min_load") == asked


def test_the_global_combine_keeps_the_minimum_load_and_refuses_regions_at_another(tmp_path, monkeypatch):
    monkeypatch.setattr(global_extension, "REGION_COORDS", dict.fromkeys(("NORTH", "SOUTH")))
    config = PathConfig.from_root(tmp_path, run="r")

    def write(n: int, region: str, min_load: float | None) -> None:
        output = config.optimal_sol_path(2024, 1.0, 0.85, region, 2025, 0.3)
        output.parent.mkdir(parents=True, exist_ok=True)
        xr.Dataset(
            {"lcoe": (("lat", "lon"), np.full((2, 2), 50.0))},
            coords={"lat": [10.0 + n, 10.25 + n], "lon": [20.0, 20.25]},
            attrs={
                "search_params_hash": "a7d2c707",
                "region": region,
                "exact_designs": 1,
                **({} if min_load is None else {"min_load": min_load}),
            },
        ).to_netcdf(output)

    # In the last case both regions agree, but not with the combine's own minimum load.
    for north, south, stale in ((0.3, 0.2, "'SOUTH'"), (0.3, None, "'SOUTH'"), (0.2, 0.2, "'NORTH', 'SOUTH'")):
        write(0, "NORTH", north)
        write(1, "SOUTH", south)
        with pytest.raises(ValueError, match=rf"\[{stale}\] were not queried at minimum load 0.3"):
            combine_regional_datasets_into_global_dataset(2025, 0.85, 1.0, config, 2024, min_load=0.3)

    write(0, "NORTH", 0.3)
    write(1, "SOUTH", 0.3)
    combined = combine_regional_datasets_into_global_dataset(2025, 0.85, 1.0, config, 2024, min_load=0.3)
    assert combined.attrs["min_load"] == 0.3
    assert config.optimal_sol_path(2024, 1.0, 0.85, "GLOBAL", 2025, 0.3).exists()


def _cell_weather(path_config: PathConfig, lat: float, lon: float) -> dict[str, np.ndarray]:
    cell = open_regional_dataset("profile", "EUROPE", path_config).sel(x=lon, y=lat, method="nearest")
    return {name: np.ascontiguousarray(cell[name].values.flatten(), dtype=np.float64) for name in ("solar", "wind")}


def test_a_minimum_load_reaches_the_region_build_and_its_query(extract_data_root, monkeypatch):
    """
    Each stored design replays under the minimum load to the hours and energy stored with it,
    within one step of the store's 16-bit fractions. Hours alone would not catch a store of
    flat designs, since a design that meets the target under flat demand meets it under a
    minimum load too; the energy used tells them apart.
    """
    candidates = cost_candidates((2025,), lambda year: _validate_cost_set(extract_data_root, year))
    profile = open_regional_dataset("profile", "EUROPE", extract_data_root)
    store = build_frontier_cache_for_region("EUROPE", 0.85, profile, candidates, extract_data_root, 1, min_load=0.3)
    assert store.parts[-3] == "cov0p85_minload0p3" and store.name.endswith("_exact.zarr")

    cache = read_frontier_cache(store, SearchParams(), 0.85, 2024, exact=True, min_load=0.3)
    assert cache.meta["run_params"]["min_load"] == 0.3
    solved = 0
    for k in range(cache.n_points):
        designs = list(_stored_designs(frontier_at(cache, k)))
        solved += bool(designs)
        weather = _cell_weather(extract_data_root, float(cache.lats[k]), float(cache.lons[k]))
        for s, w, b, hours, energy in designs:
            replayed = dispatch_metrics_min_load(weather["solar"], weather["wind"], s, w, b, 0.3)
            np.testing.assert_allclose(replayed, (hours, energy), rtol=0, atol=1 / 65535)
            assert replayed[0] >= 0.85
    assert solved

    costs, horizon = _validate_cost_set(extract_data_root, 2025)
    solution = query_frontier_cache_for_region(
        2025, "EUROPE", 1.0, 0.85, costs, horizon, extract_data_root, 1, min_load=0.3
    )
    out = extract_data_root.optimal_sol_path(2024, 1.0, 0.85, "EUROPE", 2025, 0.3)
    assert out.exists() and out.parents[2].name == "cov0p85_minload0p3"
    assert (solution.attrs["min_load"], solution.attrs["exact_designs"]) == (0.3, 1)
    # No flat store was built, and the flat query does not fall back on this one.
    with pytest.raises(FileNotFoundError):
        query_frontier_cache_for_region(2025, "EUROPE", 1.0, 0.85, costs, horizon, extract_data_root, 1, force=True)

    # The plots read the minimum load's outputs and land in its folders.
    monkeypatch.setattr(global_extension, "REGION_COORDS", dict.fromkeys(("EUROPE",)))
    plot_regional_optimum_baseload_power_simulation_map(2025, "EUROPE", 0.85, 1.0, extract_data_root, 2024, 0.3)
    combined = combine_regional_datasets_into_global_dataset(2025, 0.85, 1.0, extract_data_root, 2024, min_load=0.3)
    plot_global_optimum_baseload_power_simulation_map(combined, 2025, 0.85, 1.0, extract_data_root, 2024, 0.3)
    for region in ("EUROPE", "GLOBAL"):
        assert list(extract_data_root.map_plots_dir(2024, 1.0, 0.85, region, 0.3).glob("*.png")), region


def test_point_mode_builds_under_a_minimum_load(extract_data_root):
    lat, lon = SPANISH_CELLS["central Spain"]
    result = execute_single_point_baseload_power_simulation(
        path_config=extract_data_root,
        year=2025,
        lat=lat,
        lon=lon,
        load_density=1.0,
        coverage=0.85,
        generate_plots=False,
        include_plot_data=True,
        min_load=0.3,
    )
    assert result["status"] == 1 and result["coverage"] >= 0.85
    weather = _cell_weather(extract_data_root, lat, lon)
    design = result["design"]
    replayed = dispatch_metrics_min_load(
        weather["solar"], weather["wind"], design["solar"], design["wind"], design["battery"], 0.3
    )
    assert replayed == (result["coverage"], result["served_fraction"])
    # The state of charge follows the flat dispatch, so it is left out under a minimum load.
    assert result["plot_data"]["time_series"]["state_of_charge_mwh"] == []
