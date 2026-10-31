# Glossary

This page gives the meaning of each technical term that the pages of this site use. Each term
has one definition, and all pages use the term with this meaning. The terms are in alphabetical
order.

## Anchor

One set of cost coefficients that the build uses to rank the seeds. BOA selects a small set of
anchors so that the cost mix of each candidate is near an anchor. Thus the anchors decide where
the patches are, and which designs the frontier cache contains. The stored dispatch results
contain no cost, but the metadata of the cache records the anchors. See
[Methodology](methodology.md#cost-anchors).

## Baseload demand

A constant electricity demand: the same power in each hour of the year.

## Battery factor

The energy capacity of the battery divided by the demand, in hours of demand.

## Battery limit

The largest battery size that the bracket search tests: `b_cap` (default 500 hours of demand).
A node is infeasible when no tested battery up to this limit meets the coverage target.

## Battery rung

One of the battery sizes that BOA stores at a patch node, from the minimum battery to
`ladder_max_span` times the minimum battery. With the default settings there is one rung: the
minimum battery.

## Bisection

The method that BOA uses to find the minimum battery at one node. It halves the bracket again and
again, and keeps the end that meets the coverage target. At a patch node, it stops when the width
of the bracket is at most `tol_rel_patch` (default 0.01) of its upper end. At a solved node of the
coarse grid, it stops after `coarse_bisect_steps` steps (default 3). It then keeps the end that
does not meet the target, which is a lower bound.

## Bracket

The interval of battery sizes between the largest tested battery that does not meet the coverage
target and the smallest tested battery that meets it. The minimum battery is in the bracket.
BOA first tests a node with no battery. When a node has no start value, BOA then tests the
batteries 0.25, 0.5, 1, 2, … hours of demand, each twice the one before. When a neighbour node
gives a start value, BOA starts there. It halves the battery size while the target is met, and it
doubles the size while the target is not met. There is no bracket when `b_min` = 0.

## Candidate

A pair of an investment year of the run and a cost key of the cost set, with its cost
coefficients at a demand of 1. BOA selects the anchors so that each candidate is near an anchor.

## Capacity ceiling

The largest solar and wind capacity that the available land of a pixel can hold. BOA can
calculate it, but it does not apply it when it selects a design. Each output file records
`capacity_ceiling_applied = 0`.

## Capacity factor

The power that 1 MW of installed solar or wind capacity gives in one hour, as a fraction of 1 MW.

## CAPEX

Capital expenditure: the cost to install one unit of a technology in an investment year. The cost
set gives it for each technology, cost key and year.

## Coarse grid

A grid of nodes, evenly spaced over the search box of a pixel (`coarse_grid`, default 25 × 25
nodes). At each node, the coarse grid holds a lower bound on the minimum battery, not the minimum
battery itself. BOA solves only every `coarse_stride`-th node on each axis (the solved nodes;
default every third node). It fills the other nodes (the filled nodes). It uses the lower bounds
to select the seeds.

## Coarse step

The distance between two adjacent nodes of the coarse grid on one axis: `s_max` or `w_max`
divided by `coarse_grid − 1` (default 24). The `coarse_stride` (default 3) is the number of
coarse steps between two solved nodes.

## Containment check

A test that BOA does for each result. It gives `patch_certified`. The value is true when no coarse
node outside the patch boxes can be cheaper than the result. This is the case when the lower
bound on the LCOE at each such node is at or above the LCOE of the result. Nodes that the corner
cut removes, and nodes where no tested battery meets the target, always pass. The output files do
not record the result of the check.

## Corner cut

The removal of the corner of the search box where both the solar factor and the wind factor are
large. Nodes where `s/s_max + w/w_max` is more than `corner_cut_threshold` (default 1.2) get an
infinite lower bound. The cut does not touch the axes `s = 0` and `w = 0`.

## Cost coefficients

The four numbers `a_s`, `a_w`, `a_b` and `d0` that BOA calculates from the costs of one cost key
in one investment year. `a_s`, `a_w` and `a_b` are the discounted lifetime costs of one unit of
each factor. `d0` is the discounted demand energy over the investment horizon. With them, the
LCOE of a design is a short formula (see [Methodology](methodology.md#the-optimisation-problem)).

## Cost key

The country (ISO 3166-1 alpha-3 code, for example `DEU`) or the province (for example `CHN:CN-GS`)
whose costs BOA uses for a pixel. When the cost set has no costs for the province, BOA uses the
costs of the country. When it has no costs for the country, BOA uses the mean costs of all cost
keys in the cost set. A key of this kind ends in `:GLOBAL_AVG`, for example `FRA:GLOBAL_AVG`. A
pixel with no known country has the key `UNKNOWN:GLOBAL_AVG`.

## Cost mix

The three cost coefficients `a_s`, `a_w` and `a_b` of a candidate, divided by their sum. BOA
compares the cost mix of each candidate with the cost mix of the anchors.

## Cost of capital

The discount rate that BOA applies to the costs and to the delivered energy. The cost set gives
one value for each country. A province uses the value of its country. A country with no value in
the cost set uses the highest value of all mapped countries in the cost set.

## Cost set

One set of cost data: CAPEX for each technology, cost key and year, and OPEX and cost of capital
for each cost key.

## Coverage

The fraction of the hours of the weather year in which the system supplies the full demand.

## Coverage target

The lowest coverage that a design must have: a fraction larger than 0 and smaller than 1.

## Covered hour

An hour in which the generation and the battery charge together supply the full demand.

## Curtailment

The surplus solar and wind energy that the battery cannot take, because it is full. This energy
is lost.

## Design

One system, given as three numbers: the solar factor, the wind factor and the battery factor.

## Dispatch

The hour-by-hour simulation of one design over the weather year: generation, battery charge,
supplied demand and unmet energy.

## ERA5

The ERA5 reanalysis of the weather, from ECMWF. BOA uses the 0.25 degree grid of the ERA5 data
(`ERA5_DATA_RESOLUTION`) for its pixels, and it uses the ERA5 land-sea mask to select the land
pixels. BOA reads the hourly capacity factors from the Copernicus CDS data set
`sis-energy-global-reanalysis`.

## Filled node

A node of the coarse grid that BOA does not solve. It takes the value of the nearest solved node
with equal or larger solar and wind factors.

## Frontier

The set of designs in which the battery is the minimum battery for the solar and wind factors of
the design. BOA stores designs on the frontier or just above it, only in the patches.

## Frontier cache

The stored results of the search for the pixels of one region. For each pixel, it holds the status
code, the number of patches and widenings, and the coarse grid with its lower bounds. For each
patch node and battery rung, it holds the factors, the coverage and the served fraction. One
cache is for one weather year, region, coverage target and set of search settings. The arrays
contain no cost, no investment year, no load density and no capacity ceiling. The metadata
records the anchors, which are cost coefficients.

## GAMMA

The exponent of the battery factor in the cost of the battery: 0.85, which is 1 plus the battery
scaling factor of −0.15 (see [Model assumptions](model-assumptions.md)). The battery cost per MWh
decreases when the battery duration increases.

## GLOBAL file

The file that combines the per-year files of all regions for one investment year, on one grid.
See [Running the model](running-the-model.md#per-year-output-files).

## Input set

The same as the [weather set](#weather-set).

## Investment horizon

The number of years over which BOA calculates the LCOE: the longest technology lifetime.

## Investment year

The year in which the system is built. It sets the CAPEX that BOA uses.

## Land-sea mask

The ERA5 field that gives, for each pixel, the fraction of land. BOA models a pixel when the
value is more than 0.5.

## LCOE

Levelised cost of electricity: the discounted cost of the system divided by the discounted energy
that the system delivers to the demand, in USD per MWh.

## Load density

The demand for each km² of pixel area, in MW/km². The pixel area is the full area of the grid
cell, land and water. Multiplied by the pixel area, the load density gives the demand of the
pixel.

## Lower bound

A value that the true value cannot be below. On the coarse grid, the lower bound at a node is a
value that the minimum battery at that node cannot be below. The containment check uses the lower
bound on the LCOE that follows from it. A lower bound is infinite when no tested battery meets
the coverage target at the node, or when the corner cut removes the node.

## Minimum battery

For one solar factor and one wind factor, the smallest battery factor `b_min(s, w)` that meets
the coverage target. When `b_min = 0`, the generation alone meets the target. When no tested
battery meets the target, the node is infeasible.

## OPEX

Operating expenditure: the yearly operating cost of a technology. The cost set gives it as a
fraction of the CAPEX.

## Overscale factor

The solar factor or the wind factor: installed capacity divided by the demand. The code also uses
"overscale" for the battery factor. This site does not.

## Patch

A dense grid of designs around a seed. At each patch node, BOA finds the minimum battery. Only
the patch designs go into the frontier cache.

## Patch box

The range of solar and wind factors that one patch covers. It extends from the seed by the larger
of `patch_halfwidth` (default 20 %) of the seed coordinate and `coarse_stride` (default 3) coarse
steps, on each axis. BOA moves each edge outward to the next coarse node.

## Patch node

A node of a patch: a pair of a solar factor and a wind factor. The spacing of the patch nodes is
one coarse step divided by `lattice_refinement` (default 2). At each patch node, the bisection
runs to the full tolerance.

## Per-year file

The NetCDF file of one region and one investment year of one scenario. A scenario is a weather
year, a load density and a coverage target. See
[Running the model](running-the-model.md#per-year-output-files).

## Pixel

One cell of the ERA5 weather grid, 0.25 degrees in latitude and in longitude. BOA models a pixel
when the ERA5 land-sea mask is more than 0.5 (land).

## Promoted LCOE file

One NetCDF file with the LCOE and the status of all investment years of one scenario (weather
year, load density and coverage target) of a run. A run can have one such file for each scenario.
See [The promoted LCOE file](promoted-lcoe-file.md).

## Query

The step that prices the stored designs of one pixel with the cost coefficients of one investment
year and one cost key, and returns the design with the lowest LCOE. It does no dispatch
simulation.

## Region

A rectangle of latitude and longitude that BOA builds and prices as one unit. Together, the
regions cover most land between about 58° S and 72° N.

## Run directory

The directory `<root>/runs/<run label>_<hash>`. The hash is a hash of all search settings and of
the technology lifetimes. A run directory holds `run.json` and the per-year files of the run.
See [Running the model](running-the-model.md).

## Run label

The name of a run: the value of the option `--run`. The run label and the hash form the name of
the [run directory](#run-directory).

## Search box

The range of solar and wind factors, `0 ≤ s ≤ s_max` and `0 ≤ w ≤ w_max`, that the search
examines for one pixel. BOA sets it from the mean capacity factors of the pixel. BOA can double
it (see widening).

## Search settings

The parameters of the search (`SearchParams`): grid sizes, tolerances, the search box and the
battery limit. They are not physical parameters. A change to one of them makes a different
frontier cache.

## Seed

A solved node of the coarse grid where the search looks in detail. BOA ranks the solved nodes
with the seed score of each anchor. It builds one patch for each distinct patch box, at most
`max_patch_slots` (default 4).

## Seed score

The number `a_s·s + a_w·w + a_b·b_lower^GAMMA` of a solved node, for one anchor. It is the
numerator of the LCOE, with the lower bound on the minimum battery. It does not contain the
served fraction.

## Served fraction

The fraction of the annual demand energy that the system supplies.

## Solar factor

The installed solar capacity divided by the demand. It is an
[overscale factor](#overscale-factor).

## Solved node

A node of the coarse grid where BOA runs `coarse_bisect_steps` (default 3) steps of the
bisection. BOA solves every `coarse_stride`-th node (default every third node) on each axis.

## Status code

A number for each pixel that tells whether BOA found a result, and if not, why. See
[Known limitations](known-limitations.md#status-codes) for the meaning of each code.

## Truncation

The query reports truncation (`argmin_truncated`) when the result is on an edge of its patch that
is inside the coarse grid. An edge at `s = 0`, at `w = 0`, or at the outer edge of the coarse
grid does not count. A cheaper design can be just outside the patch. The output files do not
record the result.

## Unmet energy

The part of the demand that neither the generation nor the battery supplies in an hour. BOA gives
it no cost, and no other source supplies it.

## Weather set

The profile stores of one weather year under `<root>/inputs/<set>/`, for example `cds-2024`. The
option `--weather-input` selects it. The code and some output attributes call it the input set
(`input_set`). An input set holds one weather year.

## Weather year

The calendar year of the hourly capacity factors that BOA uses.

## Widening

The doubling of the search box (up to `box_abs_max`) when a seed is on the outer edge of the
coarse grid or next to the corner cut. BOA then selects the seeds again. It does this at most
`max_box_widenings` times (default 2).

## Wind factor

The installed wind capacity divided by the demand. It is an
[overscale factor](#overscale-factor).
