# Cost data

This page tells you which cost sets BOA can use, where their values come from, and what their
limits are. To prepare or rebuild a set, see [Preparing cost data](cost-data-prep.md).

## Cost sets

| Set | Made from | Get it |
|---|---|---|
| **Core set** (`boa-cost-data-core`) | Four public sources (below), with a build script that BOA tracks | Build it with `scripts/cost/build_core.py`, then `boa-data-prepare --input-file <workbook>` |
| **Systemiq set** (`boa-cost-data` v0.1) | The Steel-IQ master input workbook v3.0.0, made by hand by Systemiq | `boa-data-prepare` downloads it (the pinned package) |

The core set has one workbook per IEA WEO 2025 scenario: CPS, STEPS and NZE. All values are in
real 2024 USD.

## Sources of the core set

`boa-sources-fetch` downloads these files and checks their sha256
(`boa/config/cost_sources.toml`). Each workbook row names its source as `<id>: <table>`.

| Id | Source | Used for |
|---|---|---|
| `irena-rpgc-2024-data` | IRENA (2025), *Renewable power generation costs in 2024*, data file | CAPEX 2024 (Tables 2.1, 3.1, S.1), O&M (Tables A3, A4), WACC (Fig A1) |
| `irena-rpgc-2024-report` | IRENA (2025), *Renewable power generation costs in 2024*, report | Default WACC (Table A1, Box A.2), regions (Annex III) |
| `iea-weo-2025` | IEA (2025), *World Energy Outlook 2025*, Annex B (CC BY 4.0) | CAPEX change to 2035 and 2050 (Tables B.4a–c), battery CAPEX (Table B.5) |
| `natural-earth-50m-map-subunits` | Natural Earth 1:50m map subunits, v5.1.1 (public domain) | ISO-3 codes and UN subregions |

## How the core set is made

Each workbook has a **Method** sheet with these rules, an **Inputs** sheet with every source
value it uses, and the intermediate values next to each derived value.

| Value | Rule |
|---|---|
| CAPEX 2024 | IRENA weighted average of the cost region. The Middle East has no IRENA row and takes the global average. |
| CAPEX 2035, 2050 | 2024 value × the WEO Table B.4 change from 2024. United States, Europe (EU row), China and India follow their own row; the other regions follow the mean of the four. BOA interpolates the years between. |
| Battery CAPEX | WEO Table B.5, global, in every region. |
| OPEX | IRENA O&M ÷ the region's 2024 CAPEX, as a fraction per year. |
| Cost of capital | IRENA Fig A1, mean of onshore wind and solar PV (real, after tax). A country with no own value takes the median of the own values in its cost region. |
| Regions | IRENA Annex III. A code that Annex III does not list takes the region of its Natural Earth subregion. |

## Limits of the core set

- No core source gives battery O&M. The battery OPEX is a placeholder of 0.02 per year.
- Battery CAPEX is global, also for China.
- WEO Table B.4 has four regions only, so nine cost regions follow the mean change.
- 119 of 244 countries have no own Fig A1 value and take the regional median. Fig A1 values
  that IRENA raised to its minimum WACC floor (Box A.2) count as own values.

!!! note "Cost of capital for other plants"
    The cost of capital is for wind and solar projects. For an electrolyser or a power-to-methanol
    plant that uses BOA power, add a technology premium of about 3 percentage points (real),
    with +1 and +5 points as the sensitivity range. Sources: Egli et al. (2025), *Nature Energy*
    10, SI Table 5; Lee and Saygin (2023), OECD ENV/WKP(2023)19, p. 39; Terrapon-Pfaff et al.
    (2025), *Frontiers in Energy Research* 13, Table 2. No source gives a premium for the methanol
    synthesis step alone.

## The Systemiq set

The Systemiq set copies its values from the Steel-IQ master input workbook v3.0.0. The
`Contents` sheet of that workbook names its sources (IRENA, Ember, Damodaran and others). Some
values, for example OPEX and the learning rates, have no stated source.
