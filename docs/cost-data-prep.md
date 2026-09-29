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
| `RES OPEX` | `region` (`World`, or an `irena region` that overrides it), `tech`, `opex` |
| `Cost of capital` | `code` (ISO-3), `tech` (only `Renewables` rows are used), `cost of capital` |
| `Country mapping` | `code` (ISO-3, unique), `irena region` (rows without one are skipped) |

`tech` takes `Solar PV`, `Onshore wind` or `Battery`. CAPEX is read for the investment year
only: every lifetime equals the 25-year investment horizon, so no replacement is bought.

## Units, fallbacks and checks

### Units

The loaders assume fixed units. The `unit` columns are for readers; nothing checks them, so a
CAPEX sheet in USD/MW would give costs 1,000 times too high.

| Value | Unit | How BOA uses it |
|---|---|---|
| CAPEX, `Solar PV` and `Onshore wind` | USD/kW (2024 USD in v0.1) | × 1,000, to USD/MW |
| CAPEX, `Battery` | USD/kWh | × 1,000, to USD/MWh |
| `opex` | fraction of CAPEX per year (0.01 = 1%) | charged every year of the lifetime, discounted |
| `cost of capital` | fraction (0.05 = 5%) | the discount rate |

### How a country gets its costs

**CAPEX**, per technology; the first match wins:

1. its province's row, when the country is split into provinces: a `subregion code` such as
   `CHN:CN-HB` (an ISO 3166-2 first-order unit);
2. its country's row: a bare ISO-3 in `subregion code`, which overrides the region for that
   country;
3. its `irena region` row, spelled as in Country mapping;
4. otherwise the full series of the **costliest region**: the `irena region` with the highest
   CAPEX summed over all technologies and years, among the regions with a row for this
   technology (ties go to the first name alphabetically). Each such fill logs a
   `[CAPEX FALLBACK]` warning naming the region.

A country with province rows is split: pixels in an authored province use its row, and the
rest of the country uses the country's row, or else its region's.

The year columns don't have to be consecutive. Years between two columns (e.g. in a 5-yearly
sheet) are interpolated linearly along each row, and the log lists them. An investment year
before the first column is an error; years after the last column keep its value.

**OPEX:** the country's `irena region` row for the technology, else the `World` row.

**Cost of capital:** the country's `Renewables` row. A country without one gets the highest
cost of capital among the countries in Country mapping, with a `[COST OF CAPITAL FALLBACK]`
warning. Provinces share their country's rate.

**Countries without costs:** a pixel whose country isn't in Country mapping, or has no
`irena region`, is priced at run time with the global average: the mean over all cost keys,
per technology, logged as `[FALLBACK]`. Åland uses Finland's costs and South Georgia
Argentina's. v0.1 leaves out Antarctica, Bouvet Island, South Georgia and St Helena, and all
but South Georgia lie outside every region box, so with v0.1 only 12 land pixels without a
country use the global average.

Surrounding spaces, including non-breaking ones, are ignored in every key column:
`irena region`, `code`, `tech`, `subregion code` and `region`.

### What stops `boa-data-prepare`

`boa-data-prepare` checks the workbook, then builds one year's costs from it in a temporary
folder, before copying anything. A failure stops it and keeps the scenario's previous
workbook. It stops on:

- a missing sheet or column, or no year columns in RES CAPEX projections;
- a duplicate `code` in Country mapping, or among the `Renewables` rows of Cost of capital;
- Western Sahara coded `WES` instead of `ESH`;
- an unknown `tech` label in RES CAPEX projections or RES OPEX;
- a duplicate (`irena region` or `subregion code`, `tech`) row in RES CAPEX projections;
- a RES CAPEX projections row with some blank or non-numeric year cells (a row left blank
  entirely is allowed, and falls through to the next level above);
- in RES OPEX: a `region` that is neither `World` nor an `irena region` from Country mapping,
  a duplicate (`region`, `tech`) row, a blank or non-numeric `opex`, or a technology without
  a `World` row;
- anything else that breaks the one-year build.

`boa-run` also rejects a province key that isn't a first-order unit in the NE admin-1
shapefile, and a country split into provinces when that shapefile is missing.

### The cost cache

`costs/<scenario>/cache_costs/` holds one file per investment year. Each records the sha256
of the workbook it was built from and the loader's `COST_CACHE_VERSION`, and is rebuilt when
either differs, so a run never uses costs from an older workbook or loader. Bump
`COST_CACHE_VERSION` in `boa/inputs/costs.py` with any change that alters the numbers a valid
workbook produces; refactors, log messages and new checks don't need it.

### Starting a custom scenario

1. Copy `costs/default/boa_cost_data.xlsx`, a byte-identical copy of the package workbook.
2. Edit the copy, keeping the sheet and column names.
3. Prepare it: `boa-data-prepare --input-file my_costs.xlsx --scenario my_scenario`.
4. Run with it: `boa-run ... --cost-input my_scenario`.

Only the workbook is copied into the scenario. Its `source.json` records where it came from:
the file path, or for the default the package's URL, version and sha256. The package's
`boa-cost-data.json` (sheet dates, units and rounding) stays in the package.
