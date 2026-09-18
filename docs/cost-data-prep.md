# Cost-side and geo data preparation

`boa-data-prepare` (a steelo-side command) prepares everything a run needs besides the
weather-side stores: the static geo data plus a costs scenario extracted from a master
excel workbook:

```bash
boa-data-prepare                                              # S3 master-input package -> costs/default/
boa-data-prepare --input-file wb.xlsx --scenario cheap_renewables
boa-data-prepare --scenario cheap_renewables --year_start 2025 --year_end 2050 --year_step 5
```

- `--input-file` — source workbook; omitted → the `master-input` DataManager package (S3),
  the same source `steelo-data-prepare` uses. The workbook must contain the four sheets boa
  reads: RES CAPEX projections, RES OPEX, Cost of capital, Country mapping (a "missing
  sheet(s)" failure means the source predates them).
- `--scenario` — costs-set name (default `default`). A scenario is a whole hand-edited
  workbook variant; the extracted copy doubles as the provenance record of what a run used.
- `--year_start` / `--year_end` / `--year_step` — narrow the cost-cache years (defaults:
  earliest/latest year column in the RES CAPEX projections sheet, step 1).

Geo side: the pinned Natural Earth shapefiles (1:50m map subunits, 1:10m admin-1) and the
ERA5 land-sea mask are installed from the `boa-data` DataManager package (S3), and the
per-pixel iso3 grid is built locally from the 1:50m shapefile (`geo/iso3_grid_builder.py`).
The shapefiles are pinned on S3 rather than fetched from naciscdn.org because Natural Earth
releases change polygons, which would silently change the iso3 grid.

The first run downloads ~16 MB and builds the iso3 grid in about a minute; re-runs finish
in seconds. Re-running is an idempotent upsert: files already present are kept, unchanged
cost data is a no-op; changed cost data replaces the workbook and rebuilds the scenario's
cost cache. The iso3 grid carries a fingerprint of its source shapefile and is rebuilt
automatically if the NE 1:50m shapefile ever changes.

Data lands under the boa data root (`$BOA_DATA_ROOT` → `$STEELO_HOME/boa` → `~/.steelo/boa`):

```
data/
├── ne_50m_admin_0_map_subunits/      NE 1:50m shapefile (source of the iso3 grid)
├── ne_10m_admin_1_states_provinces/  NE 1:10m admin-1 shapefile (sub-national cost keys)
├── lsm_025_deg.nc                    ERA5 0.25 deg land-sea mask
├── iso3_grid.nc                      per-pixel ISO3 grid, built locally
└── cds/                              raw CDS NetCDFs (+ global_zarr/ build cache)
inputs/<set>/                         e.g. cds-2024, tagged by weather year
├── cds-zarr/                         live profile + max-capacity stores the model reads
└── staging/                          freshly built stores (transient; emptied on install)
inputs/cds-<year>/cache_frontiers/    frontier cache, built by boa-run; keyed on the
                                       weather year alone, shared across every land-
                                       availability layer set built on that weather
costs/<scenario>/
├── boa_cost_data.xlsx    the four extracted sheets (RES CAPEX projections, RES OPEX,
│                         Cost of capital, Country mapping)
├── source.json           scenario, prepared_at, source workbook path + sha256
└── cache_costs/          cost_of_renewables_<year>_investment_year.nc, one per year
```

Run against a scenario with `boa-run ... --cost-input <scenario>`.

For the exact sheet/column contract `boa-data-prepare` must produce, see
`../HANDOFF_cost_schema_contract.md` — publishing it as a standalone, machine-checkable doc
is still an open task.
