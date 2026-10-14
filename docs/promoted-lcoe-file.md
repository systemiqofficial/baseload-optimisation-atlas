# The promoted LCOE file

`boa-promote-lcoe`, or `boa-run --promote-lcoe`, combines one scenario's per-year results into a
single NetCDF file. This is the file the steel simulation reads, so its layout is a contract:
anything below that changes raises `schema_version`.

## Where it is written

```text
<root>/lcoe-only/<run>_<hash>/optimal_lcoe_wy<weather_year>_<rho>MWkm2_cov<c>_<first>_<last>.nc
```

- `<root>` is `$BOA_DATA_ROOT`, else `~/.boa`.
- `<run>_<hash>` is the run directory name (see [running-the-model.md](running-the-model.md)).
- `<rho>` is the load density in MW/km2 and `<c>` the coverage, written without dots:
  `01MWkm2` is 1.0 MW/km2 and `cov0p85` is a coverage of 0.85.
- `<first>` and `<last>` are the first and last investment years in the file.

Example: `optimal_lcoe_wy2024_01MWkm2_cov0p85_2025_2060.nc`. A reader can select a file by its
coverage token alone (`*_cov0p85_*`).

## Contents

| Name | Dimensions | Type | Meaning |
|---|---|---|---|
| `year` | `year` | int32 | Investment year |
| `lat`, `lon` | `lat`, `lon` | float | Pixel centres on the ERA5 grid (0.25 degrees) |
| `lcoe` | `year`, `lat`, `lon` | float32 | Levelised cost of electricity of the optimal solar, wind and battery system, in USD per MWh delivered, in the cost workbook's currency year (2024 USD for `boa-cost-data` v0.1). NaN wherever a pixel has no optimum |
| `cost_key_id` | `lat`, `lon` | int16 | Index into the `cost_key_legend` attribute: the cost key that priced the pixel |
| `status` | `lat`, `lon` | int8 | Index into the `status_legend` attribute: why a pixel has, or lacks, an LCOE |

`cost_key_id` and `status` are the same in every year, so they are stored once. Promotion stops
if the per-year files disagree on either.

## Attributes

**The contract.** A reader should check these before using the file:

| Attribute | Value | Meaning |
|---|---|---|
| `schema_version` | `1` | Version of this layout. A reader should refuse a version it does not know |
| `lcoe_basis` | `"per_mwh_delivered"` | `lcoe` divides the system's cost by the energy it actually delivers to the baseload demand, not by all the energy it generates |
| `capacity_ceiling_applied` | `0` or `1` | `1` when each pixel's solar and wind capacity was limited by the land available to it. Today always `0`: the optimum is unconstrained |

**The scenario**, copied from the per-year files, which must all agree: `investment_horizon_years`,
`load_density_mw_km2`, `coverage_fraction`, `search_params_hash`, `era5_weather_year`,
`era5_resolution_deg` and `capacity_ceiling_applied`. Promotion stops if any per-year file lacks
`capacity_ceiling_applied`, which only runs from BOA versions before v1.7.0 do.

**Provenance**, so the file identifies what produced it without the run directory:

| Attribute | Meaning |
|---|---|
| `source`, `title` | Fixed descriptions |
| `run` | Run directory name, `<run>_<hash>` |
| `input_set`, `cost_set` | The weather input set and the cost set the run used |
| `input_data_sha256` | sha256 of the cost workbook the run used |
| `boa_version`, `run_git_sha` | BOA version and git commit of the run |
| `run_created_at`, `promoted_at` | When the run started and when this file was written (UTC) |
| `promoted_years` | The investment years in the file |

**Legends:**

- `cost_key_legend`: the cost keys, comma-separated, in `cost_key_id` order. Keys are an ISO-3
  country code (`DEU`) or a province (`CHN:CN-GS`); an empty entry marks pixels with no cost key.
- `status_legend`: `code=label` pairs, separated by semicolons because one label contains a comma.
  Code 1 is "Optimum found"; every other code means `lcoe` is NaN.

## Changing the format

Raise `PROMOTED_LCOE_SCHEMA_VERSION` in `src/boa/model/lcoe_promotion.py` whenever a variable,
attribute, unit or meaning above changes, and update this page in the same commit. Adding a new
attribute that no reader needs does not require a new version.
