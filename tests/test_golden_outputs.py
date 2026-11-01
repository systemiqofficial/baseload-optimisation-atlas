"""
Golden outputs: the results of the Baseload Optimisation Atlas (BOA) for two real Spanish cells,
compared with stored values.

The cells are central Spain (39.5° N, 3.0° W) and the north-west coast of Spain
(43.75° N, 7.75° W). Their weather comes from the extract in `tests/data/`, cut from BOA's 2024
EUROPE stores; their costs and geography come from a data root that `boa-data-prepare` built,
named by `BOA_TEST_DATA_ROOT`. Two paths are covered: the single-point run, step by step and as
one call, and the region build and query that `boa-run` drives.

On the continuous integration (CI) runner, where `CI=true`, every number and every frontier
hash must equal `tests/golden/spanish_cells.json` bit for bit. Elsewhere the maths library can
differ in the last bit, so status, cost key and design must match exactly, the levelised cost
of electricity (LCOE) and both fractions within a relative 1e-9, and the tests do not compare
the hashes. `pytest --update-golden` rewrites the file, on the runner through the workflow's
`update-golden` input, and a pull request that changes it says why.
"""

import dataclasses
import hashlib
import json
import math
import os
import platform
from pathlib import Path

import numba
import numpy as np
import pytest
import xarray as xr

import boa
from boa.cds.max_capacity import pixel_area
from boa.cli.run_simulation import _validate_cost_set
from boa.config.data_packages import CORE_DATA_SHA256, CORE_DATA_VERSION, COST_DATA_SHA256, COST_DATA_VERSION
from boa.config.paths import PathConfig
from boa.geo.iso3_finder import iso3_at
from boa.inputs.costs import process_global_baseload_simulation_costs
from boa.inputs.profiles import open_regional_dataset
from boa.model.anchors import cost_candidates
from boa.model.bisection import STATUS_OK, PixelFrontier, SearchParams, argmin_lcoe, build_pixel_frontier
from boa.model.cost_calculations import lcoe_coefficients
from boa.model.frontier_cache import frontier_at, read_frontier_cache
from boa.model.global_extension import build_frontier_cache_for_region, query_frontier_cache_for_region
from boa.model.single_point_run import execute_single_point_baseload_power_simulation, extract_costs_for_point

GOLDEN = Path(__file__).parent / "golden" / "spanish_cells.json"
EXTRACT = Path(__file__).parent / "data" / "cds-2024"
REGION = "EUROPE"
CELLS = {"central Spain": (39.5, -3.0), "north-west coast of Spain": (43.75, -7.75)}
COVERAGES = (0.85, 0.95)
COST_YEARS = (2025, 2030)
REGION_COVERAGE = 0.95
LOAD_DENSITY = 1.0  # MW/km2, boa-run's default; neither the LCOE nor the design depends on it

ON_RUNNER = os.environ.get("CI") == "true"
EXACT = ("status", "cost_key", "solar", "wind", "battery")
CLOSE = ("lcoe", "hours_covered", "served_fraction")
RELATIVE_TOLERANCE = 1e-9
# The header fields that define the cases; the others record what wrote the file.
HEADER_INPUTS = ("search_params_hash", "core_data", "cost_data", "extract_sha256")


@pytest.fixture(scope="module", autouse=True)
def path_config(extract_data_root: PathConfig) -> PathConfig:
    """
    The throwaway data root of `conftest.py`, with the extract as input set `cds-2024`, so nothing
    the tests write outlives the run. Every test here needs it, so without a root they all skip,
    except in CI, where they fail.
    """
    return extract_data_root


