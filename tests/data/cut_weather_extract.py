"""
Cut the weather extract for the tests out of BOA's 2024 EUROPE stores.

    uv run python tests/data/cut_weather_extract.py --from <data root> --to tests/data

Reads the two stores from `<data root>/inputs/cds-2024/cds-zarr/` and writes stores of the same
names to `<to>/cds-2024/cds-zarr/`. Each holds the four by four grid that two blocks of two by
two cells span; the cells outside the blocks hold no data. Values, data types, codec and
attributes are the source's own. Only the chunks change: the profile store gets one chunk per
block. Running the script again writes the same bytes.
"""

import argparse
from pathlib import Path
from typing import cast

import numpy as np
import zarr

INPUT_SET = "cds-2024"
STORES = ("pv_and_wind_potential_EUROPE_2024_025_deg.zarr", "max_capacity_EUROPE_2024_025_deg.zarr")
# (latitudes, longitudes) of central Spain and of the north-west coast of Spain.
BLOCKS = (((39.5, 39.75), (-3.0, -2.75)), ((43.5, 43.75), (-8.0, -7.75)))


def positions(axis: np.ndarray, values: tuple[float, ...]) -> list[int]:
    """Where each value sits on a coordinate axis, which must hold it exactly once."""
    found = [np.flatnonzero(axis == value) for value in values]
    if any(len(hit) != 1 for hit in found):
        raise ValueError(f"{values} do not each appear exactly once on the axis")
    return [int(hit[0]) for hit in found]


def cut_store(source: Path, target: Path) -> None:
    """Copy one store's blocks array by array, so nothing but the chunk shape is chosen here."""
    src = zarr.open_group(source, mode="r")
    y, x = np.asarray(src["y"]), np.asarray(src["x"])
    rows = np.array(sorted(i for lats, _ in BLOCKS for i in positions(y, lats)))
    cols = np.array(sorted(j for _, lons in BLOCKS for j in positions(x, lons)))
    inside = np.zeros((len(rows), len(cols)), dtype=bool)
    for lats, lons in BLOCKS:
        inside[np.ix_(np.isin(rows, positions(y, lats)), np.isin(cols, positions(x, lons)))] = True

    dst = zarr.open_group(target, mode="w", zarr_format=2)
    dst.attrs.update(src.attrs.asdict())
    for name, array in src.arrays():
        dims = cast(list[str], array.attrs["_ARRAY_DIMENSIONS"])
        data = np.asarray(
            array.get_orthogonal_selection(tuple(rows if d == "y" else cols if d == "x" else slice(None) for d in dims))
        )
        if dims[-2:] == ["y", "x"]:
            data[..., ~inside] = np.nan
        # Each block takes one half of each axis, so a two by two chunk holds one block or no
        # data at all, and zarr does not write a chunk with no data.
        chunks = (data.shape[0], 2, 2) if dims == ["time", "y", "x"] else data.shape
        out = dst.create_array(
            name,
            shape=data.shape,
            chunks=chunks,
            dtype=array.dtype,
            fill_value=array.fill_value,
            compressors=array.compressors,
            filters=array.filters,
            attributes=array.attrs.asdict(),
            chunk_key_encoding={"name": "v2", "separator": "."},
        )
        out[...] = data
    zarr.consolidate_metadata(target, zarr_format=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="source", type=Path, required=True, help="BOA data root holding the stores")
    parser.add_argument("--to", dest="target", type=Path, required=True, help="folder that receives the extract")
    args = parser.parse_args()
    for store in STORES:
        cut_store(args.source / "inputs" / INPUT_SET / "cds-zarr" / store, args.target / INPUT_SET / "cds-zarr" / store)


if __name__ == "__main__":
    main()
