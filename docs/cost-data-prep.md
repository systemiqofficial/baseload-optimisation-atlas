# Cost-side and geo data preparation

`boa-data-prepare` prepares everything a run needs besides the weather-side stores: the
static geo data plus a costs scenario from a cost workbook:

```bash
boa-data-prepare                                              # pinned cost data -> costs/default/
boa-data-prepare --input-file wb.xlsx --scenario cheap_renewables
boa-data-prepare --input-file wb.xlsx --scenario cheap_renewables --year_start 2025 --year_end 2050 --year_step 5
```

- `--input-file` — a cost workbook for a custom scenario, e.g. a hand-edited copy of
  `boa-cost-data-v0.1.xlsx`. Without it, the pinned `boa-cost-data` package is downloaded
  from steelo-data (see below). Either way the workbook is checked against the layout below,
  smoke-tested with BOA's cost loader and copied unchanged.
- `--scenario` — costs-set name (default `default`). A scenario is a whole hand-edited
  workbook variant; the copy doubles as the provenance record of what a run used.
- `--year_start` / `--year_end` / `--year_step` — narrow the cost-cache years (defaults:
  earliest/latest year column in the RES CAPEX projections sheet, step 1).

Cost side: the default cost workbook is the `boa-cost-data` package on steelo-data, pinned
by URL and sha256 in `boa/config/data_packages.py`. It holds the workbook and
`boa-cost-data.json`, which records each sheet's last-changed date, columns, units and
rounding. The package is ~36 KB and is fetched on every run without `--input-file`.

Geo side: the pinned Natural Earth shapefiles (1:50m map subunits, 1:10m admin-1) and the
ERA5 land-sea mask are installed from the `boa-core-data` package on steelo-data, pinned by
URL and sha256 in `boa/config/data_packages.py`. Its `boa-core-data.json` records each
source's version, licence, attribution and file hashes. The per-pixel iso3 grid is built
locally from the 1:50m shapefile (`geo/iso3_grid_builder.py`).
The shapefiles are pinned on S3 rather than fetched from naciscdn.org because Natural Earth
releases change polygons, which would silently change the iso3 grid.

The first run downloads ~16 MB and builds the iso3 grid in about a minute; re-runs finish
in seconds. Re-running is an idempotent upsert: the core data is downloaded again only when
the pinned version differs from the installed one, an unchanged workbook (same sha256) is a
no-op, and a changed one replaces the copy and rebuilds the scenario's cost cache. The iso3
grid carries a fingerprint of its source shapefile and is rebuilt automatically if the NE
1:50m shapefile ever changes.

Data lands under the boa data root (`$BOA_DATA_ROOT` → `~/.boa`):

```
data/
├── ne_50m_admin_0_map_subunits/      NE 1:50m shapefile (source of the iso3 grid)
├── ne_10m_admin_1_states_provinces/  NE 1:10m admin-1 shapefile (sub-national cost keys)
├── lsm_025_deg.nc                    ERA5 0.25 deg land-sea mask
├── boa-core-data.json                core data version + provenance
├── iso3_grid.nc                      per-pixel ISO3 grid, built locally
└── cds/                              raw CDS NetCDFs (+ global_zarr/ build cache)
inputs/<set>/                         e.g. cds-2024, tagged by weather year
├── cds-zarr/                         live profile + max-capacity stores the model reads
└── staging/                          freshly built stores (transient; emptied on install)
inputs/cds-<year>/cache_frontiers/    frontier cache, built by boa-run; keyed on the
                                       weather year alone, shared across every land-
                                       availability layer set built on that weather
costs/<scenario>/
├── boa_cost_data.xlsx    the cost workbook, copied unchanged
├── source.json           scenario, prepared_at, source workbook (+ package version, URL,
│                         sha256 when downloaded) and the workbook's sha256
└── cache_costs/          cost_of_renewables_<year>_investment_year.nc, one per year
```

Run against a scenario with `boa-run ... --cost-input <scenario>`.

## The cost workbook

The workbook's sheet and column names are the contract; the loaders read them as they are,
and `COST_WORKBOOK_COLUMNS` in `boa/inputs/costs.py` lists the columns `boa-data-prepare`
checks for. Other columns (e.g. `country`, `unit`, `cost of debt`) are kept for readers and
ignored by BOA.

| Sheet | Columns BOA reads |
|---|---|
| `RES CAPEX projections` | `irena region`, `tech`, the year columns (numeric headers, e.g. `2025`), and optionally `subregion code` (a sub-national cost key such as `CHN:CN-HB`) |
| `RES OPEX` | `region`, `tech`, `opex` (one global row per technology) |
| `Cost of capital` | `code` (ISO-3), `tech` (only `Renewables` rows are used), `cost of capital` |
| `Country mapping` | `code` (ISO-3, unique), `irena region` (rows without one are skipped) |

`tech` takes `Solar PV`, `Onshore wind` or `Battery`. CAPEX is read for the investment year
only: every lifetime equals the 25-year investment horizon, so no replacement is bought.
