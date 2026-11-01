# Weather extract for the tests

`cds-2024/cds-zarr/` holds the two EUROPE stores of the Baseload Optimisation Atlas (BOA) for weather year 2024, cut down to two blocks of two by two cells. It gives the tests a year of real weather small enough to keep in the repository: some read its hourly capacity factors directly, others copy it into a data root as input set `cds-2024` and run BOA's region build, query and point mode on it.

| block | latitudes | longitudes |
|---|---|---|
| central Spain | 39.5° N, 39.75° N | 3.0° W, 2.75° W |
| north-west coast of Spain | 43.5° N, 43.75° N | 8.0° W, 7.75° W |

- **`pv_and_wind_potential_EUROPE_2024_025_deg.zarr`** holds the hourly capacity factors of solar photovoltaic and onshore wind power.
- **`max_capacity_EUROPE_2024_025_deg.zarr`** holds the capacity each cell can take, which BOA computes from the cell's area and a fixed density per technology.

The extract takes 366,729 bytes in 35 files.

## Run the tests that need a data root

The region build, the query and point mode also need the cost data and the country grid that `boa-data-prepare` installs. The fixture `extract_data_root` in `tests/conftest.py` copies those two folders of a prepared data root, and the extract, into a temporary folder, so the tests never write to the data root itself. Build a data root in an empty folder, then point the tests at it:

```bash
BOA_DATA_ROOT=<folder> uv run boa-data-prepare
BOA_TEST_DATA_ROOT=<folder> uv run pytest
```

Without `BOA_TEST_DATA_ROOT` those tests skip.

## Trace the data to its source

The capacity factors come from the Copernicus Climate Change Service (C3S): "Global climate and energy indicators from 1950 to present derived from reanalysis", dataset `sis-energy-global-reanalysis`, digital object identifier (DOI) [10.24381/3bb607bd](https://doi.org/10.24381/3bb607bd). The dataset derives them from ERA5, the global reanalysis of the European Centre for Medium-Range Weather Forecasts (ECMWF). BOA's `boa-cds-prepare --weather_year 2024` built the source stores from the dataset's 2024 files. The capacity store holds no Copernicus data.

## Reuse the data under its licence

The data is under Creative Commons Attribution 4.0 International (CC BY 4.0), as the dataset's catalogue entry states: <https://creativecommons.org/licenses/by/4.0/>.

## Credit the data when you publish it

Copernicus asks anyone who publishes modified Copernicus data to credit it and to state a disclaimer. ECMWF's guidance on [acknowledging data from the Climate Data Store](https://confluence.ecmwf.int/spaces/CKB/pages/197704114/How+to+acknowledge+and+cite+a+Climate+Data+Store+CDS+catalogue+entry+and+the+data+published+as+part+of+it) gives the credit as "[Generated using/Contains modified] Copernicus Climate Change Service information [year]", followed by the disclaimer. For this extract:

> Contains modified Copernicus Climate Change Service information 2026. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains.

The year is 2026, when Nikita Jesaibegjans downloaded the source files and cut the extract.

## Compare the extract with BOA's stores

- **Cut.** Each store keeps only the four by four grid of cells that the two blocks span. The eight cells outside the blocks hold no data, so they read as not a number (NaN).
- **Rechunked.** The profile store holds one chunk per block, where BOA's own store holds 12 by 12 cells per chunk. The capacity store keeps one chunk per array, as BOA's does.
- **Unchanged.** Every value in the blocks is bit-identical to BOA's stores, and so are the time axis, the data types, the codec (Blosc with LZ4) and the attributes.

## Cut the extract again

```bash
uv run python tests/data/cut_weather_extract.py --from <data root> --to tests/data
```

`<data root>` is a BOA data root whose `inputs/cds-2024/cds-zarr/` holds the 2024 stores, as `boa-cds-prepare --weather_year 2024` builds them. The script writes the same bytes on every run, so cutting again from the same stores reproduces the committed files.
