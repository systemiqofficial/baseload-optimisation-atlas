"""
Maps of the capacity ceiling: the available share of each pixel's land, and a cost map above a
quantity map (by default the LCOE above the capacity potential).

The colour maps are Crameri's Scientific Colour Maps (`cmcrameri`): perceptually uniform, so equal
steps in the data look like equal steps in colour, and readable with colour-vision deficiency.

Grey always means "land, but nothing available": a share of 0 in the share map, a potential of 0
in the potential map. White means "not modelled": sea, or outside the regions.
"""

import ast
from pathlib import Path

import cmcrameri.cm as cmc  # type: ignore[import-untyped]
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from matplotlib.colors import ListedColormap, LogNorm, Normalize
from matplotlib.patches import Patch

from boa.cds.max_capacity import pixel_area
from boa.config.physical_parameters import DENG_AVAILABILITY

# The share scale ends at the largest available fraction of the land-cover table (0.10 for wind
# in the "high" case), so the colours use the whole range of the data.
SHARE_VMAX = max(max(factors.values()) for factors in DENG_AVAILABILITY.values())

UNAVAILABLE_COLOUR = "#BDBDBD"
TECH_TITLES = {"pv": "Solar PV", "wind": "Wind"}


def availability_share(max_cap: xr.Dataset) -> dict[str, xr.DataArray]:
    """
    The available share of each pixel's area, per technology, from a max-capacity store:
    `ceiling / (pixel_area x density)`, with the densities the store records.

    Returned on `(lat, lon)`, so it plots like a per-year result file.
    """
    density = ast.literal_eval(max_cap.attrs["density_mw_per_km2"])
    area = xr.DataArray(pixel_area(max_cap.y.values), dims="y", coords={"y": max_cap.y})
    return {
        tech: (max_cap[tech] / (area * float(density[tech]))).rename({"y": "lat", "x": "lon"}).rename(tech)
        for tech in ("pv", "wind")
    }


def land_on_grid(lsm_path: Path, lat: np.ndarray, lon: np.ndarray) -> xr.DataArray:
    """
    Boolean land mask (ERA5 land-sea fraction above 0.5, the rule the model uses for its points)
    on the given grid. The ERA5 file has descending latitude on 0..360 longitude.
    """
    with xr.open_dataset(lsm_path) as ds:
        lsm = ds["lsm"]
        if "valid_time" in lsm.dims:
            lsm = lsm.isel(valid_time=0)
        lsm = lsm.assign_coords(longitude=(lsm.longitude + 180) % 360 - 180).sortby("longitude").sortby("latitude")
        on_grid = lsm.sel(
            latitude=xr.DataArray(lat, dims="lat"), longitude=xr.DataArray(lon, dims="lon"), method="nearest"
        )
        return xr.DataArray(on_grid.values > 0.5, dims=("lat", "lon"), coords={"lat": lat, "lon": lon})


def _grey_where(ax: plt.Axes, mask: xr.DataArray) -> None:
    """Paint `mask` (boolean, on lat/lon) in the "nothing available" grey."""
    ax.pcolormesh(
        mask.lon,
        mask.lat,
        np.where(mask.values, 1.0, np.nan),
        cmap=ListedColormap([UNAVAILABLE_COLOUR]),
        shading="nearest",
        rasterized=True,
    )


def _frame(ax: plt.Axes, data: xr.DataArray, boundaries: gpd.GeoDataFrame | None, title: str) -> None:
    if boundaries is not None:
        boundaries.plot(ax=ax, edgecolor="black", facecolor="none", linewidth=0.3)
    ax.set_xlim(float(data.lon.min()), float(data.lon.max()))
    ax.set_ylim(float(data.lat.min()), float(data.lat.max()))
    ax.set_aspect("equal")
    ax.set_xlabel("Longitude (°)")
    ax.set_ylabel("Latitude (°)")
    ax.set_title(title, loc="left")


def _figure(n_rows: int, data: xr.DataArray) -> tuple[plt.Figure, np.ndarray]:
    ratio = float(data.lat.max() - data.lat.min()) / max(float(data.lon.max() - data.lon.min()), 1e-9)
    width = 10.0
    fig, axes = plt.subplots(
        n_rows, 1, figsize=(width, n_rows * 0.85 * width * ratio + 0.6), squeeze=False, layout="constrained"
    )
    return fig, axes[:, 0]


