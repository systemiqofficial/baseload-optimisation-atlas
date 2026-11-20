"""
Supply curves: how much can be produced, and at what cost, with each pixel as one step.

Each pixel is a rectangle: its width is the quantity it can supply (by default the annual energy
of its capacity potential), its height its cost (by default the LCOE). Two orders are drawn:

  * by cost, so the curve rises from the cheapest pixel to the dearest, coloured by region;
  * by region, so each region is one block, with its own pixels by cost inside it.

The functions take any two variables on `(lat, lon)` and label the axes from each variable's
`long_name` and `units`, so a downstream file (for example an LCOH and a hydrogen potential)
plots the same way. Pixels with no cost, or a quantity of 0 or none, are left out.
"""

from pathlib import Path

import cmcrameri.cm as cmc  # type: ignore[import-untyped]
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.collections import PolyCollection
from matplotlib.patches import Patch

from boa.geo.iso3_finder import iso3_at_batch
from boa.model.capacity_maps import describe_dataset, variable_label

# Natural Earth column that names a pixel's region. The World Bank regions give seven groups, a
# number of colours a reader can still tell apart.
DEFAULT_REGION_COLUMN = "REGION_WB"
NO_REGION = "No region"

# Larger units for a total that would otherwise need many digits: unit -> (larger unit, factor).
_LARGER_UNITS = {"MW": ("GW", 1.0e3), "kW": ("MW", 1.0e3), "t": ("kt", 1.0e3), "kt": ("Mt", 1.0e3)}


def pixel_regions(
    ds: xr.Dataset,
    iso3_grid_path: Path,
    shapefile_path: Path,
    column: str = DEFAULT_REGION_COLUMN,
) -> xr.DataArray:
    """
    The region of each pixel of `ds`, on its `(lat, lon)` grid: the pixel's country from the ISO-3
    grid, and the country's `column` in the Natural Earth map-subunits file. Pixels with no
    country get an empty string.
    """
    lat2, lon2 = np.meshgrid(ds.lat.values, ds.lon.values, indexing="ij")
    iso3 = iso3_at_batch(lat2.ravel(), lon2.ravel(), iso3_grid_path)
    units = gpd.read_file(shapefile_path, ignore_geometry=True)
    lookup: dict[str, str] = {}
    for key in ("ADM0_A3", "ISO_A3"):  # ISO_A3 last, so it wins where both are set
        for code, region in zip(units[key], units[column]):
            if isinstance(code, str) and code != "-99":
                lookup[code] = str(region)
    regions = np.array([lookup.get(str(code), "") for code in iso3], dtype=object)
    return xr.DataArray(regions.reshape(lat2.shape), dims=("lat", "lon"), coords={"lat": ds.lat, "lon": ds.lon})


def supply_table(ds: xr.Dataset, cost_var: str, quantity_var: str, regions: xr.DataArray | None = None) -> pd.DataFrame:
    """One row per pixel that can supply something: `cost`, `quantity` and `region`."""
    cost = ds[cost_var].values.ravel()
    quantity = ds[quantity_var].values.ravel()
    region = regions.values.ravel().astype(object) if regions is not None else np.full(cost.shape, "", dtype=object)
    keep = np.isfinite(cost) & np.isfinite(quantity) & (quantity > 0)
    table = pd.DataFrame({"cost": cost[keep], "quantity": quantity[keep], "region": region[keep]})
    table["region"] = table["region"].replace("", NO_REGION)
    return table


def _scaled_quantity(table: pd.DataFrame, units: str | None) -> tuple[pd.Series, str | None]:
    """The quantity in a larger unit when the total needs one, and that unit."""
    if units in _LARGER_UNITS and table["quantity"].sum() >= 1.0e4:
        larger, factor = _LARGER_UNITS[units]
        return table["quantity"] / factor, larger
    return table["quantity"], units


def _rectangles(widths: np.ndarray, heights: np.ndarray) -> np.ndarray:
    """One rectangle per step, as `(n, 4, 2)` corners, placed side by side from x = 0."""
    right = np.cumsum(widths)
    left = right - widths
    zeros = np.zeros_like(heights)
    return np.stack(
        [
            np.column_stack([left, zeros]),
            np.column_stack([left, heights]),
            np.column_stack([right, heights]),
            np.column_stack([right, zeros]),
        ],
        axis=1,
    )


