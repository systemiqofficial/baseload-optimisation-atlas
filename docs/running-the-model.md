# Running the model

This page shows how to run `boa-run`, how to select the weather set, the cost set and the run
label, how to rebuild a frontier cache, and how to reproduce a result. It also shows how to run the
whole chain with `boa-lcoe`. The last section lists the variables of the per-year output files. For
the concepts, see the [Overview](overview.md) and the [Methodology](methodology.md).

## Commands

`boa-run` computes all regions. The `point` command is the only exception: it computes one pixel.

```bash
boa-run --load-density 1.0 --coverage 0.95       # build missing caches, then query every year
boa-run build-cache                              # build the frontier caches only
boa-run query --start-year 2030 --end-year 2030  # per-year files from existing caches
boa-run point --lat 52.5 --lon 13.4              # one pixel; BOA finds the region
boa-run --weather-input cds-2023 --cost-input rev3 --dry-run  # check the inputs, run nothing
```

| Command | What it does | Options that are specific to it |
|---|---|---|
| `boa-run` | Checks the inputs. Builds the frontier cache of each region when it is missing or when it does not cover the cost mixes of the run. Then writes the per-year files for each year. | `--dry-run`, `--plots`, `--promote-lcoe` |
| `boa-run build-cache` | Builds the frontier caches. Writes no per-year file. It ignores `--load-density`. | `--force` |
| `boa-run query` | Writes the per-year files from existing frontier caches. It never builds a cache. | `--force`, `--plots`, `--promote-lcoe` |
| `boa-run point` | Computes one pixel. Writes no NetCDF file. | `--lat`, `--lon` |

All commands accept these options:

| Option | Meaning | Default |
|---|---|---|
| `--load-density` | The load density, in MW/km². | 1.0 |
| `--coverage` | The coverage target: a fraction larger than 0 and smaller than 1. | 0.85 |
| `--start-year`, `--end-year` | The first and the last investment year. | 2025, 2060 |
| `--frequency` | The number of years between two investment years. | 1 |
| `--verbose` | Writes more log lines. | off |

They also accept `--weather-input`, `--cost-input` and `--run` (see the next section). All commands
except `point` accept `--workers`: the number of worker threads. The value is an integer of 1 or
more, or a preset:

| Preset | Number of workers |
|---|---|
| `small` | About 25 % of the CPU cores |
| `normal` | About 50 % of the CPU cores |
| `fast` | The number of CPU cores minus 2 |

The default is `fast`. See the [Overview](overview.md) for the meaning of the load density and the
coverage.

BOA makes the list of investment years from `--start-year`, `--end-year` and `--frequency`. It
steps from the first year in steps of `--frequency` years. It rounds each year to the nearest
multiple of `--frequency`, and keeps the year only when it is in the range. Use a `--start-year`
that is a multiple of `--frequency`. Other values can give a repeated or a missing year. For example,
2025 to 2060 with a frequency of 10 gives the years 2040, 2040 and 2060.

