# Known limitations

This page tells you what BOA does not model, how close its results are to the true optimum, and
what each status code means for a pixel. Each section says what the limit means for a result. The
[glossary](glossary.md) defines the terms.

BOA gives, for each pixel, the lowest-cost design that the search found for one weather year, one
[coverage target](glossary.md#coverage-target) and one set of costs. The sections below list where
this differs from the cost to supply a real baseload demand at that pixel.

| Limit | Effect on a result | Section |
|---|---|---|
| BOA does not apply the capacity ceiling | The design can need more land than the pixel has. The true unconstrained optimum has an [LCOE](glossary.md#lcoe) at or below the LCOE with a ceiling. | [Capacity ceiling](#the-capacity-ceiling-is-not-applied) |
| One weather year for all years of the horizon | The result has no year-to-year variation of the weather and no degradation. | [One weather year](#one-weather-year-and-no-degradation) |
| No grid, no transmission, no other source | The LCOE is the cost for each MWh delivered. Unmet demand has no cost. | [Scope of the system](#scope-of-the-system) |
| Simple battery model | Battery support is more favourable than for a real battery. | [Battery model](#battery-model) |
| Pixels without a result | The LCOE is NaN (regional and global files) or 0 (single-point run). | [Status codes](#status-codes) |
| Region extent | No result for land outside the region boxes: north of 72° N, south of 58° S, Greenland between 50° W and 25° W, and many island groups. | [Region extent](#region-extent) |
| The search finds a low-cost design, not always the lowest | The LCOE can be higher than the true minimum. | [Search precision](#search-precision) |
| The frontier cache depends on how it was built | The same query can give different results after a rebuild. | [Reuse of the frontier cache](#reuse-of-the-frontier-cache) |
| Input assumptions and fallbacks | Some inputs have no source or use a fallback value. | [Inputs and costs](#inputs-and-costs) |

## The capacity ceiling is not applied

The **capacity ceiling** is the largest solar and wind capacity that the available land of a
pixel can hold. The input pipeline can build it: it is the area of the pixel, multiplied by a power
density in MW/km² and by a land-availability fraction. The search and the query do not apply it.
The single-point run reads the ceiling store and computes a limit from it, but it does not use
the limit in the search. Each per-year file records `capacity_ceiling_applied = 0`, and the
promoted file carries this attribute (see [Promoted LCOE file](promoted-lcoe-file.md)). The query
writes a warning to the log each time that it computes a region and year.

**What it means for a result.** BOA gives the unconstrained optimum. The design can need more
land than the pixel has. The design is the solar, wind and battery factors multiplied by the
demand in MW. A solar or wind factor is an *overscale factor*: the installed capacity divided
by the demand.

The LCOE of the true unconstrained optimum is at or below the LCOE of the same pixel with a
ceiling. The value that BOA reports is the best design that the search found (see
[Search precision](#search-precision)). It is not always the true optimum. Thus the reported LCOE
can be above the LCOE of a design with a ceiling. Do not use the design as a statement about
capacity that can be built.

**Load density.** The LCOE does not change with the [load density](glossary.md#load-density). The
search works with a demand of 1. The load density only scales the reported values in MW and USD
(see [Overview](overview.md)). The result is exact apart from rounding in the last digits of the
floating-point numbers.

This depends on the missing ceiling. The ceiling in MW is the same for all load densities, but
the demand of a pixel increases with the load density. With a ceiling, a high load density would
limit the design, and the LCOE would change with the load density. BOA does not show this effect.

## One weather year and no degradation

Each run uses the profiles of one weather year. An input set holds exactly one weather year.
BOA repeats this year for each year of the investment horizon. The horizon is 25 years, the
longest technology lifetime in `LIFETIMES` (see [model assumptions](model-assumptions.md)).

The hourly output of solar, wind and battery is the same in all years of the horizon, because
BOA has no degradation term. The rates in `YEARLY_DETERIORATION_RATES` are not used in the LCOE
calculation.

**What it means for a result.**

- The result is for the weather of that year. A year with more or less wind or sun gives another
  result. BOA does not calculate the spread between years.
- The coverage target applies to this one year. A system that meets the target in the weather
  year can have a lower coverage in another year.
- Solar, wind and battery output does not decrease with age. This makes the LCOE lower than with
  degradation.

## Scope of the system

BOA models one pixel at a time. Each pixel supplies its own baseload demand from its own solar,
wind and battery. The model has no grid, no transmission between pixels, no other source of
electricity and no demand that changes with the hour.

**Unmet demand has no cost.** The coverage target is a fraction of the hours of the year. In an
hour that is not fully covered, the system supplies part of the demand or none. BOA does not
supply the rest from another source and does not add a cost for it.

The LCOE divides the cost of the system by the energy that it delivers (the
[served fraction](glossary.md#served-fraction)), not by the full demand. Thus the result is the
lowest cost for each MWh delivered at the coverage target. It is not the lowest cost to supply the
full demand. A design that delivers less energy can have a lower LCOE.

**What `lcoe_coverage_based` means.** The per-year file has the variable `lcoe_coverage_based`.
It is `lcoe × served_fraction`: the cost of the system for each MWh of the full demand. The unmet
energy is `1 − served_fraction` of the demand, and it is at most `1 − coverage`. The variable does
not contain the cost of the unmet energy. It also does not contain the cost of the capacity that
another source needs for the hours that the system does not cover. BOA has no model of that source.
See [Per-year output files](running-the-model.md#per-year-output-files) for the variable and
[Coverage and served fraction](overview.md#coverage-and-served-fraction) for the meaning.

## Battery model

The dispatch simulation ([Methodology](methodology.md)) uses a simple battery:

- The battery has no limit on the charge power and no limit on the discharge power. It can take
  all surplus of one hour, and it can supply the full demand in one hour while it has energy.
- The battery has no round-trip loss and no self-discharge.
- The battery is empty at the start of the year. BOA does not require the charge at the end of
  the year to be equal to the charge at the start.
- The battery cost depends only on the energy capacity (MWh). There is no cost for the power
  rating.
- The lifetime of the battery is 25 years, equal to the lifetime of solar and wind. This value
  has no outside source (see [model assumptions](model-assumptions.md)). With a lifetime that
  is equal to the investment horizon, the cost has no battery replacement.

**What it means for a result.** The battery support in the model is more favourable than for a
real battery, and the battery cost is lower. Thus a design can have a smaller battery and a lower
LCOE than a real system with the same coverage. The empty start has the opposite, small effect:
the battery is empty in the first hours, so the design needs a slightly larger battery or more
generation. If the real battery lifetime is shorter than 25 years, the real cost is higher than
the cost in the model.

## Status codes

Each pixel of a per-year file, and of the promoted file, has a status code. This table is the
reference for all codes. The names are the labels in `STATUS_CODES` (`boa.config.constants`).

| Code | Name | Meaning for a pixel | Result variables in a per-year file |
|---|---|---|---|
| 0 | Not modelled | BOA did not compute the pixel. It is sea, or it is outside all regions (see [Region extent](#region-extent)). A land pixel is a grid cell where the ERA5 land-sea mask is larger than 0.5. | All NaN. `cost_key` is empty. |
| 1 | Optimum found | The search found a design that meets the coverage target. The design is the best design that the search found, not always the exact optimum (see [Search precision](#search-precision)). | All set. |
| 2 | Simulated, no usable optimum | The search found no design that meets the coverage target in the range that it examined. See below. | Design, LCOE, `lcoe_coverage_based`, installation cost, `coverage` and `served_fraction` are NaN. `cost_key`, `cost_of_capital` and `load_mw` are set. |
| 3 | Zero solar and wind potential | The capacity factors of solar and wind are zero in all hours. No design can supply the demand. | As for code 2. |
| 4 | Retired (was: fragile optimum rejected by minimum-survivor cut) | The code does not set it. A file that BOA made with the earlier search method can contain it. That method used a frontier cache of schema version 2, which the current code does not accept. In that method, code 4 marked an optimum that the search rejected as fragile. Do not read it as one of the codes above. | — |
| 5 | Unallocated | The code does not set it. It has no entry in `STATUS_CODES`. | — |
| 6 | Reserved | The code does not set it. It is reserved for a pixel that has no feasible design under the capacity ceiling. The ceiling is not applied, so BOA cannot set it (see [above](#the-capacity-ceiling-is-not-applied)). It has no entry in `STATUS_CODES`. | — |

`status_legend` in the promoted file lists the codes 0 to 4. It does not list 5 and 6. The legend
text for code 4 contains the words "minimum-survivor cut", from the earlier search method.

BOA sets the status code when it builds the frontier cache. It depends on the profiles, the
coverage target and the search settings, not on the investment year or on the costs. The
promoted file requires the same status in all years.

**Status 2.** The range that BOA examines for a pixel is the search box. It excludes the corner
in which the solar and the wind factor are both large. It includes batteries up to 256 hours of
demand.

In the search, the tested battery sizes are 0.25, 0.5, 1, 2 hours and so on. 256 hours is the
largest of these sizes that is not above the battery limit `b_cap` of 500 hours. BOA sets the
search box from the mean capacity factors of the pixel. The search settings set the size of the
box, the corner and `b_cap` (see [Methodology](methodology.md)).

Thus status 2 does not mean that no system can meet the target at the pixel. It means that BOA
found no feasible design in its range. A change of the box settings, the corner or `b_cap` can
change a pixel from status 2 to status 1, and the other way.

**Pixels without a result.** The LCOE of a pixel with status 0, 2 or 3 is NaN in a regional file,
a global file and the promoted file. A NaN is not a zero cost. A single-point run behaves
differently: for a status other than 1, it reports 0 for the design, the LCOE,
`lcoe_coverage_based`, the installation cost, `coverage`, `served_fraction` and the cost of
capital. Do not read this 0 as free power. The single-point run also reports the status.

**Single-point run and status 0.** The single-point run decides whether a location is land with
the country grid, not with the ERA5 land-sea mask. For a sea point, or a point that has no country
in the grid, it stops with an error. It never returns status 0. It does not use the frontier
cache: it builds the frontier of the one pixel with the costs of that pixel.

## Search precision

The result of a pixel is the lowest-cost design among the designs that the build stored, priced
with the costs of the investment year ([`argmin_lcoe`][boa.model.bisection.argmin_lcoe]). It is
not the exact optimum of the problem in [Methodology](methodology.md). The difference has these
causes:

- **Patch resolution.** The query prices only the nodes of the patches. A better design between
  two nodes is not found.
- **Battery tolerance and one battery rung.** The build stores, for each node, the smallest
  battery that meets the target, with a relative tolerance of 1 %. With the default search
  settings, it stores no larger battery. A larger battery that gives a lower LCOE is not found.
- **Seeds.** The patches are around the seeds. BOA ranks the seeds with a score that uses the
  cost of the design and a lower bound of the battery, and it does not use the served fraction.
  The served fraction can be between the coverage target and 1. This band is wide at a low
  coverage target. Thus a region of low cost can get no seed and no patch. BOA does not search
  that region. The [Overview](overview.md) shows an example: on a synthetic pixel, the
  LCOE decreases at some steps when the coverage target increases.
- **Search box and battery limit.** BOA does not evaluate designs outside the search box, in the
  corner, or with a battery above 256 hours.

**What it means for a result.** The LCOE is at or above the lowest LCOE of the pixel. The size
of the difference depends on the pixel and on the coverage target, and BOA does not report it.
The LCOE can change in steps when the coverage target changes. Do not compare small differences
in LCOE between pixels or between coverage targets as properties of the pixels.

**The containment check.** For each result, BOA checks whether a coarse-grid cell outside the
patches can have a lower LCOE. The `Optimum` result has two diagnostics from this: `patch_certified`
(no cell outside the patches can be cheaper) and `argmin_truncated` (the result is on an inner
edge of its patch). The per-year files do not contain them. The log of each query gives the share
of pixels with each diagnostic. BOA does not search again for a pixel that the check does not
confirm, and it publishes the result. A confirmed result is not always the optimum: the check
covers only the area outside the patches, and inside a patch the node spacing limits the
accuracy. The check treats a cell in the corner cut or above the battery limit as not cheaper,
because BOA does not evaluate these cells.

## Reuse of the frontier cache

The frontier cache has the dispatch results, and no costs. But the **anchors** (sets of cost
coefficients) decide where the build puts the patches, and thus which designs the cache contains
(see [Methodology](methodology.md#cost-anchors) and
[`anchors_for_build`][boa.model.anchors.anchors_for_build]). This gives these limits:

- **A rebuild can change an earlier result.** When a run has cost mixes that the anchors of a
  stored cache do not cover, BOA builds the cache again with more anchors. The new cache can have
  other patches. The LCOE for an earlier cost set and investment year can then be different.
- **Per-year files are not refreshed.** A command that finds the file of a year skips that year,
  unless you force a new calculation. After a cache rebuild without this, the per-year files in a
  run can come from different caches. The files do not record the build time or the anchors of the
  cache. The promotion step cannot find this. See
  [Rebuild a frontier cache](running-the-model.md#rebuild-a-frontier-cache).
- **The query does not check the anchors.** The query step uses the cache that it finds. The
  cache path contains the weather year, the region, the coverage target and the search settings.
  It does not contain the cost set or the years. A cache from another cost set or another range
  of years is used without a warning. The anchor check runs in the commands that build the cache
  (see [Rebuild a frontier cache](running-the-model.md#rebuild-a-frontier-cache)). Pixels that
  the anchors do not cover get results that the check confirms less often. The LCOE can be higher
  than with covering anchors.
- **A full cache is used again.** A cache with `max_anchors` anchors (32 by default) is used
  again when it does not cover the cost mixes of the run. BOA writes a warning.
- **The global-average costs are not an anchor candidate.** The anchors cover the cost keys in
  the cost set. A pixel whose country is not a cost key, or that has no country, is priced with
  the mean costs of all cost keys (see [Inputs and costs](#inputs-and-costs)). No anchor covers
  the cost mix of these mean costs.
- **The cache identity is the weather-year label.** BOA does not compare the content of the
  profiles or of the land-sea mask. A new profile build for the same year, or a changed land-sea
  mask, uses the old cache without a warning.

## Inputs and costs

**Battery cost scaling.** BOA multiplies the CAPEX of the battery in the cost set by
`(b / 4)^−0.15`, where `b` is the battery size in hours of demand
(`BATTERY_UNIT_CAPEX_SCALING_FACTOR = −0.15`). Thus the battery cost increases with `b` to the
power `GAMMA = 1 − 0.15 = 0.85`. The factor has no outside source (see
[model assumptions](model-assumptions.md)). It depends on the duration of the battery in hours
of demand, not on the absolute size in MWh: a battery of 8 hours has the same unit cost at a
demand of 1 MW and of 1000 MW. The value 4 hours is `AVERAGE_IMPLIED_STORAGE`. It means that BOA
uses the CAPEX in the cost set as the price of a battery with a duration of 4 hours. Nothing in
the code checks this. The power law has no lower and no upper limit for `b`:

| Battery size `b` (hours of demand) | Unit cost, as a multiple of the CAPEX in the cost set |
|---|---|
| 0.1 | 1.74 |
| 1 | 1.23 |
| 4 | 1.00 |
| 8 | 0.90 |
| 24 | 0.76 |
| 100 | 0.62 |
| 256 | 0.54 |
| 500 | 0.49 |

**What it means for a result.** The cost of a design with a long-duration battery depends on this
assumption. If the CAPEX in the cost set is not the price at 4 hours, the battery cost is
different by the same factor.

**Cost fallbacks.** BOA gives each pixel a cost key (see [glossary](glossary.md#cost-key)). The
fallbacks work at two times.

When BOA reads the cost workbook, each country in the Country mapping gets a full set of costs:

- CAPEX comes from the exact cost key. If the workbook has no row for it, CAPEX comes from the
  country row. If it has none, CAPEX comes from the row of the IRENA region of the country. If it
  has none, CAPEX comes from the IRENA region with the highest total CAPEX for that technology.
  BOA writes a warning for this last case.
- OPEX comes from the row of the IRENA region of the country. If the workbook has no such row,
  OPEX comes from the World row.
- When the cost set has no cost of capital for a country, BOA uses the highest cost of capital in
  the cost set. A province has no cost of capital of its own: it uses the value of its country.

When BOA gives a pixel its cost key, it uses these rules:

- When the cost set has no costs for the province of the pixel, BOA uses the costs of the country.
- When the country of the pixel is not a cost key (it is not in the Country mapping), BOA uses the
  mean CAPEX, OPEX and cost of capital of all cost keys in the cost set. The `cost_key` is then
  `<ISO3>:GLOBAL_AVG`.
- When BOA finds no country for the pixel, it also uses the mean costs. The `cost_key` is then
  `UNKNOWN:GLOBAL_AVG`.

BOA writes the number of pixels with a fallback to the log. The `cost_key` variable of the output
shows the key that BOA used. A key that ends in `:GLOBAL_AVG` shows that BOA used the mean costs.

**Rounding.** The frontier cache stores the served fraction with a step of 1/65 535, rounded down.
The stored LCOE can be higher than the exact value, by at most about 0.0015 % for a served
fraction near 1. The cache stores the coverage with the nearest step, and the output `coverage` can be slightly below
the coverage target: for a target of 0.95, a file can show 0.94999. The design always meets the
target in the search.

## Region extent

BOA computes the land pixels in the boxes of `REGION_COORDS` (`boa.config.physical_parameters`).
The boxes lie between 72° N and 58° S. They do not cover all land. A land pixel outside all boxes
has status 0. This includes:

- Antarctica, and land south of 58° S;
- land north of 72° N;
- Greenland between 50° W and 25° W;
- Chukotka east of 180° (longitudes −180° to −170°), because the box `ALASKA` starts at −170°;
- many island groups that are in no box, for example the Azores, Cape Verde, the Maldives, the
  Seychelles, Tonga, Samoa, French Polynesia, Easter Island and the Chatham Islands.

In addition, a coastal grid cell where the ERA5 land-sea mask is 0.5 or lower is a sea pixel, and
has status 0.

A single-point run for a land location outside all boxes does not give status 0. It uses the
weather of the nearest region box in the same hemisphere, and it writes a warning with the
distance. The result is for the weather of that other grid cell.
