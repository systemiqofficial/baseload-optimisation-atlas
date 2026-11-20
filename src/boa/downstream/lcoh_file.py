"""
Apply the LCOH arithmetic (``boa.downstream.hydrogen``) to one scenario of a BOA run.

Reads the scenario's per-year GLOBAL outputs (``optimal_sol_*_GLOBAL_<year>.nc``): they hold the
three inputs per pixel, ``lcoe``, ``served_fraction`` and ``cost_of_capital``, exactly as the run
priced them. The promoted LCOE file has only ``lcoe``.

Writes, into ``PathConfig.downstream_dir``:

- ``optimal_lcoh_*.nc``: the layout of the promoted LCOE file (one ``(year, lat, lon)`` grid per
  variable, ``cost_key_id`` and ``status`` once, the run's attributes), with ``lcoh`` as the main
  variable (file attribute ``primary_variable``) and its components;
- ``<same stem>_parameters.csv``: the parameter values each investment year and group used, with
  their source labels.
"""

from __future__ import annotations

import csv
import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import xarray as xr

from boa.config import run_manifest
from boa.config.constants import STATUS_CODES
from boa.config.paths import PathConfig
from boa.downstream.hydrogen import (
    GROUPS,
    PARAMETERS,
    PARAMETERS_PATH,
    SCENARIOS,
    Electrolyser,
    ParameterTable,
    group_of,
    lcoh,
)
from boa.model.lcoe_promotion import CARRIED_ATTRS, encode_cost_keys, year_files

log = logging.getLogger(__name__)

LCOH_SCHEMA_VERSION = 1
STATUS_OPTIMUM = 1

