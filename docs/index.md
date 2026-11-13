# Baseload Optimisation Atlas

BOA answers one question for each land location between about 58° S and 72° N. What is the
cheapest mix of solar panels, wind turbines and batteries that supplies a constant electricity
demand? This page shows what a BOA result looks like. It also shows what the result does not tell
you, and where to go next.

## What BOA calculates

Many industrial processes, for example steelmaking, need electric power in every hour of the year.
We call a constant demand of this kind a **baseload demand**. Solar and wind output changes with the
hour and the season, so a system needs more capacity than the demand and a battery.

For each **pixel** (one 0.25 degree cell of the ERA5 weather grid), BOA uses the real hourly weather
of one **weather year**. It searches for the system with the lowest **levelised cost of electricity
(LCOE)**. The system must supply the full demand in at least a chosen fraction of the hours (the
**coverage target**). The LCOE is the cost of the system for each MWh that it delivers, in USD
per MWh. The costs come from a **cost set**: they depend on the country and on the **investment
year**. The [Overview](overview.md) explains each of these terms and what one LCOE value means.

The result for each pixel is the LCOE and the **design** of the system: the solar factor, the wind
factor and the battery factor. These are the installed solar capacity, the installed wind capacity
and the battery energy capacity, each relative to the demand.

## A result

Figure 1 shows the result of one BOA run for the investment year 2025.

![Four world maps. The first map shows the LCOE of the optimal system. The other three show the solar factor, the wind factor and the battery factor of that system. The maps have no value over the sea. Most pixels with a high LCOE (above 178 USD per MWh) are in northern Russia. The others are mostly in northern Canada, Alaska and mainland Southeast Asia. Most pixels with a low LCOE (below 43 USD per MWh) are in western China. The others are mostly in northern China and on the Arabian Peninsula. The wind factor is zero in most of the tropics and highest in the far north. The battery factor is highest in the far north.](assets/index/f7_global_lcoe_map.png)

**Figure 1.** The optimal system for each pixel, for the investment year 2025. Top left: the LCOE in
USD per MWh delivered. The other maps show the design of the system: solar factor (MW of solar per
MW of demand), wind factor (MW of wind per MW of demand) and battery factor (hours of demand).
Values above the end of a colour scale have the last colour. Grey pixels have no result: they are
sea, outside the regions of the model, or (48 pixels) without a usable optimum. The run is
`wy2025_default_boa110_49e8`: [weather set](glossary.md#weather-set) `cds-2025` (weather year 2025), cost set `default`,
coverage target 0.9, load density 1 MW/km², run hash `49e8`. **BOA does not apply the capacity
ceiling to this result** (see [Known limitations](known-limitations.md#the-capacity-ceiling-is-not-applied)),
so the design in a pixel can need more land than the pixel has. The script is
`docs_figures/index_figures.py`.

Generated using Copernicus Climate Change Service information 2026. Neither the European
Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or
data it contains.

The maps show these features of the 226 160 pixels that have a result:

- Half of the pixels have an LCOE below 91 USD/MWh. One pixel in twenty has an LCOE below 43
  USD/MWh, and one in twenty has an LCOE above 178 USD/MWh.
- Between 10° S and 10° N, the median pixel has a wind factor of 0 and an LCOE of 109 USD/MWh.
- North of 60° N, the median wind factor is 2.9 and the median battery factor is 29 hours of
  demand.

## What a result does not tell you

The [Known limitations](known-limitations.md) page lists all limits. Three limits change how you
must read the maps:

- BOA does not apply the capacity ceiling. The LCOE is the cost of the unconstrained optimum.
- A run uses one weather year. The result has no year-to-year variation of the weather.
- BOA models no grid, no transmission and no other source of electricity. The hours that are not
  covered have no cost. The LCOE is the cost for each MWh that the system delivers, not the cost to
  supply the full demand.

## Where to go next

| You are | You want to | Go to |
|---|---|---|
| Energy analyst | Understand what BOA calculates and what one LCOE value means | [Overview](overview.md) |
| | Get a result for one location or one region | [Quickstart](quickstart.md) |
| | Know which results you can trust | [Known limitations](known-limitations.md) |
| | Read the output files | [Running the model](running-the-model.md#per-year-output-files) and [The promoted LCOE file](promoted-lcoe-file.md) |
| Modeller or reviewer | Check the optimisation problem and the search | [Search algorithm](methodology.md) |
| | Check the physical parameters and their sources | [Model assumptions](model-assumptions.md) |
| | Reproduce a result | [Running the model](running-the-model.md#reproduce-a-result) |
| | Find a step in the code | [Architecture](architecture.md) and [API reference](api-reference.md) |
| Integrator | Install BOA | [Installation](installation.md) |
| | Run BOA from start to end | [Quickstart](quickstart.md) |
| | Select the weather set, the cost set and the run label | [Running the model](running-the-model.md#select-the-weather-set-the-cost-set-and-the-run-label) |
| | Read the output file under a stable contract | [The promoted LCOE file](promoted-lcoe-file.md) |

The [Glossary](glossary.md) defines each technical term. The [Changelog](changelog.md) lists the
changes in each version.

## About

BOA is a collaboration between [SYSTEMIQ](https://www.systemiq.earth) and the
[Interdisciplinary Transformation University (IT:U)](https://it-u.at/en/). It is a separate package.
[Steel-IQ](https://github.com/systemiqofficial/steel-iq) reads the LCOE of BOA as the cost of
renewable power. The code is in the
[BOA repository](https://github.com/systemiqofficial/baseload-optimisation-atlas). The
[Project status](development.md) page tells you the status of the project and how to contribute.

The hosted web front end at [boa.systemiq.earth](https://boa.systemiq.earth) runs an earlier
version of the BOA method. Its results can be different from the results that this package
calculates.

If you use BOA, we would like to hear about it. Please
[open an issue](https://github.com/systemiqofficial/baseload-optimisation-atlas/issues) and tell us
how you use it.
