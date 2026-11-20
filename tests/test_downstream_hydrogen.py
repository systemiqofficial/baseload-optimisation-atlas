"""LCOH from the per-pixel LCOE: annuity, parameters, arithmetic and the file step."""

import csv
import dataclasses

import numpy as np
import pytest
import xarray as xr

from boa.config.sources import load_registry, sources_with_tag
from boa.config.paths import PathConfig
from boa.downstream.finance import crf
from boa.downstream.hydrogen import (
    ASSUMPTION,
    KWH_PER_KG_H2_LHV,
    PARAMETERS_PATH,
    Electrolyser,
    ParameterTable,
    group_of,
    lcoh,
)
from boa.downstream.lcoh_file import OUTPUT_VARIABLES, build_lcoh


def _annuity(rate: float, years: int) -> float:
    return 1.0 / sum((1.0 + rate) ** -t for t in range(1, years + 1))


@pytest.fixture(scope="module")
def table() -> ParameterTable:
    return ParameterTable.read()


def _flat(table: ParameterTable, **changes) -> Electrolyser:
    return dataclasses.replace(Electrolyser.from_table(table, "other", "STEPS", 2030), **changes)


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
    assert table.value("capex", "other", "STEPS", 2030) == pytest.approx(2600 + (1650 - 2600) * 6 / 11)
    assert table.value("capex", "china", "NZE", 2060) == pytest.approx(310)


def test_wacc_premium_falls_linearly_to_zero_in_2050(table):
    assert table.value("wacc_premium", "other", "STEPS", 2025) == pytest.approx(0.03)
    assert table.value("wacc_premium", "china", "CPS", 2037.5) == pytest.approx(0.015)
    assert table.value("wacc_premium", "other", "NZE", 2060) == pytest.approx(0.0)


def test_efficiency_is_held_after_2030(table):
    assert table.value("efficiency_lhv", "other", "STEPS", 2050) == pytest.approx(0.64)
    assert table.value("efficiency_lhv", "china", "STEPS", 2027) == pytest.approx(0.60)


@pytest.mark.parametrize("key, group", [("CHN", "china"), ("CHN:CN-NM", "china"), ("HKG", "china"), ("TWN", "other")])
def test_group_of_cost_key(key, group):
    assert group_of(key) == group


def test_a_table_without_a_parameter_for_a_group_is_rejected(table):
    rows = [r for r in table.rows if not (r.parameter == "capex" and r.group == "china")]
    with pytest.raises(ValueError, match="no capex for group china"):
        ParameterTable(rows)


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


def _write_year(path_config: PathConfig, year: int) -> None:
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
    path = path_config.optimal_sol_path(2025, 1.0, 0.9, "GLOBAL", year)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path)


def test_build_lcoh_writes_the_promoted_layout_with_lcoh_as_primary_variable(tmp_path):
    path_config = PathConfig.from_root(tmp_path, input_set="cds-2025", cost_set="core-steps", run="r_abcd")
    for year in (2030, 2050):
        _write_year(path_config, year)

    path = build_lcoh(path_config, 2025, 1.0, 0.9, "STEPS")

    assert path.name == "optimal_lcoh_wy2025_01MWkm2_cov0p9_steps_2030_2050.nc"
    with xr.open_dataset(path) as ds:
        assert ds.attrs["primary_variable"] == "lcoh"
        assert ds.attrs["lcoh_basis"] == "per_kg_h2_lhv"
        assert set(OUTPUT_VARIABLES) <= set(ds.data_vars)
        assert ds["lcoh"].dims == ("year", "lat", "lon")
        assert ds["lcoh"].attrs["units"] == "USD/kg"
        lcoh_2030 = ds["lcoh"].sel(year=2030).values
        assert np.isnan(lcoh_2030[0, 2]) and np.isnan(lcoh_2030[1, 2])  # status 0 and 2
        assert lcoh_2030[0, 0] < lcoh_2030[0, 1]  # China CAPEX is lower
        assert float(ds["lcoh"].sel(year=2050)[0, 1]) < float(ds["lcoh"].sel(year=2030)[0, 1])
        total = sum(ds[f"lcoh_{part}"] for part in ("electricity", "capital", "fom", "stack"))
        np.testing.assert_allclose(total.values, ds["lcoh"].values, rtol=1e-5)
    parameters = path.with_name(path.stem + "_parameters.csv").read_text(encoding="utf-8")
    assert "iea-weo-2025: Table B.5" in parameters


def test_build_lcoh_without_outputs_raises(tmp_path):
    path_config = PathConfig.from_root(tmp_path, run="empty")
    with pytest.raises(FileNotFoundError, match="boa-run"):
        build_lcoh(path_config, 2025, 1.0, 0.9)
