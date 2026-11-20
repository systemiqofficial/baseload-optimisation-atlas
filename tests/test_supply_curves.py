"""Supply curves: one step per pixel, ordered by cost or by region, for any cost and quantity."""

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest
import xarray as xr

from boa.model.supply_curves import NO_REGION, _rectangles, plot_supply_curves, supply_table

LAT = np.array([0.0, 0.25])
LON = np.array([10.0, 10.25, 10.5])


def _ds():
    return xr.Dataset(
        {
            "lcoe": (
                ("lat", "lon"),
                np.array([[50.0, 80.0, np.nan], [40.0, 60.0, 90.0]]),
                {"long_name": "LCOE", "units": "USD/MWh"},
            ),
            "max_annual_energy_twh": (
                ("lat", "lon"),
                np.array([[2.0, 0.0, 5.0], [1.0, 3.0, np.nan]]),
                {"long_name": "Annual energy of the capacity potential", "units": "TWh/yr"},
            ),
        },
        coords={"lat": LAT, "lon": LON},
        attrs={"region": "GLOBAL", "investment_year": 2035},
    )


def _regions():
    return xr.DataArray(
        np.array([["A", "B", "A"], ["B", "", "A"]], dtype=object), dims=("lat", "lon"), coords={"lat": LAT, "lon": LON}
    )


def test_the_table_keeps_only_pixels_that_supply_something_at_a_cost():
    table = supply_table(_ds(), "lcoe", "max_annual_energy_twh", _regions())
    # Left out: no cost (lat 0, lon 10.5), quantity 0 (lat 0, lon 10.25), no quantity (lat 0.25, lon 10.5).
    assert sorted(table["cost"]) == [40.0, 50.0, 60.0]
    assert table.loc[table["cost"] == 60.0, "region"].item() == NO_REGION


def test_rectangles_sit_side_by_side_from_zero():
    corners = _rectangles(np.array([2.0, 1.0]), np.array([50.0, 40.0]))
    assert corners.shape == (2, 4, 2)
    np.testing.assert_allclose(corners[0, :, 0], [0.0, 0.0, 2.0, 2.0])
    np.testing.assert_allclose(corners[1, :, 0], [2.0, 2.0, 3.0, 3.0])
    np.testing.assert_allclose(corners[1, :, 1], [0.0, 40.0, 40.0, 0.0])


@pytest.mark.parametrize("regions", [None, "given"])
def test_the_curves_are_written(tmp_path, regions):
    out = plot_supply_curves(_ds(), tmp_path / "curve.png", regions=_regions() if regions else None)
    assert out.exists() and out.stat().st_size > 0
