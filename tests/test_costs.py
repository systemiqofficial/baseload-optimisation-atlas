import logging
from pathlib import Path

import pandas as pd
import pytest

from boa.geo.geospatial import CountryMappings
from boa.inputs.costs import preprocess_renewable_energy_cost_data

COUNTRY_REGIONS = {"DEU": "Europe", "AUS": "Oceania", "KEN": "Africa"}

# Oceania has the highest CAPEX summed over all technologies and years, but not the highest
# Battery CAPEX, so a fill from Oceania can't be mistaken for a per-technology maximum.
CAPEX = {
    ("Europe", "Solar PV"): [700.0, 630.0],
    ("Europe", "Onshore wind"): [1000.0, 900.0],
    ("Europe", "Battery"): [300.0, 270.0],
    ("Oceania", "Solar PV"): [900.0, 810.0],
    ("Oceania", "Onshore wind"): [1400.0, 1260.0],
    ("Oceania", "Battery"): [250.0, 225.0],
    ("Africa", "Solar PV"): [800.0, 720.0],
    ("Africa", "Onshore wind"): [1100.0, 990.0],
}


def _sheets(capex: dict[tuple[str, str], list[float]] = CAPEX) -> dict[str, pd.DataFrame]:
    rows = [[region, tech, *values] for (region, tech), values in capex.items()]
    return {
        "RES CAPEX projections": pd.DataFrame(rows, columns=["irena region", "tech", 2024, 2025]),
        "RES OPEX": pd.DataFrame(
            {"region": ["World"] * 3, "tech": ["Solar PV", "Onshore wind", "Battery"], "opex": [0.02, 0.03, 0.025]}
        ),
        "Cost of capital": pd.DataFrame(
            {"code": list(COUNTRY_REGIONS), "tech": ["Renewables"] * 3, "cost of capital": [0.05, 0.07, 0.1]}
        ),
        "Country mapping": pd.DataFrame(
            {"code": list(COUNTRY_REGIONS), "irena region": list(COUNTRY_REGIONS.values())}
        ),
    }


def _write(path: Path, sheets: dict[str, pd.DataFrame]) -> Path:
    with pd.ExcelWriter(path) as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return path


def _preprocess(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    code_df = pd.DataFrame({"iso3": list(COUNTRY_REGIONS)})
    return preprocess_renewable_energy_cost_data(code_df, COUNTRY_REGIONS, path)


def test_missing_capex_takes_the_costliest_regions_series(tmp_path, caplog):
    path = _write(tmp_path / "costs.xlsx", _sheets())

    with caplog.at_level(logging.WARNING):
        _, capex = _preprocess(path)

    assert capex.loc[("KEN", "battery")].tolist() == CAPEX[("Oceania", "Battery")]
    assert capex.loc[("KEN", "solar")].tolist() == CAPEX[("Africa", "Solar PV")]
    assert "KEN battery" in caplog.text
    assert "Oceania" in caplog.text


def test_blank_capex_cell_fails(tmp_path):
    capex = dict(CAPEX)
    capex[("Europe", "Battery")] = [300.0, float("nan")]
    path = _write(tmp_path / "costs.xlsx", _sheets(capex))

    with pytest.raises(ValueError, match=r"Europe Battery: 2025"):
        _preprocess(path)


def test_missing_cost_of_capital_takes_the_highest_and_warns(tmp_path, caplog):
    sheets = _sheets()
    coc = sheets["Cost of capital"]
    sheets["Cost of capital"] = coc[coc["code"] != "DEU"]
    path = _write(tmp_path / "costs.xlsx", sheets)

    with caplog.at_level(logging.WARNING):
        costs, _ = _preprocess(path)

    assert costs.loc["DEU", "Cost of capital (%)"] == 0.1
    assert "[COST OF CAPITAL FALLBACK] DEU" in caplog.text
    assert "AUS" not in caplog.text


def test_surrounding_spaces_in_key_columns_are_ignored(tmp_path, caplog):
    sheets = _sheets()
    capex = sheets["RES CAPEX projections"]
    capex["tech"] = capex["tech"] + " "
    capex["subregion code"] = pd.NA
    province = pd.DataFrame(
        [{"irena region": "Europe", "tech": "Solar PV", "subregion code": " DEU:DE-BY ", 2024: 650.0, 2025: 600.0}]
    )
    sheets["RES CAPEX projections"] = pd.concat([capex, province], ignore_index=True)
    sheets["RES OPEX"]["tech"] = " " + sheets["RES OPEX"]["tech"]
    sheets["Cost of capital"]["code"] = sheets["Cost of capital"]["code"] + " "
    sheets["Cost of capital"]["tech"] = " Renewables"
    sheets["Country mapping"]["code"] = " " + sheets["Country mapping"]["code"]
    sheets["Country mapping"]["irena region"] = sheets["Country mapping"]["irena region"] + "\xa0"
    path = _write(tmp_path / "costs.xlsx", sheets)

    mapping = CountryMappings.from_excel(path).code_to_irena_region_map
    assert mapping == COUNTRY_REGIONS
    with caplog.at_level(logging.WARNING):
        costs, capex_per_country = _preprocess(path)

    assert costs.loc["DEU", "Cost of capital (%)"] == 0.05
    assert capex_per_country.loc[("DEU:DE-BY", "solar")].tolist() == [650.0, 600.0]
    assert "COST OF CAPITAL FALLBACK" not in caplog.text
