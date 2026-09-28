# CDS input-data pipeline

`boa-cds-prepare` builds the profile + max-capacity Zarr stores for one input set from raw
CDS NetCDFs (dataset sis-energy-global-reanalysis) and installs them into
`inputs/<set>/cds-zarr/`, the live dir the model reads:

```bash
boa-cds-prepare --weather_year 2024            # build + install what is missing -> inputs/cds-2024/
boa-cds-prepare --weather_year 2024 --force    # rebuild everything
boa-cds-download --year 2025                   # fetch raw NetCDFs for another year
```

The input set is tagged automatically as `cds-<weather_year>`; pass `--inputs` only to
override. Re-running is idempotent: regions whose stores already exist in the live dir are
reused; `--force` rebuilds them. If the raw files for the requested year are missing, prepare
stops and names the `boa-cds-download` command to run (which needs a CDS account, `~/.cdsapirc`
with the dataset licence accepted, and `uv sync --extra cds` for the client). That is the
preferred route; for a re-published year it also offers `--use-republished` (see
[Re-published years](#re-published-years)). Raw files land
in `data/cds/` (~6 GB per year); the convert stage builds a shared global intermediate at
`data/cds/global_zarr/` (~12 GB per year, deletable — it rebuilds in about a minute), after
which each region converts in seconds. Max-capacity stores default to geometry-only (pixel
area x density); pass `--layers lulc,cds_exclusion` to `boa-cds-prepare` for the layered
land-availability ceiling instead — it lands in its own input set (e.g.
`cds-2024-lulc+excl`) rather than overwriting the geometry-only stores.

Already have the raw data (from another machine or an earlier checkout)? Drop the
*extracted* per-year directories — 12 monthly NetCDFs each — into `data/cds/` under the
boa data root (`$BOA_DATA_ROOT` → `~/.boa`) and prepare will
use them without downloading:

```
data/cds/
├── cds_solar_cf_ic6hh135_0_25_degree_2024/        *.nc, one per month
└── cds_wind_onshore_cf_ic6hh135_0_25_degree_2024/ *.nc, one per month
```

A zip dropped on its own is not enough: the downloader treats an existing zip as
already-handled and never extracts it, so unzip into the sibling directory named after the
zip stem. `boa-cds-download` also skips any (technology, year) whose extracted directory
already exists, so partial reuse works too.

## Re-published years

Downloading from CDS with your own account is preferred. As a fallback, the years in
`PUBLISHED_CF_SHA256` ([src/boa/cds/spec.py](../src/boa/cds/spec.py)) are re-published on the
public `steelo-data` bucket and need no CDS account:

```bash
boa-cds-prepare --weather_year 2024 --use-republished
```

```
https://steelo-data.s3.eu-north-1.amazonaws.com/boa-standalone-input-data/cds-capacity-factors-<year>.zip
```

Each zip (about 6.6 GB) holds the year's two extracted folders plus
`cds-capacity-factors-<year>.json`, which records the CDS request, when the files were
downloaded, and a sha256 per file. With `--use-republished`, `boa-cds-prepare` downloads the zip
only if the raw files are missing, checks it against its pinned sha256, extracts it into
`data/cds/` and deletes it.

The data is Copernicus Climate Change Service information, licensed CC-BY 4.0. Redistributing
it, or publishing results derived from it, needs the attribution recorded in the JSON.
