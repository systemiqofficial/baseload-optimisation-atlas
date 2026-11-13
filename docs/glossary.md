# Glossary

This page gives the meaning of each technical term that the pages of this site use outside the
[Methodology](methodology.md). Each term has one definition, and all pages use the term with this
meaning. The terms of the search itself are defined in the Methodology, where each is first used.
The terms are in alphabetical order.

## Anchor

One set of cost coefficients that the cache build uses to rank the seeds. Only its cost mix (the
shares of the solar, wind and battery coefficients) matters. A frontier cache is built for a small
set of anchors. See [Cost anchors](methodology.md#cost-anchors).

## Baseload demand

A constant electricity demand: the same power in each hour of the year. See
[What BOA calculates](overview.md#what-boa-calculates).

## Battery factor

The energy capacity of the battery divided by the demand, in hours of demand. See
[The design](methodology.md#the-design).

## Capacity ceiling

The largest solar and wind capacity that the available land of a pixel can hold. BOA does not apply
it when it selects a design. See
[Known limitations](known-limitations.md#the-capacity-ceiling-is-not-applied).

## Capacity factor

The power that 1 MW of installed solar or wind capacity gives in one hour, as a fraction of 1 MW.

## CAPEX

Capital expenditure: the cost to install one unit of a technology in an investment year. The cost
set gives it for each technology, cost key and year. See
[What one LCOE value means](overview.md#what-one-lcoe-value-means).

## Containment check

The test of whether no coarse-grid node outside the patches can have a lower LCOE than the result
(`patch_certified`). See [The query](methodology.md#the-query).

## Cost key

The country or the province whose costs BOA uses for a pixel, for example `DEU` or `CHN:CN-GS`.
A key that ends in `:GLOBAL_AVG` shows that BOA used mean costs. See
[Cost fallbacks](known-limitations.md#inputs-and-costs).

## Cost mix

The three cost coefficients of solar, wind and battery, divided by their sum. See
[Cost anchors](methodology.md#cost-anchors).

## Cost of capital

The discount rate that BOA applies to the costs and to the delivered energy. The cost set gives one
value for each country. See [Cost fallbacks](known-limitations.md#inputs-and-costs).

## Cost set

One set of cost data: CAPEX for each technology, cost key and year, and OPEX and cost of capital
for each cost key. See
[Select the weather set, the cost set and the run label](running-the-model.md#select-the-weather-set-the-cost-set-and-the-run-label).

## Coverage

The fraction of the hours of the weather year in which the system supplies the full demand. An hour
with only part of the demand supplied is not a covered hour. See
[Coverage and served fraction](overview.md#coverage-and-served-fraction).

## Coverage target

The lowest coverage that a design must have: a fraction larger than 0 and smaller than 1. See
[The optimisation problem](methodology.md#the-optimisation-problem).

## Curtailment

The surplus solar and wind energy that the battery cannot take, because it is full. This energy is
lost.

## Design

One system, given as three numbers: the solar factor, the wind factor and the battery factor. See
[The design of a system](overview.md#the-design-of-a-system).

## Dispatch

The hour-by-hour simulation of one design over the weather year: generation, battery charge,
supplied demand and unmet energy. See [Dispatch rules](methodology.md#dispatch-rules).

## ERA5

The ERA5 reanalysis of the weather, from ECMWF. BOA uses its 0.25 degree grid for the pixels. See
[The CDS data pipeline](cds-data-pipeline.md).

## Frontier

The set of designs in which the battery is the smallest battery that meets the coverage target for
the solar and wind factors of the design. See
[The optimisation problem](methodology.md#the-optimisation-problem).

## Frontier cache

The stored dispatch results for the pixels of one region. They contain no cost, no investment year
and no load density. One cache is for one weather year, region, coverage target and set of search
settings. See [What the frontier cache contains](methodology.md#what-the-frontier-cache-contains).

## GLOBAL file

The file that combines the per-year files of all regions for one investment year, on one grid.
See [Running the model](running-the-model.md#per-year-output-files).

## Investment horizon

The number of years over which BOA calculates the LCOE: the longest technology lifetime. See
[What one LCOE value means](overview.md#what-one-lcoe-value-means).

## Investment year

The year in which the system is built. It sets the CAPEX that BOA uses.

## LCOE

Levelised cost of electricity: the discounted cost of the system divided by the discounted energy
that the system delivers to the demand, in USD per MWh. See
[What one LCOE value means](overview.md#what-one-lcoe-value-means).

## Load density

The demand for each km² of pixel area, in MW/km². The pixel area is the full area of the grid
cell, land and water. See
[Why the LCOE does not change with the load density](overview.md#why-the-lcoe-does-not-change-with-the-load-density).

## OPEX

Operating expenditure: the yearly operating cost of a technology. The cost set gives it as a
fraction of the CAPEX.

## Overscale factor

The word that the code and the log of `boa-run point` use for the factors of a design. This site
uses the terms solar factor, wind factor and battery factor. See [Solar factor](#solar-factor).

## Patch

A fine grid of designs around a promising node of the coarse grid. The frontier cache holds only
the designs of the patches. See [Patches](methodology.md#6-patches).

## Per-year file

The NetCDF file of one region and one investment year of one scenario. A scenario is a weather
year, a load density and a coverage target. See
[Per-year output files](running-the-model.md#per-year-output-files).

## Pixel

One cell of the ERA5 weather grid, 0.25 degrees in latitude and in longitude. BOA models a pixel
when the ERA5 land-sea mask, which gives the fraction of land of the cell, is more than 0.5.

## Promoted LCOE file

One NetCDF file with the LCOE and the status of all investment years of one scenario of a run. See
[The promoted LCOE file](promoted-lcoe-file.md).

## Query

The step that prices the stored designs of one pixel with the costs of one investment year and one
cost key, and returns the design with the lowest LCOE. It does no dispatch simulation. See
[The query](methodology.md#the-query).

## Region

A rectangle of latitude and longitude that BOA builds and prices as one unit. Together, the regions
cover most land between about 58° S and 72° N. See
[Region extent](known-limitations.md#region-extent).

## Run directory

The directory `<root>/runs/<run label>_<hash>`. It holds `run.json` and the per-year files of the
run. See [Select the weather set, the cost set and the run label](running-the-model.md#select-the-weather-set-the-cost-set-and-the-run-label).

## Run label

The name of a run: the value of the option `--run`. The run label and a hash of the search settings
and the technology lifetimes form the name of the [run directory](#run-directory).

## Search settings

The parameters of the search. They are not physical parameters. A change to one of them makes a
different frontier cache and a different run directory. See
[Search settings](methodology.md#search-settings).

## Served fraction

The fraction of the annual demand energy that the system supplies. See
[Coverage and served fraction](overview.md#coverage-and-served-fraction).

## Solar factor

The installed solar capacity divided by the demand, in MW per MW of demand. See
[The design](methodology.md#the-design).

## Status code

A number for each pixel that tells whether BOA found a result, and if not, why. See
[Status codes](known-limitations.md#status-codes).

## Unmet energy

The part of the demand that neither the generation nor the battery supplies in an hour. BOA gives it
no cost, and no other source supplies it.

## Weather set

The profile stores of one weather year under `<root>/inputs/<set>/`, for example `cds-2024`. The
option `--weather-input` selects it. The code and some output attributes call it the input set
(`input_set`).

## Weather year

The calendar year of the hourly capacity factors that BOA uses.

## Wind factor

The installed wind capacity divided by the demand, in MW per MW of demand. See
[The design](methodology.md#the-design).
