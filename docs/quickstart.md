# Quickstart

This page takes you from a new installation to two results: the optimal system for one location,
and the optimal systems for all pixels for one year. Each step shows the output that you must see.
Do the [installation](installation.md) first, and activate the environment.

The steps use the weather year 2025, the default cost set, a coverage target of 0.9 and the
investment year 2030.

## Step 1: Prepare the data

```bash
boa-data-prepare
boa-cds-prepare --weather_year 2025 --use-republished
```

`boa-data-prepare` downloads the pinned cost data and the geographic reference data. It writes the
cost set `default`. `boa-cds-prepare` downloads the re-published capacity factors of 2025 (about
6.6 GB) and builds the weather stores of the [weather set](glossary.md#weather-set) `cds-2025`. Both commands reuse what is
already in the data root.

When both commands end, these files exist in your [data root](installation.md#the-data-root):

```text
costs/default/boa_cost_data.xlsx
inputs/cds-2025/cds-zarr/                  one profile store and one max-capacity store for each region
```

## Step 2: Run one location

```bash
boa-run point --lat 52.5 --lon 13.4 --weather-input cds-2025 --run quickstart --coverage 0.9 --start-year 2030 --end-year 2030
```

The location is near Berlin. BOA finds the region and the country of the location. It uses the
weather of the nearest 0.25 degree pixel (here the pixel at 52.5° N, 13.5° E). It uses the costs
of the country of the exact location (for some countries, of the sub-national region). Then it
searches for the optimal system.

The command ends after a few seconds. This is the output. This page shows only the main lines.
A line `...` marks lines that this page omits, and `...` in a line marks text that this page
shortens. The lines in the real output start with a date and a time. This page omits them, and it
replaces your data root with `<root>`.

```text
...
INFO - BOA: single-point simulation
...
INFO - Location: Lat=52.5, Lon=13.4 (region auto-derived)
INFO - Years: [2030]; load density: 1.0 MW/km2; coverage 0.9
INFO - Data root: <root>
INFO - Inputs: cds-2025; costs: default; run: quickstart_49e8
INFO - Preflight OK: weather year 2025, cost set 'default'.
INFO - Run manifest: <root>\runs\quickstart_49e8\run.json
INFO - Running single-point simulation for year 2030
...
INFO - Location DEU -> region EUROPE (inside_box=True)
...
INFO - Physical capacity limits: {'solar': 46.827000000000005, 'wind': 10.42}
INFO - Building the frontier and pricing it...
WARNING - [UNCONSTRAINED] The capacity ceiling is not applied yet (...), so this LCOE is the unconstrained optimum. ... Do not promote it.
...
INFO - Optimization complete for (52.5, 13.4)
INFO -   Optimal LCOE: 75.49 $/MWh
INFO -   Installation cost: 3208.23 M$
INFO -   Solar overscale factor: 4.38
INFO -   Wind overscale factor: 1.98
INFO -   Battery overscale factor: 18.57
INFO - All plots saved to <root>\runs\quickstart_49e8\outputs\plots\single_point\cov0.9\lat_52_50_lon_13_40
INFO - Total runtime: 7.06 seconds (0.12 minutes)
INFO - point: all years complete.
```

How to read the result:

- **Optimal LCOE** is the LCOE of the optimal system: 75.49 USD for each MWh that the system
  delivers.
- **Installation cost** is the capital cost (CAPEX) of the system in 2030, in million USD. It is
  for a demand of 470 MW: the load density of 1 MW/km² times the area of the pixel.
- The three **factors** are the design of the system, relative to the demand. For each MW of demand,
  the system has 4.38 MW of solar and 1.98 MW of wind. The battery stores 18.57 hours of the demand.
  The log calls the three values "overscale factors". The battery factor is in hours of demand, not
  in MW per MW.
- **Physical capacity limits** is the capacity ceiling of the pixel, relative to the demand.
  BOA writes this line but does not apply the ceiling, and the WARNING says this. Here the system
  is far below the ceiling. See
  [Known limitations](known-limitations.md#the-capacity-ceiling-is-not-applied).

The command also writes two plots, a time series of the profiles and the state of charge of the
battery, in the folder that the last INFO line names.

## Step 3: Check a run of all regions

`boa-run` computes all regions. The smallest run is one investment year at one coverage target.
Check the inputs first. The command does no computation:

```bash
boa-run --weather-input cds-2025 --run quickstart --coverage 0.9 --start-year 2030 --end-year 2030 --dry-run
```

This is the end of the output:

```text
INFO - Inputs: cds-2025; costs: default; run: quickstart_49e8
INFO - Preflight OK: weather year 2025, cost set 'default'.
INFO - Frontier caches: <root>\inputs\cds-2025\cache_frontiers
INFO - Outputs: <root>\runs\quickstart_49e8\outputs
INFO - Dry run - exiting without running simulation
```

When a store is missing, the command stops and prints the preparation command to run.

## Step 4: Run all regions for one year

```bash
boa-run --weather-input cds-2025 --run quickstart --coverage 0.9 --start-year 2030 --end-year 2030
```

BOA builds the frontier cache of each of the 17 regions, and then writes the result for 2030. The
build of the frontier caches takes most of the time. The README gives about 75 minutes for each
coverage target for a run from 2025 to 2060. This page gives no time for the run of this step.

A second run with the same weather year and coverage target can reuse the caches. BOA reuses a
cache only while its [cost anchors](methodology.md#cost-anchors) cover every combination of cost
key and investment year in the new run. If they do not, BOA builds the cache again. See
[Reuse of the frontier cache](known-limitations.md#reuse-of-the-frontier-cache).

The last line of the log is `All simulations completed successfully!`.

The run writes one file for each region and one file for all regions together. For this run, they
are in this folder:

```text
<root>/runs/quickstart_49e8/outputs/wy2025/01MWkm2/cov0p9/nc/
├── ALASKA/optimal_sol_wy2025_01MWkm2_cov0p9_ALASKA_2030.nc
├── ...                                                        (17 regions)
├── EUROPE/optimal_sol_wy2025_01MWkm2_cov0p9_EUROPE_2030.nc
├── ...
└── GLOBAL/optimal_sol_wy2025_01MWkm2_cov0p9_GLOBAL_2030.nc
```

`boa-run` always computes all regions. To get one region, read its file.

Each file has these variables on the dimensions `lat` and `lon`: `lcoe`, `lcoe_coverage_based`,
`installation_cost`, `installation_cost_solar`, `installation_cost_wind`, `installation_cost_battery`,
`solar_factor`, `wind_factor`, `battery_factor`, `coverage`, `served_fraction`, `cost_of_capital`,
`load_mw`, `cost_key` and `status`. The units are in
[Per-year output files](running-the-model.md#per-year-output-files).

Read the pixel of step 2 from the file of the region `EUROPE`. Replace `<root>` with your data root:

```python
import xarray as xr

ds = xr.open_dataset("<root>/runs/quickstart_49e8/outputs/wy2025/01MWkm2/cov0p9/nc/EUROPE/"
                     "optimal_sol_wy2025_01MWkm2_cov0p9_EUROPE_2030.nc")
pixel = ds.sel(lat=52.5, lon=13.5)
for name in ["lcoe", "solar_factor", "wind_factor", "battery_factor", "coverage", "status"]:
    print(f"{name:15s} {float(pixel[name]):.2f}")
```

```text
lcoe            75.46
solar_factor    4.38
wind_factor     1.98
battery_factor  18.51
coverage        0.90
status          1.00
```

The `lcoe` is in USD/MWh, the three factors are the design as in step 2, and `coverage` is the
fraction of hours in which the system supplies the full demand. A `status` of 1 means that the
search found a result for the pixel. The file attribute `capacity_ceiling_applied` is 0.

The values are close to the values of step 2, but not the same. The difference can come from the
placement of the search. The single-point run places its search with the costs of only this pixel.
A run of all regions places the search with a small set of cost mixes for all pixels (see
[Search algorithm](methodology.md#cost-anchors)).

## Next steps

- Make a map of the `GLOBAL` file, or give the LCOE to another model: see
  [Running the model](running-the-model.md) and [The promoted LCOE file](promoted-lcoe-file.md).
- Learn what the LCOE means and what the coverage target does: see the [Overview](overview.md).
- Learn which results you can trust: see [Known limitations](known-limitations.md).
