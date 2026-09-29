import logging
from pathlib import Path

import pandas as pd
import pytest

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


def _write_workbook(path: Path, capex: dict[tuple[str, str], list[float]]) -> None:
    rows = [[region, tech, *values] for (region, tech), values in capex.items()]
    capex_sheet = pd.DataFrame(rows, columns=["irena region", "tech", 2024, 2025])
    opex = pd.DataFrame(
        {"region": ["World"] * 3, "tech": ["Solar PV", "Onshore wind", "Battery"], "opex": [0.02, 0.03, 0.025]}
    )
    cost_of_capital = pd.DataFrame(
        {"code": list(COUNTRY_REGIONS), "tech": ["Renewables"] * 3, "cost of capital": [0.05, 0.07, 0.1]}
    )
    country = pd.DataFrame({"code": list(COUNTRY_REGIONS), "irena region": list(COUNTRY_REGIONS.values())})
    with pd.ExcelWriter(path) as writer:
        capex_sheet.to_excel(writer, sheet_name="RES CAPEX projections", index=False)
        opex.to_excel(writer, sheet_name="RES OPEX", index=False)
        cost_of_capital.to_excel(writer, sheet_name="Cost of capital", index=False)
        country.to_excel(writer, sheet_name="Country mapping", index=False)


def _preprocess(path: Path) -> pd.DataFrame:
    code_df = pd.DataFrame({"iso3": list(COUNTRY_REGIONS)})
    _, capex_per_country = preprocess_renewable_energy_cost_data(code_df, COUNTRY_REGIONS, path)
    return capex_per_country


def test_missing_capex_takes_the_costliest_regions_series(tmp_path, caplog):
    path = tmp_path / "costs.xlsx"
    _write_workbook(path, CAPEX)

    with caplog.at_level(logging.WARNING):
        capex = _preprocess(path)

    assert capex.loc[("KEN", "battery")].tolist() == CAPEX[("Oceania", "Battery")]
    assert capex.loc[("KEN", "solar")].tolist() == CAPEX[("Africa", "Solar PV")]
    assert "KEN battery" in caplog.text
    assert "Oceania" in caplog.text


def test_blank_capex_cell_fails(tmp_path):
    capex = dict(CAPEX)
    capex[("Europe", "Battery")] = [300.0, float("nan")]
    path = tmp_path / "costs.xlsx"
    _write_workbook(path, capex)

    with pytest.raises(ValueError, match=r"Europe.*Battery.*2025"):
        _preprocess(path)