def plot_availability_share(
    share: dict[str, xr.DataArray],
    out_path: Path,
    land: xr.DataArray | None = None,
    boundaries: gpd.GeoDataFrame | None = None,
    title: str | None = None,
) -> Path:
    """
    Two maps, solar PV and wind: the available share of each pixel's area, on 0 to `SHARE_VMAX`.

    Land with a share of 0 is grey. With `land` given, that is every land pixel without available
    area; without it, every pixel of the share arrays with a share of 0.
    """
    first = next(iter(share.values()))
    fig, axes = _figure(len(share), first)
    norm = Normalize(vmin=0.0, vmax=SHARE_VMAX)
    mesh = None
    for ax, (tech, values) in zip(axes, share.items()):
        unavailable = values.fillna(0.0) <= 0.0
        if land is not None:
            unavailable = unavailable & land.reindex_like(values, method="nearest", fill_value=False)
        _grey_where(ax, unavailable)
        mesh = ax.pcolormesh(
            values.lon,
            values.lat,
            values.where(values > 0.0),
            cmap=cmc.batlow,
            norm=norm,
            shading="nearest",
            rasterized=True,
        )
        _frame(ax, values, boundaries, TECH_TITLES.get(tech, tech))
    assert mesh is not None, "plot_availability_share needs at least one technology"
    fig.colorbar(mesh, ax=list(axes), label="Available share of the pixel area", extend="max", shrink=0.6)
    axes[-1].legend(
        handles=[Patch(facecolor=UNAVAILABLE_COLOUR, label="No available land")], loc="lower left", frameon=True
    )
    if title:
        fig.suptitle(title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def variable_label(data: xr.DataArray) -> str:
    """`long_name (units)` from the variable's attributes, falling back to its name."""
    name = str(data.attrs.get("long_name", data.name))
    units = data.attrs.get("units")
    return f"{name} ({units})" if units and units != "1" else name


# File attributes that describe a result, in the order a title states them.
_DESCRIBING_ATTRS = (
    ("region", "{}"),
    ("investment_year", "investment year {}"),
    ("coverage_fraction", "coverage {:g}"),
    ("era5_weather_year", "weather year {}"),
)


def describe_dataset(ds: xr.Dataset) -> str:
    """A title from the file's own attributes: its `title`, or the attributes that describe a result."""
    if "title" in ds.attrs:
        return str(ds.attrs["title"])
    parts = []
    for key, form in _DESCRIBING_ATTRS:
        if key in ds.attrs:
            value = ds.attrs[key]
            parts.append(form.format(float(value) if "{:g}" in form else value))
    return ", ".join(parts)


def _decade_range(values: xr.DataArray) -> tuple[float, float]:
    """Log-scale limits: the decades around the 5th and 99.5th percentile of the positive values."""
    positive = values.values[np.isfinite(values.values) & (values.values > 0)]
    if positive.size == 0:
        return 1.0, 10.0
    low, high = np.percentile(positive, [5.0, 99.5])
    return 10.0 ** np.floor(np.log10(low)), 10.0 ** np.ceil(np.log10(max(high, low * 10)))


def plot_cost_and_quantity_maps(
    ds: xr.Dataset,
    out_path: Path,
    cost_var: str = "lcoe",
    quantity_var: str = "max_baseload_mw",
    boundaries: gpd.GeoDataFrame | None = None,
    title: str | None = None,
    cost_range: tuple[float, float] | None = None,
    quantity_range: tuple[float, float] | None = None,
) -> Path:
    """
    A cost map above a quantity map, for any two variables on `(lat, lon)`: by default the LCOE
    above the capacity potential, and equally an LCOH above a hydrogen potential.

    Labels come from each variable's `long_name` and `units`, the title from the file's attributes
    (`describe_dataset`) unless `title` is given. The cost scale runs from 0 to the 98th percentile
    unless `cost_range` is given. The quantity uses a log scale, because a potential spans orders
    of magnitude between pixels. A quantity of 0 (the land cannot hold the design) is grey.
    """
    cost = ds[cost_var]
    quantity = ds[quantity_var]
    if cost_range is None:
        finite = cost.values[np.isfinite(cost.values)]
        cost_range = (0.0, float(np.percentile(finite, 98.0)) if finite.size else 1.0)
    fig, (ax_cost, ax_quantity) = _figure(2, cost)

    mesh = ax_cost.pcolormesh(
        cost.lon, cost.lat, cost, cmap=cmc.batlow, norm=Normalize(*cost_range), shading="nearest", rasterized=True
    )
    fig.colorbar(mesh, ax=ax_cost, label=variable_label(cost), extend="max", shrink=0.8)
    _frame(ax_cost, cost, boundaries, str(cost.attrs.get("long_name", cost_var)))

    _grey_where(ax_quantity, quantity == 0.0)
    mesh = ax_quantity.pcolormesh(
        quantity.lon,
        quantity.lat,
        quantity.where(quantity > 0.0),
        cmap=cmc.lajolla,
        norm=LogNorm(*(quantity_range or _decade_range(quantity)), clip=True),
        shading="nearest",
        rasterized=True,
    )
    fig.colorbar(mesh, ax=ax_quantity, label=variable_label(quantity), extend="both", shrink=0.8)
    _frame(ax_quantity, quantity, boundaries, str(quantity.attrs.get("long_name", quantity_var)))
    ax_quantity.legend(
        handles=[Patch(facecolor=UNAVAILABLE_COLOUR, label="Land cannot hold the design")],
        loc="lower left",
        frameon=True,
    )
    fig.suptitle(title if title is not None else describe_dataset(ds))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path
