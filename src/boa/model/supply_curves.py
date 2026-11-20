"""
Supply curves: how much can be produced, and at what cost, with each pixel as one step.

Each pixel is a rectangle: its width is the quantity it can supply (by default the annual energy
of its capacity potential), its height its cost (by default the LCOE). Two orders are drawn:

  * by cost, so the curve rises from the cheapest pixel to the dearest, coloured by region;
  * by region, so each region is one block, with its own pixels by cost inside it.

The most expensive share of each region's quantity (2 % by default) is left out of both curves, so
a few very expensive pixels do not flatten them. The regions are the fourteen `REGIONS`, made from
the UN subregions of the Natural Earth map, and `plot_region_map` shows them in the same colours.

The functions take any two variables on `(lat, lon)` and label the axes from each variable's
`long_name` and `units`, so a downstream file (for example an LCOH and a hydrogen potential)
plots the same way. Pixels with no cost, or a quantity of 0 or none, are left out.
"""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.collections import PolyCollection
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch

from boa.geo.iso3_finder import iso3_at_batch
from boa.model.capacity_maps import _figure, _frame, describe_dataset, variable_label

# The regions of the supply curves and their colours. The colours are Paul Tol's discrete rainbow
# for 14 colours (https://personal.sron.nl/~pault/), given to the regions so that neighbours differ.
REGIONS: dict[str, str] = {
    "North Africa": "#F7F056",
    "West & Central Africa": "#1965B0",
    "East & Southern Africa": "#E8601C",
    "Middle East": "#4EB265",
    "Central Asia": "#F1932D",
    "South Asia": "#AE76A3",
    "China": "#DC050C",
    "Other East Asia": "#D1BBD7",
    "Southeast Asia": "#CAE0AB",
    "Europe": "#5289C7",
    "Russia": "#882E72",
    "North America": "#F6C141",
    "Latin America & Caribbean": "#90C987",
    "Oceania & other": "#7BAFDE",
}
NO_REGION = "No region"
NO_REGION_COLOUR = "#BDBDBD"

# Natural Earth column that holds the UN subregion of a map subunit.
SUBREGION_COLUMN = "SUBREGION"
SUBREGION_TO_REGION = {
    "Northern Africa": "North Africa",
    "Western Africa": "West & Central Africa",
    "Middle Africa": "West & Central Africa",
    "Eastern Africa": "East & Southern Africa",
    "Southern Africa": "East & Southern Africa",
    "Western Asia": "Middle East",
    "Central Asia": "Central Asia",
    "Southern Asia": "South Asia",
    "Eastern Asia": "Other East Asia",
    "South-Eastern Asia": "Southeast Asia",
    "Northern Europe": "Europe",
    "Western Europe": "Europe",
    "Southern Europe": "Europe",
    "Eastern Europe": "Europe",
    "Northern America": "North America",
    "Central America": "Latin America & Caribbean",
    "Caribbean": "Latin America & Caribbean",
    "South America": "Latin America & Caribbean",
    "Australia and New Zealand": "Oceania & other",
    "Melanesia": "Oceania & other",
    "Micronesia": "Oceania & other",
    "Polynesia": "Oceania & other",
    "Seven seas (open ocean)": "Oceania & other",
    "Antarctica": "Oceania & other",
}
# Countries with a region of their own, and countries whose map subunits are in more than one UN
# subregion (for example with overseas territories). The ISO-3 grid gives only the country, so such
# a country gets the region of its main territory.
COUNTRY_TO_REGION = {
    "CHN": "China",
    "HKG": "China",
    "MAC": "China",
    "RUS": "Russia",
    "USA": "North America",
    "FRA": "Europe",
    "NLD": "Europe",
    "IND": "South Asia",
    "CHL": "Latin America & Caribbean",
    "ZAF": "East & Southern Africa",
    "SHN": "West & Central Africa",
    "NZL": "Oceania & other",
    "ATA": "Oceania & other",
}
DEFAULT_CUT_SHARE = 0.02

# Larger units for a total that would otherwise need many digits: unit -> (larger unit, factor).
_LARGER_UNITS = {"MW": ("GW", 1.0e3), "kW": ("MW", 1.0e3), "t": ("kt", 1.0e3), "kt": ("Mt", 1.0e3)}


def country_regions(shapefile_path: Path) -> dict[str, str]:
    """
    The region of each country code of the Natural Earth map-subunits file: from
    `COUNTRY_TO_REGION`, else from the UN subregion through `SUBREGION_TO_REGION`.
    """
    units = gpd.read_file(shapefile_path, ignore_geometry=True)
    lookup: dict[str, str] = {}
    for key in ("ADM0_A3", "ISO_A3"):  # ISO_A3 last, so it wins where both are set
        for code, subregion in zip(units[key], units[SUBREGION_COLUMN]):
            if isinstance(code, str) and code != "-99" and subregion in SUBREGION_TO_REGION:
                lookup[code] = SUBREGION_TO_REGION[subregion]
    lookup.update(COUNTRY_TO_REGION)
    return lookup


