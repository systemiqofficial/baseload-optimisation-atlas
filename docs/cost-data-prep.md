# Cost-side and geo data preparation

This page tells you how to prepare a cost set and the geo data for a run, which workbook layout
BOA reads, and how to build the core cost set.

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
rounding. The package (~36 KB) is installed unchanged in `data/boa-cost-data/`, next to an
`installed.json` recording the zip's URL, version and sha256, and is downloaded again only
when the pinned sha256 changes. Scenarios copy their workbook from there.

Geo side: the pinned Natural Earth shapefiles (1:50m map subunits, 1:10m admin-1) and the
ERA5 land-sea mask are installed from the `boa-core-data` package on steelo-data, pinned by
URL and sha256 in `boa/config/data_packages.py`, and kept unchanged in `data/boa-core-data/`
like the cost package. Its `boa-core-data.json` records each source's version, licence,
attribution and file hashes. The per-pixel iso3 grid is built
locally from the 1:50m shapefile (`geo/iso3_grid_builder.py`).
The shapefiles are pinned on S3 rather than fetched from naciscdn.org because Natural Earth
releases change polygons, which would silently change the iso3 grid.

The first run downloads ~16 MB and builds the iso3 grid in about a minute; re-runs finish
in seconds. Re-running is an idempotent upsert: the core and cost packages are downloaded again
only when the pinned sha256 differs from the installed zip's, an unchanged workbook (same sha256) is a
no-op, and a changed one replaces the copy and rebuilds the scenario's cost cache. The iso3
grid carries a fingerprint of the NE 1:50m shapefile and of `NE_TO_BOA` (the subunit-to-iso3
remap in `geo/iso3_grid_builder.py`), and is rebuilt automatically if either changes.

Data lands under the boa data root (`$BOA_DATA_ROOT` → `~/.boa`):

```
data/
├── boa-core-data/                    the pinned core package, unchanged:
│   ├── ne_50m_admin_0_map_subunits/      NE 1:50m shapefile (source of the iso3 grid)
│   ├── ne_10m_admin_1_states_provinces/  NE 1:10m admin-1 shapefile (sub-national cost keys)
│   ├── lsm_025_deg.nc                    ERA5 0.25 deg land-sea mask
│   ├── boa-core-data.json                core data provenance
│   └── installed.json                    the installed zip's version, URL and sha256
├── boa-cost-data/                    the pinned cost package, unchanged: its workbook,
│                                     boa-cost-data.json and installed.json
├── iso3_grid.nc                      per-pixel ISO3 grid, built locally
└── cds/                              raw CDS NetCDFs (+ global_zarr/ build cache, and
                                      cds-capacity-factors-<year>.json for a re-published year)
inputs/<set>/                         e.g. cds-2024, tagged by weather year
├── cds-zarr/                         live profile + max-capacity stores the model reads
└── staging/                          freshly built stores (transient; removed once installed)
inputs/cds-<year>/cache_frontiers/    frontier cache, built by boa-run; keyed on the
                                       weather year alone, shared across every land-
                                       availability layer set built on that weather
costs/<scenario>/
├── boa_cost_data.xlsx    the cost workbook, copied unchanged
├── source.json           scenario, prepared_at, source workbook, the workbook's sha256,
│                         and source_package when the workbook belongs to a cost package
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
| CAPEX, `Solar PV` and `Onshore wind` | USD/kW (2024 USD in `boa-cost-data` v0.1 and in the core set) | × 1,000, to USD/MW |
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
Argentina's. `boa-cost-data` v0.1 leaves out Antarctica, Bouvet Island, South Georgia and St Helena, and all
but South Georgia lie outside every region box, so with `boa-cost-data` v0.1 only 12 land pixels without a
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

1. Copy the package workbook, `data/boa-cost-data/boa-cost-data-v0.1.xlsx`.
2. Edit the copy, keeping the sheet and column names.
3. Prepare it: `boa-data-prepare --input-file my_costs.xlsx --scenario my_scenario`.
4. Run with it: `boa-run ... --cost-input my_scenario`.

Only the workbook is copied into the scenario. Its `source.json` records where it came from:
the file path and the workbook's sha256. When the workbook belongs to a cost package, it also
records `source_package`: the package name, version, workbook name and workbook sha256 (and the
URL and zip sha256 of the pinned package). An `--input-file` workbook belongs to a package when a
package JSON in the same folder lists its sha256, for example `boa-cost-data-core.json` next to
the core workbooks. A second prepare of an unchanged workbook updates `source.json` if the
origin differs.
The package's `boa-cost-data.json` (sheet dates, units, rounding and notes) stays with the
package in `data/boa-cost-data/`; it names the workbook `boa-cost-data-v<version>.xlsx`, and
its `workbook.sha256` matches a scenario's `boa_cost_data.xlsx` prepared from it.

## Building the core cost set

The core cost set is made from pinned public sources (see [Cost data](cost-data.md)). Run these
commands from a checkout of the BOA repository:

```bash
boa-sources-fetch                                   # download the sources into <data root>/sources/
python scripts/cost/build_core.py --out-dir build/cost-core
boa-data-prepare --input-file build/cost-core/boa-cost-data-core-steps-v0.1.xlsx --scenario core-steps
boa-run ... --cost-input core-steps
```

The build writes one workbook for each WEO scenario (`cps`, `steps`, `nze`). `core-steps` is the
name you give to the costs set in BOA. `boa-sources-fetch --list` shows which sources are on disk.
The build stops if a file is missing or its sha256 is not the pinned value.

The build reads three kinds of input:

| Input | Holds | Check it against |
|---|---|---|
| `scripts/cost/transcribed/*.csv` | Values typed from the PDF sources, in the layout of the source table | The page in the file header |
| `scripts/cost/rules.toml` | Our decisions: which WEO row a region follows, OECD regions, name aliases, the subregion table | — |
| The IRENA data file | Read by the script | The **Inputs** sheet of each workbook |
| The Natural Earth file | Read by the script | The `irena region` and `source` columns of the **Country mapping** sheet |

### Updating a source

1. In `src/boa/config/cost_sources.toml`, change the `url`, `sha256` and `accessed` of the
   source. Change its `tables` lines if the table numbers change.
2. Run `boa-sources-fetch <id>`.
3. For a PDF source, update its file in `scripts/cost/transcribed/` from the new pages.
4. Run the build and `pytest tests/test_cost_build_core.py`. These tests skip when the source
   files are not fetched. With `pypdf` installed, they compare the WEO Tables B.4 and B.5 with
   the PDF. They check that each `source` cell names a table in the registry.
5. Check Annex III and Table A1 against the PDF by hand. Compare the **Inputs** and
   **Country mapping** sheets with the source files.
