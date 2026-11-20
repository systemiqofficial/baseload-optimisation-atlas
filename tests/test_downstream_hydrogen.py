"""LCOH from the per-pixel LCOE: annuity, parameters, arithmetic and the file step."""

import csv
import dataclasses

import numpy as np
import pytest
import xarray as xr

from boa.config.paths import PathConfig
from boa.config.sources import load_registry, sources_with_tag
from boa.downstream.finance import crf
from boa.downstream.hydrogen import (
    ASSUMPTION,
    KWH_PER_KG_H2_LHV,
    PARAMETERS_PATH,
    Electrolyser,
    ParameterTable,
    lcoh,
)
from boa.downstream.lcoh_file import OUTPUT_VARIABLES, build_lcoh


def _annuity(rate: float, years: int) -> float:
    return 1.0 / sum((1.0 + rate) ** -t for t in range(1, years + 1))


@pytest.fixture(scope="module")
def table() -> ParameterTable:
    return ParameterTable.read()


def _flat(table: ParameterTable, **changes) -> Electrolyser:
    return dataclasses.replace(Electrolyser.from_table(table, "STEPS", 2030), **changes)


# --- annuity --------------------------------------------------------------------------------------


def test_crf_is_the_inverse_of_the_discounted_year_sum():
    assert crf(0.07, 25) == pytest.approx(_annuity(0.07, 25))
    assert crf(0.12, 15) == pytest.approx(_annuity(0.12, 15))


def test_crf_at_zero_rate_is_one_over_years():
    assert crf(0.0, 20) == pytest.approx(0.05)


def test_crf_rejects_a_negative_rate_and_a_nonpositive_life():
    with pytest.raises(ValueError, match="negative"):
        crf(-0.01, 10)
    with pytest.raises(ValueError, match="positive"):
        crf(0.05, 0)


# --- parameters -----------------------------------------------------------------------------------


def test_every_parameter_row_names_a_registered_source_or_an_assumption():
    registry = load_registry()
    with PARAMETERS_PATH.open(newline="", encoding="utf-8") as f:
        sources = {row["source"] for row in csv.DictReader(f)}
    for label in sources - {ASSUMPTION}:
        source_id, ref = label.split(": ", 1)
        assert registry[source_id].label(ref) == label


def test_the_hydrogen_tag_holds_exactly_the_parameter_sources():
    with PARAMETERS_PATH.open(newline="", encoding="utf-8") as f:
        ids = {row["source"].split(": ", 1)[0] for row in csv.DictReader(f)} - {ASSUMPTION}
    assert ids == set(sources_with_tag("hydrogen"))


def test_each_parameter_has_one_unit(table):
    units: dict[str, set[str]] = {}
    for row in table.rows:
        units.setdefault(row.parameter, set()).add(row.unit)
    assert all(len(u) == 1 for u in units.values()), units


def test_capex_is_linear_between_the_weo_years_and_held_after_2050(table):
    assert table.value("capex", "STEPS", 2030, "upper") == pytest.approx(2600 + (1650 - 2600) * 6 / 11)
    assert table.value("capex", "NZE", 2060, "lower") == pytest.approx(310)


def test_mid_capex_is_the_mean_of_the_weo_range(table):
    assert table.value("capex", "STEPS", 2024) == pytest.approx(1600)
    assert table.value("capex", "STEPS", 2035) == pytest.approx((420 + 1650) / 2)
    years = np.array([2024.0, 2040.5, 2060.0])
    expected = (table.value("capex", "NZE", years, "lower") + table.value("capex", "NZE", years, "upper")) / 2
    np.testing.assert_allclose(table.value("capex", "NZE", years), expected)


def test_only_capex_differs_between_the_bounds(table):
    for parameter in ("efficiency_lhv", "fom_fraction", "stack_life_hours", "stack_share", "wacc_premium"):
        values = {table.value(parameter, "STEPS", 2030, b) for b in ("mid", "lower", "upper")}
        assert len(values) == 1, parameter


def test_mid_capex_names_the_rows_of_both_bounds(table):
    notes = {r.note.split(";")[0] for r in table.rows_for("capex", "STEPS")}
    assert notes == {"lower range", "upper range"}


def test_wacc_premium_falls_linearly_to_zero_in_2050(table):
    assert table.value("wacc_premium", "STEPS", 2025) == pytest.approx(0.03)
    assert table.value("wacc_premium", "CPS", 2037.5) == pytest.approx(0.015)
    assert table.value("wacc_premium", "NZE", 2060) == pytest.approx(0.0)


