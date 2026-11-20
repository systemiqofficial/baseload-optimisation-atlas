"""The capacity maps: the available-share map and the LCOE + capacity-potential panel."""

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest
import xarray as xr

from boa.cds.max_capacity import pixel_area
from boa.model.capacity_maps import (
    SHARE_VMAX,
    availability_share,
    plot_availability_share,
    plot_lcoe_and_potential,
)

LAT = np.array([10.0, 10.25, 10.5])
LON = np.array([20.0, 20.25])


def _store(pv_share, wind_share):
    area = pixel_area(LAT)[:, None]
    return xr.Dataset(
        {"pv": (("y", "x"), area * 50.0 * pv_share), "wind": (("y", "x"), area * 7.0 * wind_share)},
        coords={"y": LAT, "x": LON},
        attrs={"density_mw_per_km2": "{'pv': 50.0, 'wind': 7.0}"},
    )


def test_share_is_the_ceiling_over_area_times_density():
    pv = np.array([[0.0, 0.02], [0.03, 0.08], [0.0, 0.0]])
    wind = np.full((3, 2), 0.1)
    share = availability_share(_store(pv, wind))
    assert share["pv"].dims == ("lat", "lon")
    np.testing.assert_allclose(share["pv"].values, pv, atol=1e-12)
    np.testing.assert_allclose(share["wind"].values, wind, atol=1e-12)


def test_the_share_scale_ends_at_the_largest_table_fraction():
    assert SHARE_VMAX == pytest.approx(0.10)


def test_share_map_is_written(tmp_path):
    share = availability_share(_store(np.array([[0.0, 0.02], [0.03, 0.08], [0.0, 0.0]]), np.full((3, 2), 0.1)))
    land = xr.DataArray(np.ones((3, 2), dtype=bool), dims=("lat", "lon"), coords={"lat": LAT, "lon": LON})
    out = plot_availability_share(share, tmp_path / "share.png", land=land, title="test")
    assert out.exists() and out.stat().st_size > 0


def test_panel_is_written_with_zero_and_missing_potential(tmp_path):
    ds = xr.Dataset(
        {
            "lcoe": (("lat", "lon"), np.array([[50.0, np.nan], [80.0, 120.0], [250.0, 60.0]])),
            "max_baseload_mw": (("lat", "lon"), np.array([[300.0, np.nan], [0.0, 5.0], [2.0e4, 40.0]])),
        },
        coords={"lat": LAT, "lon": LON},
    )
    out = plot_lcoe_and_potential(ds, tmp_path / "panel.png")
    assert out.exists() and out.stat().st_size > 0
