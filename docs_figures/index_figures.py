"""
Make the result map of the `index` page from a real per-year GLOBAL output file.

    uv run python docs_figures/index_figures.py

Output (in `docs/assets/index/`):

- `f7_global_lcoe_map.png`: the LCOE of the optimal system for one investment year, and the
  solar, wind and battery factor of that system (figure F7).

The script reads one per-year GLOBAL NetCDF of the run `RUN` under the BOA data root
(`$BOA_DATA_ROOT`, else `~/.boa`). It does not write to the data root. The caption of the figure
on the page names the weather set, cost set, coverage and run hash, and these must agree with
the constants below and with the attributes of the file.
"""

import sys

import numpy as np
import xarray as xr

import _style
from _style import BATTERY, REPO_ROOT, SOLAR, WIND

import matplotlib.pyplot as plt  # noqa: E402  (after _style sets the backend)
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "src"))

from boa.config.paths import PathConfig  # noqa: E402

PAGE = "index"

# The run behind the figure: weather set cds-2025 (weather year 2025), cost set `default`,
# coverage 0.9, load density 1 MW/km2. The run hash is the last part of the run name.
RUN = "wy2025_default_boa110_49e8"
WEATHER_YEAR = 2025
LOAD_DENSITY = 1.0
COVERAGE = 0.9
INVESTMENT_YEAR = 2025

# Map window: the regions of the model cover about 58 deg S to 72 deg N.
LAT_MIN, LAT_MAX = -58.0, 74.0

# Colour of the pixels without a result (ocean, and pixels with a status other than 1).
NO_RESULT = "#E3E3E3"


def tech_cmap(colour: str) -> LinearSegmentedColormap:
    """White to the technology colour, so each map has the same colour as its technology."""
    return LinearSegmentedColormap.from_list("tech", ["#FFFFFF", colour])


def load() -> xr.Dataset:
    path_config = PathConfig.from_auto_detect(run=RUN)
    path = path_config.optimal_sol_path(WEATHER_YEAR, LOAD_DENSITY, COVERAGE, "GLOBAL", INVESTMENT_YEAR)
    ds = xr.open_dataset(path).load()
    assert int(ds.attrs["era5_weather_year"]) == WEATHER_YEAR
    assert float(ds.attrs["coverage_fraction"]) == COVERAGE
    assert int(ds.attrs["capacity_ceiling_applied"]) == 0
    return ds


def panel(ax, ds: xr.Dataset, name: str, title: str, cmap, vmin: float, vmax: float, unit: str):
    """Draw one map. Only pixels with status 1 (optimum found) have a value."""
    data = ds[name].where(ds["status"] == 1).sel(lat=slice(LAT_MIN, LAT_MAX))
    cmap = cmap.copy()
    cmap.set_bad(NO_RESULT)
    image = ax.imshow(
        np.ma.masked_invalid(data.values),
        origin="lower",
        extent=(-180.125, 180.125, float(data.lat.min()) - 0.125, float(data.lat.max()) + 0.125),
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
        aspect="equal",
    )
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.set_xticks([-120, -60, 0, 60, 120])
    ax.set_xticklabels(["120°W", "60°W", "0°", "60°E", "120°E"], fontsize=8)
    ax.set_yticks([-40, -20, 0, 20, 40, 60])
    ax.set_yticklabels(["40°S", "20°S", "0°", "20°N", "40°N", "60°N"], fontsize=8)
    ax.grid(False)
    for side in ax.spines.values():
        side.set_visible(False)
    cbar = ax.figure.colorbar(image, ax=ax, orientation="horizontal", fraction=0.05, pad=0.12, aspect=40, extend="max")
    cbar.set_label(unit, fontsize=9)
    cbar.ax.tick_params(labelsize=8)
    cbar.outline.set_visible(False)


def make_map() -> None:
    ds = load()
    fig, axes = plt.subplots(2, 2, figsize=(12.0, 7.4))
    panel(axes[0, 0], ds, "lcoe", "LCOE", plt.get_cmap("viridis_r"), 20, 200, "USD per MWh delivered (values above 200 share the last colour)")
    panel(axes[0, 1], ds, "solar_factor", "Solar factor", tech_cmap(SOLAR), 0, 10, "MW of solar per MW of demand (above 10: last colour)")
    panel(axes[1, 0], ds, "wind_factor", "Wind factor", tech_cmap(WIND), 0, 6, "MW of wind per MW of demand (above 6: last colour)")
    panel(axes[1, 1], ds, "battery_factor", "Battery factor", tech_cmap(BATTERY), 0, 60, "hours of demand (above 60: last colour)")
    fig.tight_layout(h_pad=1.0, w_pad=1.0)
    path = _style.save(fig, PAGE, "f7_global_lcoe_map.png")
    print(path, path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    _style.apply()
    plt.rcParams["savefig.dpi"] = 110
    make_map()
