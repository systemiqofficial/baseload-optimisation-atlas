# Hydrogen cost (LCOH)

This page gives the facts of the optional LCOH step: what it calculates, its parameters and
sources, its output file and its limits. To run the step, see
[Hydrogen cost from a run](running-the-model.md#hydrogen-cost-from-a-run).

## What the step calculates

The [LCOH](glossary.md#lcoh) (levelised cost of hydrogen) is the cost of one kilogram of hydrogen.
The step calculates it for each pixel and [investment year](glossary.md#investment-year) of a
finished BOA run. The step reads the outputs of the run and does not change them.

- **Electrolyser size.** The electrolyser has 1 kW of electrical input for each kW of
  [baseload demand](glossary.md#baseload-demand).
- **Electricity.** The electrolyser uses all the electricity that the optimal BOA system of the
  pixel delivers. This electricity has the cost of the pixel's [LCOE](glossary.md#lcoe).
- **Full-load hours.** The electrolyser operates for 8760 × *sf* full-load hours per year. *sf* is
  the served fraction: the energy that the system delivers, divided by the baseload energy of one
  year.
- **Inputs from the run.** The step reads `lcoe`, `served_fraction` and `cost_of_capital` of each
  pixel from the GLOBAL per-year files (see
  [Per-year output files](running-the-model.md#per-year-output-files)).
- **Units.** The LCOH is in USD per kg of hydrogen. The energy basis is the lower heating value
  (LHV) of hydrogen.

**Cost basis.** The step adds a real premium to the cost of capital of the cost set. The CAPEX
values are in real 2024 USD. The result is in real 2024 USD only when the cost set gives a real
cost of capital, as the core set does. The [Systemiq set](cost-data.md#the-systemiq-set) gives a
nominal cost of capital. With that set, the electrolyser cost of capital mixes a nominal and a real
value. The step does not check the basis.

## Equation

For one pixel and investment year *y*:

| Term | Equation | Unit |
|---|---|---|
| Electricity for each kg | *e* = 33.33 / η(*y*) | kWh/kg |
| Hydrogen for each kW of electrolyser | *H* = 8760 × *sf* / *e* | kg per kW per year |
| Electrolyser cost of capital | *r* = WACC + *p*(*y*) | fraction per year |
| Electricity part | LCOE × *e* / 1000 | USD/kg |
| Capital part | CAPEX(*y*) × CRF(*r*, *N*) / *H* | USD/kg |
| Fixed O&M part | *f* × CAPEX(*y*) / *H* | USD/kg |
| Stack part | CRF(*r*, *N*) / *H* × Σ<sub>*k*</sub> *s* × CAPEX(*y* + *t<sub>k</sub>*) × (1 + *r*)<sup>−*t<sub>k</sub>*</sup> | USD/kg |

The LCOH is the sum of the four parts. The symbols are:

- **33.33 kWh/kg:** the LHV of hydrogen, 120 MJ/kg (US Department of Energy, *Introduction to
  Hydrogen for Code Officials*).
- **η:** the electrolyser efficiency, as a fraction of the LHV.
- **8760:** the hours in one year. **1000:** the kWh in one MWh. The LCOE is in USD/MWh.
- **WACC:** the weighted average cost of capital of the pixel, that is, its
  [cost of capital](glossary.md#cost-of-capital) in the cost set of the run.
- **p(y):** the premium on the WACC in the investment year *y*.
- **CAPEX:** the installed cost of the electrolyser, in USD per kW of electrical input.
- **f:** the fixed operation and maintenance (O&M) cost, as a fraction of CAPEX per year.
- **CRF(*r*, *N*):** the capital recovery factor, *r* / (1 − (1 + *r*)<sup>−*N*</sup>). It is the
  yearly payment that repays a cost of 1 in *N* years at the rate *r*. BOA uses the same factor
  for the LCOE.
- **N:** the plant life of the electrolyser, in years.
- **s:** the stack share of CAPEX. **L:** the stack life, in operating hours.
- **t<sub>k</sub>:** the year of stack replacement *k*, *t<sub>k</sub>* = *k* × *L* / (8760 × *sf*),
  for *k* = 1, 2, 3 and so on, while *t<sub>k</sub>* is less than *N*.

All parts use the rate *r* of the investment year *y*. A stack replacement costs *s* × the CAPEX of
the replacement year, *y* + *t<sub>k</sub>*.

The plant life *N* (20 years) is shorter than the investment horizon of the LCOE (25 years with the
default lifetimes). Each part is a yearly cost divided by the yearly hydrogen, so the two horizons
can be different.

## Parameters

The parameter file `electrolysis.csv` is part of the `boa.downstream` package. Each row names its
source as `<id>: <table>` or as `assumption`.

- Between two listed years, the value is linear.
- Before the first listed year and after the last listed year, the value is the value of that year.
- The efficiency, O&M, stack, plant life and premium values are the same in all three CAPEX
  scenarios.

**One electrolyser for all pixels.** All countries use the same parameter values. This is an
assumption. The sources give no regional values that are sufficiently robust for each country.

**CAPEX bound.** WEO Table B.5 gives a lower and an upper CAPEX value. By default (`mid`), the step
uses the mean of the two values. With `--capex-bound lower` or `--capex-bound upper`, it uses one of
the two values. The bound changes only the CAPEX.

The CAPEX scenarios are those of the IEA World Energy Outlook 2025 (WEO): CPS (Current Policies),
STEPS (Stated Policies) and NZE (Net Zero Emissions by 2050).

| Parameter | Value | Source |
|---|---|---|
| CAPEX, CPS (USD(2024)/kW) | mid: 1600 (2024), 1060 (2035), 925 (2050). Lower: 600, 440, 390. Upper: 2600, 1680, 1460 | `iea-weo-2025`: Table B.5, lower and upper range |
| CAPEX, STEPS (USD(2024)/kW) | mid: 1600 (2024), 1035 (2035), 920 (2050). Lower: 600, 420, 390. Upper: 2600, 1650, 1450 | `iea-weo-2025`: Table B.5, lower and upper range |
| CAPEX, NZE (USD(2024)/kW) | mid: 1600 (2024), 820 (2035), 745 (2050). Lower: 600, 330, 310. Upper: 2600, 1310, 1180 | `iea-weo-2025`: Table B.5, lower and upper range |
| Efficiency η (LHV) | 63 % (2024), 64 % (2030 and later) | `iea-ghr-2025-annex`: Production pathways, global average, columns 2024 and STEPS 2030 |
| Fixed O&M *f* | 3.0 % of CAPEX per year | `iea-ghr-2025-annex`: Production pathways |
| Stack life *L* | 50 000 operating hours | `iea-ghr-2025-annex`: Production pathways |
| Stack share *s* | 30 % of CAPEX | `irena-green-h2-2020`: p. 8, the share at GW-scale manufacturing |
| Plant life *N* | 20 years | `irena-green-h2-2020`: Fig. ES1, the future case |
| Premium *p* | 3.0 percentage points (real) in 2025, linear to 0 in 2050 | 2025: assumption; 2050: `irena-green-h2-2020`: Fig. ES1 |

**Premium in 2025.** The value of 3 points is an assumption. Egli et al. (2025), *Nature Energy* 10,
SI Table 5, give 3.25 points. Lee and Saygin (2023), OECD ENV/WKP(2023)19, p. 39, give 1 to 5
points by country rating. These papers are not pinned files.

**Premium in 2050.** IRENA (2020), Fig. ES1, decreases the electrolyser WACC from 10 % today to 6 %
in its future case. IRENA calls 6 % "similar to renewable electricity today". The step reads this as
a premium of 0 in 2050: the electrolyser then has the WACC of the pixel's wind and solar plants. The
IRENA value of 10 % today is more than 3 points above a typical renewable WACC, so the 2025 premium
can be low.

## Sources

The sources of this step have the tag `hydrogen` in the source list of BOA. The WEO file also has
the tag `costs`, because it is also a source of the core cost set (see [Cost data](cost-data.md)). The fetch command downloads
each file and checks its sha256 (see
[Hydrogen cost from a run](running-the-model.md#hydrogen-cost-from-a-run)).

| Id | Source | Used for |
|---|---|---|
| `iea-weo-2025` | IEA (2025), *World Energy Outlook 2025*, Annex B, Table B.5, p. 457 (CC BY 4.0) | CAPEX |
| `iea-ghr-2025-annex` | IEA (2025), *Global Hydrogen Review 2025: Assumptions annex*, "Production pathways", p. 6 (CC BY 4.0) | Efficiency, fixed O&M, stack life |
| `irena-green-h2-2020` | IRENA (2020), *Green hydrogen cost reduction*, p. 8 and Fig. ES1 (IRENA terms of use) | Stack share, plant life, premium in 2050 |

## Command options

| Option | Value | Default |
|---|---|---|
| `--run` | The run label, as given to `boa-run` | Necessary |
| `--scenario` | The WEO scenario of the CAPEX: `CPS`, `STEPS` or `NZE` | `STEPS` |
| `--capex-bound` | The CAPEX of the WEO range: `mid`, `lower` or `upper` | `mid` |
| `--coverage` | One or more coverage targets of the run | All coverage targets of the run |
| `--verbose` | More log output | Off |

The step writes a warning when the name of the cost set contains a different WEO scenario (for
example `core-nze` with `--scenario STEPS`). It does not warn for a cost-set name without a scenario
in it. The exit code is 1 when the run has no GLOBAL files for the selected coverage targets, or when
the grid or the status of the GLOBAL files is different between the years.

## Output file

The step writes one file for each weather year, load density and coverage target of the run. The
folder is `<data root>/downstream/<run folder>/`. The run folder is the run label with its hash, as
in `runs/`. The file name is:

`optimal_lcoh_wy<weather year>_<rho>MWkm2_cov<c>_<scenario>_<bound>_<first year>_<last year>.nc`

- `<rho>` is the load density with no decimal point and at least two integer digits.
- `<c>` is the coverage target with `p` in place of the decimal point.
- `<scenario>` is in lower case.
- `<bound>` is the CAPEX bound: `mid`, `lower` or `upper`.

Example: `optimal_lcoh_wy2025_01MWkm2_cov0p9_steps_mid_2025_2060.nc`.

The file has the layout of the [promoted LCOE file](promoted-lcoe-file.md). Each variable below is
float32 on `(year, lat, lon)`. `cost_key_id` (int16) and `status` (int8) are on `(lat, lon)`.

| Variable | Unit | What |
|---|---|---|
| `lcoh` | USD/kg | LCOH, the sum of the four parts |
| `lcoh_electricity` | USD/kg | Electricity part |
| `lcoh_capital` | USD/kg | Capital part |
| `lcoh_fom` | USD/kg | Fixed O&M part |
| `lcoh_stack` | USD/kg | Stack part |
| `electrolyser_wacc` | fraction | The rate *r*: pixel WACC plus the premium of the investment year |
| `max_annual_h2_kt` | kt/yr | Hydrogen potential: `max_annual_energy_twh` of the run × 1000 / *e*. Only when the run reports the capacity potential. 0 when the land cannot hold the design |

**No value.** A pixel has no value (NaN) when one of these conditions is true:

- its status is not 1 (optimum found);
- it has no cost key;
- its LCOE, served fraction or WACC is not a finite number;
- its served fraction is not more than 0 and not more than 1, or its WACC is less than 0.

**File attributes.**

| Attribute | What |
|---|---|
| `schema_version` | 1. The version of this file layout. |
| `title`, `source` | Text that names the file and the step |
| `primary_variable` | `lcoh`, the main variable of the file |
| `lcoh_basis` | `per_kg_h2_lhv` |
| `electrolyser_sizing` | The sizing and full-load hour rule |
| `electrolyser_scenario` | The CAPEX scenario: `CPS`, `STEPS` or `NZE` |
| `electrolyser_capex_bound` | The CAPEX bound: `mid`, `lower` or `upper` |
| `parameters_sha256` | The sha256 of the parameter file |
| `run`, `input_set`, `cost_set`, `input_data_sha256`, `boa_version` | The run, its weather set, cost set, cost workbook hash and BOA version |
| `years` | The investment years in the file |
| `created_at` | The time the file was written (UTC) |
| `cost_key_legend`, `status_legend` | The legends of `cost_key_id` and `status`, as in the promoted LCOE file |
| `investment_horizon_years`, `load_density_mw_km2`, `coverage_fraction`, `search_params_hash`, `era5_weather_year`, `era5_resolution_deg`, `capacity_ceiling_applied` | Copied from the GLOBAL per-year files of the run |

A file `<same name>_parameters.csv` is in the same folder. It gives the value, unit and sources of
each parameter, for each investment year.

## Limits

These limits apply to the LCOH in addition to the limits of the LCOE (see
[Known limitations](known-limitations.md)).

- **No capacity ceiling.** BOA does not apply the capacity ceiling, so the LCOH is also a cost
  without a land limit. The hydrogen potential `max_annual_h2_kt` gives the quantity that the land
  can supply at that LCOE.
- **Full-load hours.** The step uses 8760 × *sf* as the full-load hours and does not model
  part-load hours. The stack life uses these hours.
- **No degradation.** The efficiency does not decrease when the stack ages.
- **All delivered energy.** The electrolyser uses all the delivered energy at the LCOE. The step
  adds no hydrogen storage and uses no curtailed energy.
- **Costs not included.** Water, compression, hydrogen storage, transport and a grid connection.
  No income from oxygen.
- **Efficiency after 2030.** The efficiency is the 2030 value, because no source gives a later value.
- **Stack share.** IRENA (2020) gives the share of the system cost (stack and balance of plant). The
  step applies it to the installed CAPEX, which also contains engineering and construction.
- **One electrolyser for all countries.** The CAPEX and the efficiency do not change with the
  country. Installed costs in China are much lower than in other regions (IEA Global Hydrogen
  Review 2025: 600–1200 USD/kW in China, 2000–2600 USD/kW as the global average in 2024). The LCOH
  is therefore too high in China and possibly too low in Europe and North America.
- **One premium for all countries.** The premium does not change with the country risk.
- **Electrolyser type.** The values are for water electrolysis in general, not for PEM or alkaline
  electrolysers.
- **Cost basis.** The result is in real 2024 USD only with a cost set that gives a real cost of
  capital (see "Cost basis" above).