def _region_colours(regions: list[str]) -> dict[str, tuple]:
    """
    Colours from Crameri's categorical batlowS, in its own order: its first colours are the ones
    that differ most, so a few regions stay apart. Grey for pixels with no region.
    """
    named = [r for r in regions if r != NO_REGION]
    palette = cmc.batlowS.colors
    colours = {r: tuple(palette[i % len(palette)]) for i, r in enumerate(named)}
    colours[NO_REGION] = (0.74, 0.74, 0.74)
    return colours


def plot_supply_curves(
    ds: xr.Dataset,
    out_path: Path,
    cost_var: str = "lcoe",
    quantity_var: str = "max_annual_energy_twh",
    regions: xr.DataArray | None = None,
    title: str | None = None,
    cost_max: float | None = None,
) -> Path:
    """
    Two supply curves of `cost_var` over `quantity_var`: ordered by cost and coloured by region,
    and ordered by region (largest total first, each region by cost inside its block).

    The cost axis ends at the 99th percentile of the pixel costs unless `cost_max` is given, so a
    few very expensive pixels do not flatten the curve; the share of the quantity above it is
    stated in the panel.
    """
    table = supply_table(ds, cost_var, quantity_var, regions)
    widths, x_units = _scaled_quantity(table, ds[quantity_var].attrs.get("units"))
    table = table.assign(width=widths.to_numpy())
    region_order = list(table.groupby("region")["width"].sum().sort_values(ascending=False).index)
    colours = _region_colours(region_order)
    top = cost_max if cost_max is not None else float(np.percentile(table["cost"], 99.0)) if len(table) else 1.0

    fig, (ax_cost, ax_region) = plt.subplots(2, 1, figsize=(10, 9), sharey=True, layout="constrained")

    by_cost = table.sort_values("cost", kind="stable")
    ax_cost.add_collection(
        PolyCollection(
            list(_rectangles(by_cost["width"].to_numpy(), by_cost["cost"].to_numpy())),
            facecolors=[colours[r] for r in by_cost["region"]],
            edgecolors="none",
            rasterized=True,
        )
    )
    ax_cost.set_title("Ordered by cost", loc="left")

    by_region = table.assign(order=table["region"].map({r: i for i, r in enumerate(region_order)}))
    by_region = by_region.sort_values(["order", "cost"], kind="stable")
    ax_region.add_collection(
        PolyCollection(
            list(_rectangles(by_region["width"].to_numpy(), by_region["cost"].to_numpy())),
            facecolors=[colours[r] for r in by_region["region"]],
            edgecolors="none",
            rasterized=True,
        )
    )
    edges = np.cumsum(by_region.groupby("order", sort=True)["width"].sum().to_numpy())
    for edge in edges[:-1]:
        ax_region.axvline(edge, color="black", linewidth=0.6)
    ax_region.set_title("Ordered by region, each region by cost", loc="left")

    total = float(table["width"].sum())
    above = float(table.loc[table["cost"] > top, "width"].sum())
    name = str(ds[quantity_var].attrs.get("long_name", quantity_var))
    x_label = f"Cumulative {name.lower()} ({x_units})" if x_units and x_units != "1" else f"Cumulative {name.lower()}"
    for ax in (ax_cost, ax_region):
        ax.set_xlim(0.0, total if total > 0 else 1.0)
        ax.set_ylim(0.0, top)
        ax.set_xlabel(x_label)
        ax.set_ylabel(variable_label(ds[cost_var]))
        if above > 0:
            ax.text(
                0.99,
                0.97,
                f"{100 * above / total:.1f} % of the quantity costs more than {top:.0f}",
                transform=ax.transAxes,
                ha="right",
                va="top",
                fontsize=8,
            )
    fig.legend(
        handles=[Patch(facecolor=colours[r], label=r) for r in region_order],
        loc="outside right center",
        frameon=False,
        title="Region",
    )
    fig.suptitle(title if title is not None else describe_dataset(ds))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path