def frontier_sha256(frontier: PixelFrontier) -> str:
    """
    SHA-256 over every field of a frontier: its name, data type, shape and raw bytes. A change to
    any stored design then fails on the runner, not only one that moves the optimum.
    """
    digest = hashlib.sha256()
    for field in dataclasses.fields(frontier):
        value = getattr(frontier, field.name)
        array = np.ascontiguousarray(value) if isinstance(value, np.ndarray) else np.asarray(value, dtype=np.int64)
        digest.update(field.name.encode())
        digest.update(array.dtype.str.encode())
        digest.update(repr(array.shape).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def solve_point(path_config: PathConfig, lat: float, lon: float, coverage: float, year: int) -> dict:
    """
    The steps of `execute_single_point_baseload_power_simulation`, taken one by one so that the
    frontier it prices can be hashed: the cell's own costs are the one anchor.
    """
    costs, horizon = process_global_baseload_simulation_costs(
        year, path_config.input_data_path, path_config.cost_cache_dir
    )
    capex, opex_pct, cost_of_capital, cost_key = extract_costs_for_point(
        lat, lon, costs, iso3_at(lat, lon, path_config.iso3_grid_path)
    )
    cell = open_regional_dataset("profile", REGION, path_config).sel(x=lon, y=lat, method="nearest")
    frontier = build_pixel_frontier(
        np.ascontiguousarray(cell["solar"].values.flatten(), dtype=np.float64),
        np.ascontiguousarray(cell["wind"].values.flatten(), dtype=np.float64),
        coverage,
        SearchParams(),
        lcoe_coefficients(horizon, capex, opex_pct, cost_of_capital, 1.0),
    )
    load_mw = LOAD_DENSITY * float(pixel_area(np.array([cell.y.values]))[0])
    optimum = argmin_lcoe(frontier, lcoe_coefficients(horizon, capex, opex_pct, cost_of_capital, load_mw))
    return {
        "status": frontier.status,
        "cost_key": cost_key,
        "lcoe": optimum.lcoe,
        "solar": optimum.solar,
        "wind": optimum.wind,
        "battery": optimum.battery,
        "hours_covered": optimum.hours_covered,
        "served_fraction": optimum.served_fraction,
        "frontier_sha256": frontier_sha256(frontier),
    }


@pytest.fixture(scope="module")
def point_cases(path_config) -> list[dict]:
    """Both cells at both coverages and both cost years: eight cases."""
    return [
        {
            "inputs": {
                "cell": cell,
                "lat": lat,
                "lon": lon,
                "coverage": coverage,
                "cost_year": year,
                "load_density": LOAD_DENSITY,
            },
            "outputs": solve_point(path_config, lat, lon, coverage, year),
        }
        for cell, (lat, lon) in CELLS.items()
        for coverage in COVERAGES
        for year in COST_YEARS
    ]


@pytest.fixture(scope="module")
def region_cells(path_config) -> list[dict]:
    """
    The extract's EUROPE region, built and priced as `boa-run` does it: anchors over every cost
    key for both years, one frontier store, then one query per year. The solved cells are the
    block cells on land; the cells outside the blocks hold no weather to solve. Each cell also
    carries the fingerprint of its frontier as the store holds it, so a change to the stored
    designs fails on the runner even where the optimum stays put.
    """
    candidates = cost_candidates(COST_YEARS, lambda year: _validate_cost_set(path_config, year))
    profile = open_regional_dataset("profile", REGION, path_config)
    store = build_frontier_cache_for_region(REGION, REGION_COVERAGE, profile, candidates, path_config, n_workers=1)
    cache = read_frontier_cache(store)
    position = {(int(i), int(j)): k for k, (i, j) in enumerate(zip(cache.iy, cache.ix))}
    cells = []
    for year in COST_YEARS:
        costs, horizon = _validate_cost_set(path_config, year)
        solution = query_frontier_cache_for_region(
            year, REGION, LOAD_DENSITY, REGION_COVERAGE, costs, horizon, path_config, n_workers=1
        )
        for i, j in np.argwhere(solution["status"].values == STATUS_OK):
            cell = solution.isel(lat=i, lon=j)
            cells.append(
                {
                    "inputs": {
                        "region": REGION,
                        "lat": float(cell["lat"]),
                        "lon": float(cell["lon"]),
                        "coverage": REGION_COVERAGE,
                        "cost_year": year,
                        "anchor_years": list(COST_YEARS),
                        "load_density": LOAD_DENSITY,
                    },
                    "outputs": {
                        "status": int(cell["status"]),
                        "cost_key": str(cell["cost_key"].values),
                        "lcoe": float(cell["lcoe"]),
                        "solar": float(cell["solar_factor"]),
                        "wind": float(cell["wind_factor"]),
                        "battery": float(cell["battery_factor"]),
                        "hours_covered": float(cell["coverage"]),
                        "served_fraction": float(cell["served_fraction"]),
                        "frontier_sha256": frontier_sha256(frontier_at(cache, position[int(i), int(j)])),
                    },
                }
            )
    return cells


def header() -> dict:
    """What the golden numbers were computed from, and the software and platform that computed them."""
    return {
        "boa_version": boa.__version__,
        "search_params_hash": SearchParams().identity_hash(),
        "core_data": {"version": CORE_DATA_VERSION, "sha256": CORE_DATA_SHA256},
        "cost_data": {"version": COST_DATA_VERSION, "sha256": COST_DATA_SHA256},
        # Finder leaves .DS_Store files in the folders it opens and git ignores them, so they
        # are not part of the extract; zarr's own dotfiles are.
        "extract_sha256": {
            path.relative_to(EXTRACT.parent).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(EXTRACT.rglob("*"))
            if path.is_file() and path.name != ".DS_Store"
        },
        "numpy": np.__version__,
        "numba": numba.__version__,
        "platform": platform.platform(),
    }


@pytest.fixture(scope="module")
def golden(request) -> dict:
    """
    The stored golden outputs. With `--update-golden` this run's results replace them first,
    which is the only way the file is meant to change.
    """
    if request.config.getoption("--update-golden"):
        document = {
            "header": header(),
            "point": request.getfixturevalue("point_cases"),
            "region": request.getfixturevalue("region_cells"),
        }
        text = json.dumps(document, indent=2) + "\n"
        assert json.loads(text) == document, "the golden file would not read back exactly"
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(text)
    return json.loads(GOLDEN.read_text())


def assert_matches(cases: list[dict], golden_cases: list[dict]) -> None:
    """
    Compare cases with their golden values by this platform's rule, and list every output that
    differs, so one failure shows the whole drift rather than its first number.
    """
    assert [case["inputs"] for case in cases] == [case["inputs"] for case in golden_cases], "the cases differ"
    differences = []
    for case, golden_case in zip(cases, golden_cases):
        for key, expected in golden_case["outputs"].items():
            actual = case["outputs"][key]
            if ON_RUNNER or key in EXACT:
                same = actual == expected
            elif key in CLOSE:
                same = math.isclose(actual, expected, rel_tol=RELATIVE_TOLERANCE)
            else:
                continue
            if not same:
                differences.append(f"{case['inputs']}: {key} is {actual!r}, golden {expected!r}")
    assert not differences, "\n".join(differences)


def test_the_golden_file_was_written_from_these_inputs(golden):
    """
    The search settings, the data pins and the extract define the cases. When one of them
    changes, the stored numbers describe other inputs, so `--update-golden` rewrites the file
    and the pull request says why.
    """
    current = header()
    assert {key: golden["header"][key] for key in HEADER_INPUTS} == {key: current[key] for key in HEADER_INPUTS}


def test_the_point_path_matches_the_golden_outputs(point_cases, golden):
    """
    The coverage changes what the frontier holds and the cost year changes how it is priced, so
    the eight cases cover both halves of the single-point run for both cells.
    """
    assert_matches(point_cases, golden["point"])


def test_one_call_of_the_point_function_matches_its_steps(path_config, point_cases):
    """
    The golden point cases come from the steps, so one call of the function itself must give
    the same answer, or the steps could drift from what it does. One case is enough: every case
    takes the same steps.
    """
    inputs, outputs = point_cases[0]["inputs"], point_cases[0]["outputs"]
    result = execute_single_point_baseload_power_simulation(
        path_config=path_config,
        year=inputs["cost_year"],
        lat=inputs["lat"],
        lon=inputs["lon"],
        load_density=inputs["load_density"],
        coverage=inputs["coverage"],
        generate_plots=False,
    )
    assert {
        "status": result["status"],
        "cost_key": result["cost_key"],
        "lcoe": result["lcoe"],
        **result["design"],
        "hours_covered": result["coverage"],
        "served_fraction": result["served_fraction"],
    } == {key: value for key, value in outputs.items() if key != "frontier_sha256"}


def test_the_region_path_matches_the_golden_outputs(region_cells, golden):
    """
    The region path prices the same cells differently by design: it searches under more anchors
    and stores its fractions as fixed-point numbers, so it has golden values of its own.
    """
    assert_matches(region_cells, golden["region"])


def test_the_region_path_records_neither_exact_designs_nor_a_minimum_load(path_config, region_cells):
    """Both options enter an output's attributes only when set, so a default output keeps the attributes it had."""
    for year in COST_YEARS:
        output = path_config.optimal_sol_path(2024, LOAD_DENSITY, REGION_COVERAGE, REGION, year)
        with xr.open_dataset(output) as solution:
            assert not {"exact_designs", "min_load"} & set(solution.attrs), year