# name -> (long_name, units). Every variable is float32 on (year, lat, lon).
OUTPUT_VARIABLES: dict[str, tuple[str, str]] = {
    "lcoh": ("LCOH", "USD/kg"),
    "lcoh_electricity": ("LCOH: electricity", "USD/kg"),
    "lcoh_capital": ("LCOH: electrolyser capital", "USD/kg"),
    "lcoh_fom": ("LCOH: electrolyser fixed O&M", "USD/kg"),
    "lcoh_stack": ("LCOH: stack replacement", "USD/kg"),
    "electrolyser_wacc": ("Electrolyser WACC (pixel WACC plus premium)", "fraction"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cost_set_scenario(cost_set: str) -> str | None:
    """The WEO scenario that a cost-set name such as ``core-steps`` names, if any."""
    tokens = cost_set.lower().replace("_", "-").split("-")
    found = [s for s in SCENARIOS if s.lower() in tokens]
    return found[0] if len(found) == 1 else None


def _attrs(path_config: PathConfig, reference: xr.Dataset, years: list[int], scenario: str, table_path: Path) -> dict:
    manifest = run_manifest.load(path_config) or {}
    provenance = manifest.get("provenance", {})
    attrs = {name: reference.attrs[name] for name in CARRIED_ATTRS if name in reference.attrs}
    attrs.update(
        {
            "schema_version": LCOH_SCHEMA_VERSION,
            "title": "Levelised cost of hydrogen per investment year, from the BOA LCOE (optional downstream step)",
            "source": "Baseload Optimisation Atlas (BOA), boa.downstream.hydrogen",
            "primary_variable": "lcoh",
            "lcoh_basis": "per_kg_h2_lhv",
            "electrolyser_sizing": "1 kW of electrolyser per kW of baseload; full-load hours = 8760 x served_fraction",
            "electrolyser_scenario": scenario,
            "parameters_sha256": _sha256(table_path),
            "run": path_config.run,
            "input_set": provenance.get("input_set", path_config.input_set),
            "cost_set": provenance.get("cost_set", path_config.cost_set),
            "input_data_sha256": provenance.get("input_data_sha256") or "",
            "boa_version": provenance.get("boa_version", ""),
            "years": np.asarray(years, dtype="int32"),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    return attrs


def _write_parameters(path: Path, table: ParameterTable, scenario: str, years: list[int]) -> None:
    """One row per (year, group, parameter) the run used: the value, unit and the sources behind it."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "group", "parameter", "value", "unit", "sources"])
        for year in years:
            for group in GROUPS:
                for parameter in PARAMETERS:
                    rows = table.rows_for(parameter, group, scenario)
                    sources = ";".join(dict.fromkeys(r.source for r in rows))
                    value = table.value(parameter, group, scenario, year)
                    writer.writerow([year, group, parameter, f"{value:g}", rows[0].unit, sources])


def build_lcoh(
    path_config: PathConfig,
    weather_year: int,
    load_density: float,
    coverage: float,
    scenario: str = "STEPS",
    table_path: Path = PARAMETERS_PATH,
) -> Path:
    """Price hydrogen for every pixel and investment year of one run scenario; return the LCOH file path."""
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}, got {scenario!r}")
    table = ParameterTable.read(table_path)
    files = year_files(path_config, weather_year, load_density, coverage)
    if not files:
        raise FileNotFoundError(
            f"No GLOBAL optimal-solution NetCDFs for {load_density:g} MW/km2 at coverage {coverage:g}, weather "
            f"year {weather_year} in run '{path_config.run}' — run `boa-run` first."
        )
    years = list(files)

    with xr.open_dataset(files[years[0]]) as reference:
        lat, lon = reference["lat"].values, reference["lon"].values
        cost_key = np.asarray(reference["cost_key"].values)
        status = np.asarray(reference["status"].values).astype(np.int8)
        attrs = _attrs(path_config, reference, years, scenario, table_path)

    implied = _cost_set_scenario(str(attrs["cost_set"]))
    if implied and implied != scenario:
        log.warning(f"Cost set '{attrs['cost_set']}' names {implied}, but the electrolyser scenario is {scenario}.")

    is_china = np.vectorize(lambda k: bool(k) and group_of(str(k)) == "china", otypes=[bool])(cost_key)
    out = {name: np.full((len(years), lat.size, lon.size), np.nan, dtype=np.float32) for name in OUTPUT_VARIABLES}

    for i, year in enumerate(years):
        with xr.open_dataset(files[year]) as ds:
            if not (np.array_equal(ds["lat"].values, lat) and np.array_equal(ds["lon"].values, lon)):
                raise ValueError(f"{files[year].name} is on a different grid than {files[years[0]].name}.")
            if not np.array_equal(np.asarray(ds["status"].values).astype(np.int8), status):
                raise ValueError(f"status differs between {files[years[0]].name} and {files[year].name}.")
            lcoe = ds["lcoe"].values.astype(float)
            served = ds["served_fraction"].values.astype(float)
            wacc = ds["cost_of_capital"].values.astype(float)
        priced = (status == STATUS_OPTIMUM) & (cost_key != "")
        for group, mask in (("china", priced & is_china), ("other", priced & ~is_china)):
            if not mask.any():
                continue
            result = lcoh(lcoe[mask], served[mask], wacc[mask], Electrolyser.from_table(table, group, scenario, year))
            out["lcoh"][i][mask] = result.total
            out["lcoh_electricity"][i][mask] = result.electricity
            out["lcoh_capital"][i][mask] = result.capital
            out["lcoh_fom"][i][mask] = result.fom
            out["lcoh_stack"][i][mask] = result.stack
            out["electrolyser_wacc"][i][mask] = result.wacc

    cost_key_id, legend = encode_cost_keys(cost_key)
    attrs["cost_key_legend"] = legend
    attrs["status_legend"] = ";".join(f"{code}={label}" for code, label in STATUS_CODES.items())
    data_vars: dict = {
        name: (("year", "lat", "lon"), out[name], {"long_name": long_name, "units": units})
        for name, (long_name, units) in OUTPUT_VARIABLES.items()
    }
    data_vars["cost_key_id"] = (
        ("lat", "lon"),
        cost_key_id,
        {"description": "Index into the cost_key_legend attribute"},
    )
    data_vars["status"] = (("lat", "lon"), status, {"description": "Index into the status_legend attribute"})
    dataset = xr.Dataset(
        coords={"year": np.asarray(years, dtype="int32"), "lat": lat, "lon": lon}, data_vars=data_vars, attrs=attrs
    )
    encoding: dict = {
        name: {"dtype": "float32", "zlib": True, "complevel": 4, "chunksizes": (1, lat.size, lon.size)}
        for name in OUTPUT_VARIABLES
    }
    encoding["cost_key_id"] = {"dtype": "int16", "zlib": True, "complevel": 4}
    encoding["status"] = {"dtype": "int8", "zlib": True, "complevel": 4}

    path = path_config.lcoh_path(weather_year, load_density, coverage, scenario, years[0], years[-1])
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_netcdf(path, mode="w", format="NETCDF4", encoding=encoding)
    _write_parameters(path.with_name(path.stem + "_parameters.csv"), table, scenario, years)
    log.info(f"Wrote {path}")
    return path