def pixel_regions(ds: xr.Dataset, iso3_grid_path: Path, shapefile_path: Path) -> xr.DataArray:
    """
    The region of each pixel of `ds`, on its `(lat, lon)` grid: the pixel's country from the ISO-3
    grid, and the country's region from `country_regions`. Pixels with no country, or with a
    country that has no region, get an empty string.
    """
    lat2, lon2 = np.meshgrid(ds.lat.values, ds.lon.values, indexing="ij")
    iso3 = iso3_at_batch(lat2.ravel(), lon2.ravel(), iso3_grid_path)
    lookup = country_regions(shapefile_path)
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


def drop_costliest(table: pd.DataFrame, share: float = DEFAULT_CUT_SHARE) -> pd.DataFrame:
    """
    `table` without the most expensive `share` of each region's quantity. A pixel stays when the
    quantity of the cheaper pixels of its region is less than `(1 - share)` of the region's total,
    so the pixel that crosses that limit stays.
    """
    if share <= 0.0 or table.empty:
        return table
    ordered = table.sort_values("cost", kind="stable")
    grouped = ordered.groupby("region")["quantity"]
    before = grouped.cumsum() - ordered["quantity"]
    keep = before < (1.0 - share) * grouped.transform("sum")
    return ordered[keep].sort_index()


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


def region_colour(region: str) -> str:
    """The colour of `region` in `REGIONS`, else the grey of `NO_REGION`."""
    return REGIONS.get(region, NO_REGION_COLOUR)


def plot_region_map(
    regions: xr.DataArray,
    out_path: Path,
    boundaries: gpd.GeoDataFrame | None = None,
    title: str | None = "Regions of the supply curves",
) -> Path:
    """A map of the region of each pixel, in the colours of the supply curves."""
    names = list(REGIONS)
    index = {name: float(i) for i, name in enumerate(names)}
    codes = np.array([index.get(r, np.nan) for r in regions.values.ravel()]).reshape(regions.shape)
    fig, axes = _figure(1, regions)
    ax = axes[0]
    ax.pcolormesh(
        regions.lon,
        regions.lat,
        codes,
        cmap=ListedColormap([REGIONS[n] for n in names]),
        norm=BoundaryNorm(np.arange(len(names) + 1) - 0.5, len(names)),
        shading="nearest",
        rasterized=True,
    )
    _frame(ax, regions, boundaries, "")
    present = set(regions.values.ravel())
    shown = [n for n in names if n in present]
    fig.legend(
        handles=[Patch(facecolor=REGIONS[n], label=n) for n in shown],
        loc="outside lower center",
        ncols=max(min(len(shown), 5), 1),
        frameon=False,
    )
    if title:
        fig.suptitle(title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_supply_curves(
    ds: xr.Dataset,
    out_path: Path,
    cost_var: str = "lcoe",
    quantity_var: str = "max_annual_energy_twh",
    regions: xr.DataArray | None = None,
    title: str | None = None,
    cost_max: float | None = None,
    cut_share: float = DEFAULT_CUT_SHARE,
) -> Path:
    """
    Two supply curves of `cost_var` over `quantity_var`: ordered by cost and coloured by region,
    and ordered by region (largest total first, each region by cost inside its block).

    The most expensive `cut_share` of each region's quantity is left out (see `drop_costliest`),
    and the panels say so. The cost axis ends at the highest cost that stays, unless `cost_max` is
    given.
    """
    table = drop_costliest(supply_table(ds, cost_var, quantity_var, regions), cut_share)
    widths, x_units = _scaled_quantity(table, ds[quantity_var].attrs.get("units"))
    table = table.assign(width=widths.to_numpy())
    region_order = list(table.groupby("region")["width"].sum().sort_values(ascending=False).index)
    colours = {r: region_colour(r) for r in region_order}
    top = cost_max if cost_max is not None else float(table["cost"].max()) if len(table) else 1.0

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
    name = str(ds[quantity_var].attrs.get("long_name", quantity_var))
    x_label = f"Cumulative {name.lower()} ({x_units})" if x_units and x_units != "1" else f"Cumulative {name.lower()}"
    for ax in (ax_cost, ax_region):
        ax.set_xlim(0.0, total if total > 0 else 1.0)
        ax.set_ylim(0.0, top)
        ax.set_xlabel(x_label)
        ax.set_ylabel(variable_label(ds[cost_var]))
        if cut_share > 0:
            ax.text(
                0.01,
                0.97,
                f"Most expensive {100 * cut_share:g} % of each region's quantity left out",
                transform=ax.transAxes,
                ha="left",
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