def test_efficiency_is_the_global_average_held_after_2030(table):
    assert table.value("efficiency_lhv", "STEPS", 2024) == pytest.approx(0.63)
    assert table.value("efficiency_lhv", "STEPS", 2050) == pytest.approx(0.64)


def test_a_table_without_a_parameter_for_a_bound_is_rejected(table):
    rows = [r for r in table.rows if not (r.parameter == "capex" and r.bound == "lower")]
    with pytest.raises(ValueError, match="no capex for bound lower"):
        ParameterTable(rows)


def test_an_unknown_bound_is_rejected(table):
    rows = [dataclasses.replace(r, bound="china") if r.parameter == "capex" else r for r in table.rows]
    with pytest.raises(ValueError, match="unknown bounds"):
        ParameterTable(rows)
    with pytest.raises(ValueError, match="bound must be one of"):
        table.value("capex", "STEPS", 2030, "median")


# --- arithmetic -----------------------------------------------------------------------------------


def test_capital_and_om_equal_the_discounted_cost_over_the_discounted_hydrogen(table):
    p = _flat(table, stack_share=0.0)
    lcoe, sf, wacc = 50.0, 0.93, 0.07
    result = lcoh(np.array([lcoe]), np.array([sf]), np.array([wacc]), p)

    r, n = wacc + p.wacc_premium, p.plant_life_years
    df = [(1 + r) ** -t for t in range(1, n + 1)]
    kg_per_year = 8760 * sf / p.kwh_per_kg
    expected = (p.capex + sum(p.fom_fraction * p.capex * d for d in df)) / sum(kg_per_year * d for d in df)

    assert result.capital[0] + result.fom[0] == pytest.approx(expected)
    assert result.electricity[0] == pytest.approx(lcoe * KWH_PER_KG_H2_LHV / p.efficiency_lhv / 1000)
    assert result.stack[0] == 0.0
    assert result.wacc[0] == pytest.approx(r)


def test_stack_replacements_happen_every_stack_life_within_the_plant_life(table):
    p = _flat(table)
    sf, wacc = 0.93, 0.07
    result = lcoh(np.array([50.0]), np.array([sf]), np.array([wacc]), p)

    r, hours = wacc + p.wacc_premium, 8760 * sf
    times = [
        k * p.stack_life_hours / hours for k in range(1, 10) if k * p.stack_life_hours / hours < p.plant_life_years
    ]
    assert len(times) == 3  # 6.1, 12.3 and 18.4 years in a 20-year plant
    present = sum(p.stack_share * float(p.capex_at(np.array(p.year + t))) * (1 + r) ** -t for t in times)
    assert result.stack[0] == pytest.approx(present * crf(r, p.plant_life_years) / (hours / p.kwh_per_kg))


def test_lower_served_fraction_raises_the_capital_part_only(table):
    p = _flat(table)
    result = lcoh(np.array([50.0, 50.0]), np.array([0.95, 0.5]), np.array([0.07, 0.07]), p)
    assert result.electricity[0] == result.electricity[1]
    assert result.capital[1] == pytest.approx(result.capital[0] * 0.95 / 0.5)


def test_invalid_inputs_give_nan(table):
    p = _flat(table)
    result = lcoh(
        np.array([50.0, np.nan, 50.0, 50.0]), np.array([0.9, 0.9, 0.0, 0.9]), np.array([0.07, 0.07, 0.07, np.nan]), p
    )
    assert np.isfinite(result.total[0])
    assert np.isnan(result.total[1:]).all()


# --- file step ------------------------------------------------------------------------------------


def _write_year(path_config: PathConfig, year: int, energy_twh: np.ndarray | None = None) -> None:
    lat, lon = np.array([0.0, 0.25]), np.array([10.0, 10.25, 10.5])
    ds = xr.Dataset(
        {
            "lcoe": (("lat", "lon"), np.full((2, 3), 50.0, dtype="float32")),
            "served_fraction": (("lat", "lon"), np.full((2, 3), 0.93, dtype="float32")),
            "cost_of_capital": (("lat", "lon"), np.full((2, 3), 0.07, dtype="float32")),
            "cost_key": (("lat", "lon"), np.array([["CHN", "DEU", ""], ["CHN", "DEU", "DEU"]])),
            "status": (("lat", "lon"), np.array([[1, 1, 0], [1, 1, 2]], dtype="int8")),
        },
        coords={"lat": lat, "lon": lon},
        attrs={"coverage_fraction": 0.9, "era5_weather_year": 2025, "capacity_ceiling_applied": 0},
    )
    if energy_twh is not None:
        ds["max_annual_energy_twh"] = (("lat", "lon"), energy_twh.astype("float32"))
    path = path_config.optimal_sol_path(2025, 1.0, 0.9, "GLOBAL", year)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path)