A query does no dispatch simulation. It prices the designs that the frontier cache holds (see
[The query](methodology.md#the-query)).

### Single-point run

`boa-run point` finds the region of the location, and builds the frontier of this one pixel with
the costs of the pixel. It uses no frontier cache. It checks only that the cost workbook and the
weather year exist. It reads the profile store and the maximum-capacity store of the region of the
location. For each investment year, it reports the result in the log: the LCOE, the installation
cost and the three factors of the design.

For each year, `point` also writes PNG files to this directory:

```text
<root>/runs/<label>_<hash>/outputs/plots/single_point/cov<c>/<location>/
```

Here `<c>` is the coverage as a plain number (for example `cov0.85`), and `<location>` is
`lat_<lat>_lon_<lon>` with the coordinates rounded to two decimals, a point as an underscore, and
`neg` for a minus sign. The files are `<year>_<location>_time_series.png` (the solar and wind
capacity factors) and `<year>_<location>_state_of_charge.png` (the state of charge of the battery
in the optimal design). BOA writes the second file only when the pixel has the status 1.

## Select the weather set, the cost set and the run label

| Option | Selects | Default |
|---|---|---|
| `--weather-input` | The weather set: the profile stores under `<root>/inputs/<set>/`. BOA reads the weather year from the file names of the stores. You do not pass it. Use one weather set for each run label. | `cds-2024` |
| `--cost-input` | The cost set: the cost workbook under `<root>/costs/<set>/`. | `default` |
| `--run` | The run label: the name of the run. | The cost set |

`<root>` is `$BOA_DATA_ROOT`, or `~/.boa` when that variable is not set.

The run directory is `<root>/runs/<label>_<hash>`. The `<hash>` has four characters. It is a hash of
all search settings and of the technology lifetimes. A change to one of them gives a different
directory, so a run never mixes results from different settings. The same label with the same
settings always gives the same directory. `boa-promote-lcoe --run <label>` finds the directory
from the label.

Before BOA does any computation, it checks that the selected sets are complete. When a set is
incomplete, the error message gives the `boa-cds-prepare` or `boa-data-prepare` command to run.
`--dry-run` does only this check, and prints the directories that the run would use.

The files are in these places:

```text
<root>/inputs/cds-<weather year>/cache_frontiers/          frontier caches
<root>/runs/<label>_<hash>/run.json                        provenance of the run
<root>/runs/<label>_<hash>/outputs/wy<weather year>/<rho>MWkm2/cov<c>/nc/<REGION>/
        optimal_sol_wy<weather year>_<rho>MWkm2_cov<c>_<REGION>_<year>.nc
```

`<rho>` is the load density and `<c>` the coverage, written without dots (`01MWkm2`, `cov0p9`).
`<REGION>` is the name of a region, or `GLOBAL` for the combination of all regions. The frontier
cache directory depends on the weather year only. All cost sets, and all runs on the same weather
year, share it.

## Rebuild a frontier cache

One frontier cache serves each load density and each investment year. It depends on the weather
year, the region, the coverage target and the search settings. It also depends on the costs in one
way: through the cost mixes that it was built for, which are its [anchors](glossary.md#anchor) (see
[Build once, price many](overview.md#build-once-price-many) and
[Cost anchors](methodology.md#cost-anchors)).

- **The cost mix check.** `boa-run` and `boa-run build-cache` compare the cost mixes that a stored
  cache records with the cost mixes of all cost keys. They do this for the investment years that
  `--start-year`, `--end-year` and `--frequency` give, not for every year in the range. When the
  cache covers the cost mixes, BOA uses the cache as it is. When it does not, BOA builds the cache
  again for the old cost mixes and the new ones. A new cost set, or more years, makes one
  rebuild, and the cache then covers them.
- **`boa-run query` does no cost mix check.** It reads the cache that it finds at the cache path.
  The path contains the weather year, the region, the coverage target and the search settings. It
  contains neither the cost set nor the years. A query can use a cache that was built for other
  costs or other years, and BOA gives no warning. Run `boa-run build-cache` with the same cost set
  and years before you run `boa-run query`.
- **A query needs a cache.** When no cache exists, `boa-run query` stops with an error. The
  coverage is part of the cache path. A query with another `--coverage` finds no cache, and stops
  with the same error.
- **A cache at the limit.** When a cache holds the largest number of cost mixes that it can hold
  (`max_anchors`, 32 by default), BOA uses it as it is, with a warning, because a rebuild cannot
  add a cost mix.
- **A cache from another cache version.** `boa-run` and `build-cache` build it again. `query`
  stops with an error that names `boa-run build-cache`.
- **Force.** `boa-run build-cache --force` builds each cache again, also when it covers
  the cost mixes of the run. `boa-run` has no `--force` option.
- **After a rebuild, use `boa-run query --force`.** A command that finds a per-year file skips the
  year. A per-year file does not record the build time, the cache version or the cost mixes that its
  cache was built for. A rebuild does not change the existing per-year files, and old and new
  results can be in one run directory. Run `boa-run query --force` with the same scenario options
  to write them again.

A rebuild for more cost mixes can change which designs the cache holds, and therefore the LCOE of
an earlier cost set or year. See
[Reuse of the frontier cache](known-limitations.md#reuse-of-the-frontier-cache).

## Plots

`boa-run` and `boa-run query` make map PNGs only with `--plots`. The maps show `lcoe`,
`solar_factor`, `wind_factor` and `battery_factor`, for each region and for GLOBAL. They are in
`<root>/runs/<label>_<hash>/outputs/wy<weather year>/<rho>MWkm2/cov<c>/plots/<REGION>/`. The log
line "Regridding regional datasets onto the global grid" appears when BOA combines the regions into
the GLOBAL file. It appears with or without `--plots`. The `point` command always makes its plots
(see [Single-point run](#single-point-run)).

## Capacity ceiling

BOA does not apply the capacity ceiling. Each query reports the unconstrained optimum for the
coverage target, for each load density, and writes a warning to the log. Each per-year file records
`capacity_ceiling_applied = 0`: BOA did not apply the capacity ceiling. See
[The capacity ceiling is not applied](known-limitations.md#the-capacity-ceiling-is-not-applied).

## Reproduce a result

Each per-year file and the `run.json` of its run directory record the settings of the run.

1. Open the per-year file. Read `era5_weather_year`, `coverage_fraction`,
   `load_density_mw_km2` and `investment_year`. The directory name above `outputs/` is
   `<label>_<hash>`.
2. Open `<root>/runs/<label>_<hash>/run.json`. The entry `provenance` gives these values:
    - `input_set`: the weather set.
    - `cost_set`.
    - `input_data_sha256`: the sha256 of the cost workbook.
    - `availability_signature`: the signature of the maximum-capacity stores. It can be null.
    - `boa_version`.
    - `search_params`.
    - `lifetimes`: the technology lifetimes.
    - `era5_data_year`: the weather year.

    Each entry in `invocations` gives the command, `argv`, `git_sha` and `parameters`. The
    `git_sha` is the commit of the BOA installation. It is null when BOA cannot find it.
    The `parameters` are the resolved settings, with the defaults: the load density, the coverage,
    `workers` (not for `point`), and `lat` and `lon` (only for `point`). For `run`, `query` and
    `point`, they also include the list `years`. For `build-cache`, they do not include the years.
    Read the years from `argv`. A default value is not in `argv`: when `argv` has no year option,
    BOA used the default years.
3. Install the same BOA version, and prepare the same weather set and cost set. Compare the
   sha256 of your cost workbook with `input_data_sha256`.
4. Run the same command with the same `--weather-input`, `--cost-input`, `--run`, `--coverage`,
   `--load-density` and years.

Before BOA adds outputs to a run directory, it compares the current provenance with the `provenance`
in `run.json`. It compares `input_set`, `cost_set`, `input_data_sha256`, `availability_signature`,
`boa_version`, `search_params`, `lifetimes` and `era5_data_year`. When one of them differs, BOA
stops with a `RuntimeError` that lists the differences. BOA also refuses a `run.json` of an older
schema version. Use a new `--run` label in these cases.

The cost mixes that a cache covers depend on the years of the run and on the earlier runs that used
the same cache (see above). To get the same designs, start with no frontier cache for the weather
year and coverage, and use the same years.

## Hand the LCOE to the steel simulation

The steel simulation reads one variable of a run: `lcoe`. `boa-promote-lcoe` combines the per-year
files of each scenario in a run into one file:

```bash
boa-promote-lcoe --run my_run                               # every scenario in a finished run
boa-run --load-density 1.0 --coverage 0.95 --promote-lcoe   # or at the end of a run
```

The output is `<root>/lcoe-only/<label>_<hash>/optimal_lcoe_wy<weather year>_<rho>MWkm2_cov<c>_<first>_<last>.nc`.
Promotion stops with an error when the years disagree on `cost_key`, on `status` or on a scenario
attribute. The layout of the promoted file is a contract: see
[The promoted LCOE file](promoted-lcoe-file.md).

`boa-promote-lcoe --run <label>` fails when the label matches more than one directory
`<label>_<hash>`. In that case, pass the full directory name. The default label is `default`.

BOA does not apply the capacity ceiling, and the promoted file carries `capacity_ceiling_applied =
0`. Promotion requires the attribute `capacity_ceiling_applied` in the per-year files, but it does
not check its value. See
[The capacity ceiling is not applied](known-limitations.md#the-capacity-ceiling-is-not-applied).
A promoted file also depends on the state of the frontier cache when the per-year files were
written (see [Reuse of the frontier cache](known-limitations.md#reuse-of-the-frontier-cache)).

## Run the whole chain with `boa-lcoe`

`boa-lcoe` runs these steps in this order, and passes on only the options that you give:

1. `boa-data-prepare`: the cost set. The default is the pinned cost data.
2. `boa-cds-prepare --use-republished`: the weather data of the weather year. When the raw data is
   missing, BOA downloads the re-published copy, so you need no CDS account. The input set is
   `cds-<weather year>`, with no availability layers.
3. `boa-run --promote-lcoe`, once for each value of `--coverage`.

```bash
boa-lcoe --coverage 0.85 0.95                         # one boa-run for each coverage
boa-lcoe --input-file costs.xlsx --scenario mycase    # a custom cost workbook, with its own name
boa-lcoe --run smoke --start-year 2025 --end-year 2026 --dry-run
boa-lcoe --like <promoted file> --run rerun           # rerun the run behind a promoted file
```

The options are `--input-file` and `--scenario` (the cost set), `--weather-year` (default 2024),
`--run`, `--coverage` (one or more values), `--start-year`, `--end-year`, `--frequency`,
`--load-density` and `--workers`. The last five go to `boa-run`. A custom workbook needs a
`--scenario` name of its own, so that it does not replace the `default` cost set.

- **`--dry-run`** prints the command of each step. It skips the two preparation steps, and runs
  `boa-run --dry-run`.
- **`--like FILE`** reruns a promoted LCOE file. BOA reads the run label, the cost set, the
  weather year, the coverage, the load density and the years from the file. It uses these values
  for each option that you do not give. It stops when your cost workbook is not the workbook that
  made the file. It warns when the file comes from another BOA version.
- **Run directory check.** `boa-lcoe` stops before the first step when the run directory was made
  by another BOA version, for another cost set, on another weather set, or from another cost
  workbook. Use a new `--run` label.
- **Stop.** `boa-lcoe` stops at the first step that fails, with the exit code of that step.

When all steps succeed, the last two lines of the standard output are `BOA_RUN=<label>_<hash>` and
`BOA_RUN_DIR=<path>`. They give the name of the run and its directory of promoted files under
`<root>/lcoe-only/`.

## Per-year output files

A per-year file is a NetCDF file for one region and one investment year. The GLOBAL file combines
the per-year files of all regions for one investment year. It has one grid: latitude from −90 to
90 and longitude from −180 to 180, both in steps of 0.25 degrees. Each file has these variables on
the dimensions `lat` and `lon`.

| Variable | Type | Unit | Meaning |
|---|---|---|---|
| `lcoe` | float32 | USD/MWh | The levelised cost of electricity of the optimal design, for each MWh that the system delivers to the demand. |
| `lcoe_coverage_based` | float32 | USD/MWh | The cost of the system for each MWh of the full demand: `lcoe × served_fraction`. Add the cost of the unserved part of the demand to get the cost to supply the full demand (see [Coverage and served fraction](overview.md#coverage-and-served-fraction)). |
| `solar_factor` | float32 | MW per MW of demand | Installed solar capacity divided by the demand of the pixel. |
| `wind_factor` | float32 | MW per MW of demand | Installed wind capacity divided by the demand of the pixel. |
| `battery_factor` | float32 | hours of demand | Battery energy capacity divided by the demand of the pixel. |
| `coverage` | float32 | fraction of hours, 0 to 1 | The fraction of the hours of the weather year in which the design supplies the full demand. |
| `served_fraction` | float32 | fraction of energy, 0 to 1 | The fraction of the annual demand energy that the design supplies. It is equal to or larger than `coverage`. The `lcoe` divides by it. |
| `installation_cost` | float32 | USD | The sum of the three installation costs below. |
| `installation_cost_solar` | float32 | USD | CAPEX of the solar capacity in the investment year: `solar_factor × load_mw` times the solar CAPEX. |
| `installation_cost_wind` | float32 | USD | CAPEX of the wind capacity in the investment year. |
| `installation_cost_battery` | float32 | USD | CAPEX of the battery in the investment year, with the correction of the battery cost for its size (see [Model assumptions](model-assumptions.md)). |
| `cost_of_capital` | float32 | fraction per year | The discount rate that BOA used for the pixel. For example, 0.055 is 5.5 % per year. |
| `load_mw` | float32 | MW | The demand of the pixel: the load density multiplied by the area of the pixel. The installed solar capacity in MW is `solar_factor × load_mw`. The battery capacity in MWh is `battery_factor × load_mw`. |
| `cost_key` | string | — | The cost key that priced the pixel, for example `DEU` or `CHN:CN-GS`. |
| `status` | int8 | code | Why the pixel has, or has not, a result. The next paragraph gives the values. |

The unit of all money values is USD. BOA does not convert currency and does not adjust for
inflation. It uses the values of the cost workbook as they are.

The installation costs are the costs in the investment year only. They do not contain OPEX.

**Status.** `status` is 1 when the search found a result. For every other value, the variables of
the design, the LCOE, the installation costs, `coverage` and `served_fraction` are NaN. The values of `cost_key`,
`cost_of_capital` and `load_mw` depend on the status. The code table is in
[Known limitations](known-limitations.md#status-codes). The status is the same for every
investment year of a run.

- **Status 0.** The pixel is sea, is outside all regions, or BOA did not model it. `cost_key` is an
  empty string. `cost_of_capital` and `load_mw` are NaN.
- **Status 2 or 3.** `cost_key`, `cost_of_capital` and `load_mw` have values.

Per-year files from BOA before version 1.9.0 hold 0, not NaN, where there is no result.

**Precision.** The file stores floating-point variables as float32. The frontier cache stores
`served_fraction` rounded down and `coverage` rounded to the nearest step of 1/65 535. `coverage`
can be slightly below the coverage target, for example 0.89999 for a target of 0.9.

**How BOA makes the GLOBAL file.** BOA combines the regions when the per-year files of all regions
exist. The rules are:

- When the per-year file of a region is missing, BOA writes a warning, writes no GLOBAL file, and
  continues. The command can still end with the message that all simulations completed.
- When the files disagree on `search_params_hash`, BOA stops with a `ValueError`. Query the stale
  regions again.
- Where regions overlap, the first non-NaN value of each variable wins, with the regions in the
  order of the region list. For `status`, the first non-zero value wins. For `cost_key`, the first
  non-empty value wins. Each variable is chosen on its own, so the values of one pixel can come
  from different regions.
- The attributes of the GLOBAL file are the attributes of the first region, with `region` set to
  `GLOBAL` and a new `created_at`.

The attributes of a file record the scenario and the provenance:

| Attribute | Meaning |
|---|---|
| `investment_year` | The investment year of the file. |
| `investment_horizon_years` | The investment horizon in years. |
| `load_density_mw_km2` | The load density of the run, in MW/km². |
| `coverage_fraction` | The coverage target of the run. |
| `region` | The region of the file, or `GLOBAL`. |
| `era5_weather_year`, `era5_resolution_deg` | The weather year and the grid size, in degrees, of the weather data. |
| `search_params_hash` | A hash of the search settings. The frontier cache path contains it. |
| `frontier_cache_path` | The frontier cache that the file was priced from: the path of the cache of the region, relative to the cache directory. In the GLOBAL file, it is the cache of the first region only. The path separator depends on the operating system. |
| `capacity_ceiling_applied` | `0`: BOA did not apply the capacity ceiling. |
| `created_at`, `source` | When BOA wrote the file (UTC), and a fixed description. |
