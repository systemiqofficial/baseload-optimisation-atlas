# Cost data

This page tells you which cost sets BOA can use, where their values come from, and what their
limits are. To prepare or rebuild a set, see [Preparing cost data](cost-data-prep.md).

## Cost sets

| Set | Made from | Get it |
|---|---|---|
| **Core set** (`boa-cost-data-core`) | Four public sources (below). A build script in the BOA repository makes the workbooks. | Build it from a repository checkout: see [Building the core cost set](cost-data-prep.md#building-the-core-cost-set) |
| **Systemiq set** (`boa-cost-data` v0.1) | The Steel-IQ master input workbook v3.0.0, copied by BOA | `boa-data-prepare` downloads it (the pinned package) |

The core set has one workbook for each scenario of the IEA World Energy Outlook 2025 (WEO): CPS
(Current Policies), STEPS (Stated Policies) and NZE (Net Zero Emissions by 2050). All costs in
USD are real 2024 USD. The workbooks have the years 2024, 2035 and 2050. BOA interpolates
linearly between them, keeps the 2050 value after 2050, and rejects an investment year before 2024.

## Sources of the core set

`boa-sources-fetch` downloads these files and checks their sha256. The list of files is
`src/boa/config/cost_sources.toml`. Each workbook row names its source as `<id>: <table>`.

| Id | Source | Used for |
|---|---|---|
| `irena-rpgc-2024-data` | IRENA (2025), *Renewable power generation costs in 2024*, data file | CAPEX 2024 (Tables 2.1, 3.1, S.1), O&M (Tables A3, A4), cost of capital (Fig A1) |
| `irena-rpgc-2024-report` | IRENA (2025), *Renewable power generation costs in 2024*, report | Regions (Annex III). Table A1 gives the default values in Fig A1, which the build does not use as own values. |
| `iea-weo-2025` | IEA (2025), *World Energy Outlook 2025*, Annex B (CC BY 4.0) | CAPEX change to 2035 and 2050 (Tables B.4a–c), battery CAPEX (Table B.5) |
| `natural-earth-50m-map-subunits` | Natural Earth 1:50m map subunits, v5.1.1 (public domain) | ISO-3 codes and UN subregions |

## How the core set is made

Each workbook has a **Method** sheet with these rules. An **Inputs** sheet lists the values the
build takes from the IRENA data file, from WEO and from Table A1. Each derived value has its
intermediate values next to it.

| Value | Rule |
|---|---|
| CAPEX 2024 (USD/kW) | The IRENA weighted average of the cost region. The Middle East has no IRENA row. It takes the global average. |
| CAPEX 2035, 2050 (USD/kW) | The 2024 value times the change from 2024 in WEO Table B.4. United States, Europe (EU row), China and India follow their own row. The other regions follow the mean change of these four rows. |
| Battery CAPEX (USD/kWh) | WEO Table B.5, global, in every region. |
| OPEX (fraction of CAPEX per year) | IRENA O&M (operation and maintenance) divided by the 2024 CAPEX of the region. The regions Europe, Other North America, Oceania and United States take the OECD O&M. Brazil, China, India and the United States take their own wind O&M. |
| Cost of capital (fraction) | IRENA Fig A1, the mean of onshore wind and solar PV (real, after tax). A country without its own Fig A1 value takes the median of the own values in its cost region. |
| Regions | IRENA Annex III. A code that is not in Annex III takes the region of its Natural Earth subregion. |

## Limits of the core set

- No core source gives battery O&M. The battery OPEX is a placeholder of 0.02 per year.
- Battery CAPEX is global, also for China.
- WEO Table B.4 has four regions only, so nine cost regions follow the mean change.
- 120 of 245 countries have no own Fig A1 value and take the regional median. Fig A1 values
  that IRENA raised to its minimum floor (report Box A.2) count as own values.

!!! note "Cost of capital for other plants (not used by BOA)"
    The cost of capital is for wind and solar projects. For an electrolyser or a power-to-methanol
    plant that uses BOA power, add a technology premium of about 3 percentage points (real). Use
    +1 and +5 points for a sensitivity. Sources: Egli et al. (2025), *Nature Energy* 10, SI Table 5
    (3.25 points); Lee and Saygin (2023), OECD ENV/WKP(2023)19, p. 39 (1 to 5 points, by country
    rating); Terrapon-Pfaff et al. (2025), *Frontiers in Energy Research* 13, Table 2. These
    sources give no premium for the methanol synthesis step alone.

## The Systemiq set

The Systemiq set copies its values from the Steel-IQ master input workbook v3.0.0. Its cost of
capital is nominal and comes from Damodaran country risk data. Its CAPEX after 2024 comes from
learning rates. Some values, for example OPEX and the learning rates, are assumptions and have
no external source.