def test_build_lcoh_converts_the_energy_potential_to_hydrogen(tmp_path):
    path_config = PathConfig.from_root(tmp_path, input_set="cds-2025", cost_set="core-steps", run="r_abcd")
    _write_year(path_config, 2030, energy_twh=np.array([[2.0, 0.0, 5.0], [1.0, 1.0, 1.0]]))
    with xr.open_dataset(build_lcoh(path_config, 2025, 1.0, 0.9)) as ds:
        h2 = ds["max_annual_h2_kt"].sel(year=2030).values
        assert ds["max_annual_h2_kt"].attrs["units"] == "kt/yr"
    kwh_per_kg = KWH_PER_KG_H2_LHV / 0.64
    assert h2[0, 0] == pytest.approx(2.0e3 / kwh_per_kg, rel=1e-6)  # 2 TWh is about 38 kt
    assert h2[0, 1] == 0.0  # the land cannot hold the design
    assert np.isnan(h2[0, 2])  # status 0: no LCOH, no potential


def test_build_lcoh_without_a_potential_writes_no_potential(tmp_path):
    path_config = PathConfig.from_root(tmp_path, input_set="cds-2025", cost_set="core-steps", run="r_abcd")
    _write_year(path_config, 2030)
    with xr.open_dataset(build_lcoh(path_config, 2025, 1.0, 0.9)) as ds:
        assert "max_annual_h2_kt" not in ds.data_vars


def test_build_lcoh_writes_the_promoted_layout_with_lcoh_as_primary_variable(tmp_path):
    path_config = PathConfig.from_root(tmp_path, input_set="cds-2025", cost_set="core-steps", run="r_abcd")
    for year in (2030, 2050):
        _write_year(path_config, year)

    path = build_lcoh(path_config, 2025, 1.0, 0.9, "STEPS")

    assert path.name == "optimal_lcoh_wy2025_01MWkm2_cov0p9_steps_mid_2030_2050.nc"
    with xr.open_dataset(path) as ds:
        assert ds.attrs["primary_variable"] == "lcoh"
        assert ds.attrs["lcoh_basis"] == "per_kg_h2_lhv"
        assert ds.attrs["electrolyser_capex_bound"] == "mid"
        assert set(OUTPUT_VARIABLES) <= set(ds.data_vars)
        assert ds["lcoh"].dims == ("year", "lat", "lon")
        assert ds["lcoh"].attrs["units"] == "USD/kg"
        lcoh_2030 = ds["lcoh"].sel(year=2030).values
        assert np.isnan(lcoh_2030[0, 2]) and np.isnan(lcoh_2030[1, 2])  # status 0 and 2
        assert lcoh_2030[0, 0] == lcoh_2030[0, 1]  # one electrolyser for all countries
        assert float(ds["lcoh"].sel(year=2050)[0, 1]) < float(ds["lcoh"].sel(year=2030)[0, 1])
        total = sum(ds[f"lcoh_{part}"] for part in ("electricity", "capital", "fom", "stack"))
        np.testing.assert_allclose(total.values, ds["lcoh"].values, rtol=1e-5)
    parameters = path.with_name(path.stem + "_parameters.csv").read_text(encoding="utf-8")
    assert "iea-weo-2025: Table B.5" in parameters
    assert parameters.splitlines()[0] == "year,parameter,value,unit,sources"


def test_build_lcoh_capex_bounds_order_the_lcoh(tmp_path):
    path_config = PathConfig.from_root(tmp_path, input_set="cds-2025", cost_set="core-steps", run="r_abcd")
    _write_year(path_config, 2030)
    values = {}
    for bound in ("lower", "mid", "upper"):
        path = build_lcoh(path_config, 2025, 1.0, 0.9, "STEPS", bound)
        assert path.name.endswith(f"_steps_{bound}_2030_2030.nc")
        with xr.open_dataset(path) as ds:
            values[bound] = float(ds["lcoh"].sel(year=2030)[0, 1])
    assert values["lower"] < values["mid"] < values["upper"]
    with pytest.raises(ValueError, match="capex_bound"):
        build_lcoh(path_config, 2025, 1.0, 0.9, "STEPS", "median")


def test_build_lcoh_without_outputs_raises(tmp_path):
    path_config = PathConfig.from_root(tmp_path, run="empty")
    with pytest.raises(FileNotFoundError, match="boa-run"):
        build_lcoh(path_config, 2025, 1.0, 0.9)
