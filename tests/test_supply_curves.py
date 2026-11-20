"""Supply curves: one step per pixel, ordered by cost or by region, for any cost and quantity."""

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import Point

from boa.model.supply_curves import (
    COUNTRY_TO_REGION,
    NO_REGION,
    NO_REGION_COLOUR,
    REGIONS,
    SUBREGION_TO_REGION,
    _rectangles,
    country_regions,
    drop_costliest,
    plot_region_map,
    plot_supply_curves,
    region_colour,
    supply_table,
)

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


def test_the_costliest_share_of_each_region_is_left_out():
    table = pd.DataFrame(
        {
            "cost": [10.0, 20.0, 30.0, 40.0, 15.0, 99.0],
            "quantity": [50.0, 30.0, 18.0, 2.0, 98.0, 2.0],
            "region": ["A", "A", "A", "A", "B", "B"],
        }
    )
    kept = drop_costliest(table, 0.02)
    # A: 98 of 100 lie below cost 40, so the pixel at 40 goes. B: the pixel at 15 is 98 %, 99 goes.
    assert sorted(kept["cost"]) == [10.0, 15.0, 20.0, 30.0]
    assert drop_costliest(table, 0.0).equals(table)


def test_the_pixel_that_crosses_the_limit_stays():
    table = pd.DataFrame({"cost": [10.0, 20.0], "quantity": [97.0, 3.0], "region": ["A", "A"]})
    assert sorted(drop_costliest(table, 0.02)["cost"]) == [10.0, 20.0]


def test_each_subregion_maps_to_a_region_with_a_colour():
    assert set(SUBREGION_TO_REGION.values()) | set(COUNTRY_TO_REGION.values()) <= set(REGIONS)
    assert len(set(REGIONS.values())) == len(REGIONS)
    assert region_colour(NO_REGION) == NO_REGION_COLOUR


def test_country_regions_split_china_and_russia_from_their_subregions(tmp_path):
    units = gpd.GeoDataFrame(
        {
            "ADM0_A3": ["CHN", "JPN", "RUS", "DEU"],
            "ISO_A3": ["-99", "JPN", "-99", "DEU"],
            "SUBREGION": ["Eastern Asia", "Eastern Asia", "Eastern Europe", "Western Europe"],
        },
        geometry=[Point(0, 0)] * 4,
        crs="EPSG:4326",
    )
    path = tmp_path / "units.shp"
    units.to_file(path)
    lookup = country_regions(path)
    assert (lookup["CHN"], lookup["JPN"], lookup["RUS"], lookup["DEU"]) == (
        "China",
        "Other East Asia",
        "Russia",
        "Europe",
    )


@pytest.mark.parametrize("regions", [None, "given"])
def test_the_curves_are_written(tmp_path, regions):
    out = plot_supply_curves(_ds(), tmp_path / "curve.png", regions=_regions() if regions else None)
    assert out.exists() and out.stat().st_size > 0


def test_the_region_map_is_written(tmp_path):
    regions = _regions().copy(data=np.array([["Europe", "China", ""], ["Russia", "", "Europe"]], dtype=object))
    out = plot_region_map(regions, tmp_path / "regions.png")
    assert out.exists() and out.stat().st_size > 0
