# Methodology

This page gives the exact optimisation problem that BOA solves for each pixel: the objective,
the constraint and the hourly [dispatch](glossary.md#dispatch) rules. It also explains how the
search finds the optimum, how close the result is to the true optimum, and which parameters are
[search settings](glossary.md#search-settings).

The [Overview](overview.md) introduces the concepts that this page uses. The
[model assumptions](model-assumptions.md) page gives the physical parameters and their sources.
[Known limitations](known-limitations.md) describes the limits of the method and their effect on
the results. The [Glossary](glossary.md) defines each technical term. The first use of each term
on this page links to the glossary.

## The design

BOA describes a system with three numbers that are relative to the demand of the pixel. The
demand is set to 1 in each hour.

| Symbol | Name | Unit |
|---|---|---|
| `s` | Solar factor | MW of installed solar capacity per MW of demand |
| `w` | Wind factor | MW of installed wind capacity per MW of demand |
| `b` | Battery factor | Battery energy capacity, in hours of demand |

The search and the stored results use only these relative numbers. The
[load density](glossary.md#load-density) (MW/km²) enters only at the
[query](glossary.md#query). The demand of a pixel in MW is the load density multiplied by the
area of the pixel. This demand sets the absolute size of the design (MW, MWh) and its installation
cost.

## Dispatch rules

The dispatch is the hour-by-hour simulation of one design over the weather year. The inputs are
the hourly capacity factors `S[t]` (solar) and `W[t]` (wind) of the pixel. The hours of the
weather year are `t = 1 … T`. The function is
[`dispatch_metrics`][boa.model.bisection.dispatch_metrics].

The battery charge `q[t]` is the charge at the end of hour `t`, in hours of demand. The battery
is empty at the start: `q[0] = 0`. In each hour:

1. The generation is `g[t] = s·S[t] + w·W[t]`, and the net generation is `n[t] = g[t] − 1`.
2. The available energy is `a[t] = q[t−1] + n[t]`. The hour is
   [**covered**](glossary.md#covered-hour) when `a[t] ≥ 0`: the generation and the battery charge
   together supply the full demand.
3. The new charge is `q[t] = min(max(a[t], 0), b)`.
4. When `n[t] ≥ 0`, the surplus charges the battery by `q[t] − q[t−1]`. The remaining surplus
   is [**curtailed**](glossary.md#curtailment): it is lost, because the battery is full.
5. When `n[t] < 0`, the battery supplies `q[t−1] − q[t]`, which is the smaller of the deficit
   `−n[t]` and the charge `q[t−1]`. The demand that the battery cannot supply is the
   [**unmet energy**](glossary.md#unmet-energy) `u[t] = −n[t] − (q[t−1] − q[t])`.

At the end of the year:

```text
coverage        = (number of covered hours) / T
served fraction = 1 − (u[1] + … + u[T]) / T
```

[Coverage](glossary.md#coverage) is the fraction of hours in which the system supplies the full
demand. The [served fraction](glossary.md#served-fraction) is the fraction of the annual demand
energy that the system supplies.

These rules have these properties:

- The battery has no charge power limit and no discharge power limit. Only its energy capacity
  `b` is a limit. The battery can supply at most the deficit of the hour, which is at most 1.
- The battery has no round-trip loss and no self-discharge.
- The battery is empty at the start of the year. The charge at the end of the year does not
  go back to the start.
- There is no grid connection and no other source of electricity.
- An hour with only part of the demand supplied is not covered, but it adds its supplied part to
  the served fraction. Thus the served fraction is always equal to or larger than the coverage.
- More solar, more wind or a larger battery never decreases the charge in any hour. Thus the
  coverage cannot decrease when `s`, `w` or `b` increases. The search uses this property.

[Known limitations](known-limitations.md) describes the effect of this battery model on the
results.

![Two stacked charts for three days at one synthetic pixel. The top chart shows, for each hour, how the energy goes: wind and solar to the demand, battery discharge to the demand, unmet demand, surplus that charges the battery, and curtailed surplus. The bottom chart shows the battery charge, the battery capacity, and shaded hours that are not covered.](assets/methodology/f3_dispatch_rules.svg)

**Figure 1.** The dispatch rules for three days at one synthetic pixel with strong sun and some
wind. The synthetic profile has three weeks (504 hours), and the figure shows 72 of these hours.
The design is the result of the search for cost set A of the figure script, at a
[coverage target](glossary.md#coverage-target) of 0.85. The costs of cost set A are illustrative.
Below the demand line, each hour shows where the supplied energy comes from: wind, solar, or
battery discharge. The pink part is the unmet demand of the hour. Above the demand line, the
hatched part is the surplus that charges the battery, and the grey part is the curtailed surplus.
Curtailment occurs only when the battery is full. The unmet hours are at the end of each night,
when the battery is empty. The profiles are synthetic, from the generators in the test fixtures.
The script is `docs_figures/methodology_figures.py`.

## The optimisation problem

For each pixel, each coverage target `c` and each investment year, BOA looks for the design
with the lowest levelised cost of electricity (LCOE):

```text
minimise    LCOE(s, w, b) = (a_s·s + a_w·w + a_b·b^GAMMA) / (d0 · served_fraction(s, w, b))
subject to  coverage(s, w, b) ≥ c
            s ≥ 0,  w ≥ 0,  b ≥ 0
```

- The coverage target `c` is the lowest coverage that a design must have. It is a fraction with
  `0 < c < 1`. Other values stop the run with an error.
- `coverage` and `served_fraction` come from the dispatch rules above.
- `a_s`, `a_w`, `a_b` and `d0` are the four [**cost coefficients**](glossary.md#cost-coefficients)
  of one investment year and one [cost key](glossary.md#cost-key)
  ([`CostCoefficients`][boa.model.bisection.CostCoefficients], calculated by
  [`lcoe_coefficients`][boa.model.cost_calculations.lcoe_coefficients]). `a_s`, `a_w` and `a_b`
  are the discounted lifetime costs of one unit of each factor. `d0` is the discounted demand
  energy over the investment horizon.
- [`GAMMA`](glossary.md#gamma) is 0.85: `1 + BATTERY_UNIT_CAPEX_SCALING_FACTOR`, with the scaling
  factor −0.15 (see [model assumptions](model-assumptions.md)). The battery cost is not
  proportional to `b`: the cost per MWh decreases when the battery duration increases.

The LCOE is the cost for each MWh that the system delivers to the demand. The unmet energy is
`1 − served fraction` of the annual demand. It has no cost in the objective, and no other source
supplies it.

??? note "The cost coefficients"
    For one cost key with cost of capital `r`, the discount factor of year `t` is
    `δ[t] = 1 / (1 + r)^t`. The investment horizon `H` is the longest technology lifetime. For
    each technology `x` (solar, wind, battery), with OPEX `o_x` as a fraction of CAPEX and CAPEX
    `C_x` in the investment year (USD/MW for solar and wind, USD/MWh for the battery):

    ```text
    weight_x = 1 + o_x · (δ[1] + … + δ[L_x])        L_x = lifetime of x
    a_s = D · weight_solar   · C_solar
    a_w = D · weight_wind    · C_wind
    a_b = D · weight_battery · C_battery · 4^(1 − GAMMA)
    d0  = D · 8760 · (δ[1] + … + δ[H])
    ```

    `D` is the demand of the pixel in MW. The factor `4^(1 − GAMMA)` makes
    `a_b · b^GAMMA = D · b · weight_battery · C_battery · (b / 4 h)^−0.15`. The correction
    factor `(b / 4 h)^−0.15` is 1 for a battery of 4 hours of demand
    (`AVERAGE_IMPLIED_STORAGE`). It changes the battery CAPEX per MWh with the power −0.15
    of the duration.

    With the lifetimes in [model assumptions](model-assumptions.md) (25 years for each
    technology), the horizon is equal to each lifetime, and there is no reinstallation term.
    The energy of each year is the same. One weather year applies to each year of the horizon,
    and the output does not decrease with age.

**Load density.** Each cost coefficient is proportional to the demand `D`. In the LCOE, `D`
cancels. Thus the LCOE and the selected design do not change with the load density, apart from
floating-point rounding. This is true because no capacity ceiling applies when BOA selects a
design: each per-year file records `capacity_ceiling_applied = 0`. See
[Known limitations](known-limitations.md).

**The frontier.** For a fixed solar and wind factor, the coverage cannot decrease when the
battery increases. Thus there is a smallest battery `b_min(s, w)` that meets the coverage target.
We call it the [**minimum battery**](glossary.md#minimum-battery). We call the set of these
designs the [**frontier**](glossary.md#frontier). A design with `b < b_min(s, w)` does not meet
the target. When `b_min = 0`, the generation alone meets the target.

![Two heat maps over the plane of solar factor and wind factor for one synthetic pixel. The left map shows the minimum battery that meets the coverage target, with contour lines at 0.5, 1, 2, 4 and 8 hours, a grey region where no battery of 256 hours or less meets the target, and a white region where no battery is needed. The right map shows the LCOE of each of these designs as an index. The lowest values form a narrow valley along the edge of the grey region, with a minimum on the solar axis and a second low region near a solar factor of 3 and a wind factor of 0.6.](assets/methodology/f5_frontier.svg)

**Figure 2.** The frontier of one synthetic pixel (the pixel of Figure 1, coverage target 0.85).
(a) The minimum battery `b_min(s, w)`. In the grey region, no battery of 256 hours or less meets
the target. For a solar factor of 1 or more, the generation alone meets the target above a wind
factor of about 4.4. With no solar, this wind factor is about 4.9. The dashed line is the
[corner cut](glossary.md#corner-cut) of the search (see below). (b) The LCOE of the design with
the minimum battery, for cost set A of the figure script. It is an index: the minimum on the
reference grid is 100. The low-cost designs are in a narrow valley along the edge of the grey
region. The valley has more than one low point. The diamond is the result of the search: its LCOE
is 1.0 % above the minimum on the reference grid (the star). The reference grid has 97 × 97
nodes. This is half the node spacing of the search [patches](glossary.md#patch). The battery
tolerance of the reference grid is 0.01 %. The profiles and the costs are synthetic. The script is
`docs_figures/methodology_figures.py`.

## The search

BOA does not evaluate all designs. It evaluates a finite set of designs on grids in the plane of
the solar and wind factors. It stores their dispatch results in the
[frontier cache](glossary.md#frontier-cache). Each stored design is on the frontier or just above
it. Its battery is the `b_min` that the [bisection](glossary.md#bisection) finds (see
[below](#the-minimum-battery-by-bisection)), or a [battery rung](glossary.md#battery-rung) above
it.
Thus each stored design meets the coverage target. The query then selects the cheapest stored
design.

[`build_pixel_frontier`][boa.model.bisection.build_pixel_frontier] does the search for one
pixel. It uses no random numbers: the same inputs give the same result.

### 1. Zero potential

When the solar and the wind capacity factors are zero in all hours, the search stops. The pixel
gets [status code](glossary.md#status-code) 3.

### 2. The search box

The search looks only at designs inside the [**search box**](glossary.md#search-box)
`0 ≤ s ≤ s_max`, `0 ≤ w ≤ w_max` ([`search_box`][boa.model.bisection.search_box]). The box comes
from the mean capacity factor `CF` of each technology over the weather year:

```text
s_max = clip(box_multiple · k / CF_solar, box_min, box_abs_max)      k = 0.75
w_max = clip(box_multiple · k / CF_wind,  box_min, box_abs_max)
```

With the default settings, the box is `3 / CF`, but at least 2 and at most 200. A technology
with a zero capacity factor gets `box_abs_max`, which is 200.

### 3. The coarse grid

The [**coarse grid**](glossary.md#coarse-grid) has `coarse_grid × coarse_grid` nodes (25 × 25),
evenly spaced in the box ([`coarse_b_min_grid`][boa.model.bisection.coarse_b_min_grid]). At each
node, the coarse grid holds a [**lower bound**](glossary.md#lower-bound) on `b_min`, not `b_min`
itself:

- BOA solves only every `coarse_stride`-th node on each axis (every third node, 9 × 9
  [**solved nodes**](glossary.md#solved-node)). At a solved node, the
  [bisection](glossary.md#bisection) (see [below](#the-minimum-battery-by-bisection)) stops after
  `coarse_bisect_steps` steps (3). It keeps the infeasible end of the interval, which is a lower
  bound on `b_min` at that node.
- `b_min` cannot increase when `s` or `w` increases. Thus each solved node takes the largest
  lower bound of all solved nodes with equal or larger `s` and `w`. Each other node is a
  [**filled node**](glossary.md#filled-node). It takes the value of the nearest solved node with
  equal or larger `s` and `w`.
- When no battery up to the tested limit meets the target at a solved node, the bound is
  infinite. This propagates to all nodes with equal or smaller `s` and `w`.

**Corner cut.** Nodes where `s/s_max + w/w_max > corner_cut_threshold` (1.2) get an infinite
bound ([`corner_cut_mask`][boa.model.bisection.corner_cut_mask]). The cut removes the corner of
the box where both factors are large. It does not touch the axes `s = 0` and `w = 0`.

### 4. Seeds

A [**seed**](glossary.md#seed) is a solved coarse node where the search looks in detail. BOA
ranks the solved nodes with a [**seed score**](glossary.md#seed-score) for each cost
[**anchor**](glossary.md#anchor). An anchor is one set of cost coefficients that the build uses
to rank the seeds (see [Cost anchors](#cost-anchors)). The function is
[`anchor_score`][boa.model.bisection.anchor_score]:

```text
score(s, w) = a_s·s + a_w·w + a_b·b_lower^GAMMA
```

This is the numerator of the LCOE, with the lower bound `b_lower` from the coarse grid. The score
does not contain the served fraction, because the coarse grid does not calculate it. Thus the
order of the scores can be different from the order of the LCOE values, when the served
fractions of two designs are different.

For each anchor, [`select_seeds`][boa.model.bisection.select_seeds] keeps the node with the
lowest score. It also keeps each node with a score within `seed_tolerance` (5 %) of the lowest.
This node must be at least two solved nodes away from each seed already kept (Chebyshev
distance). There are at most `max_seeds` (3) seeds for each anchor. The separation rule sends the
seeds to different low regions of the plane. This is necessary, because a solar-heavy design and
a wind-heavy design can have almost the same cost.

BOA joins the seeds of all anchors. Seeds that give the same patch box (see step 6) count once,
with the lowest score of the anchors that proposed them. BOA sorts the boxes by this score and
keeps the first `max_patch_slots` (4).

When no solved node that the corner cut keeps has a finite bound, there is no seed. The pixel
gets status code 2, and the search stops.

### 5. Widening

A seed can be on the outer edge of the coarse grid (`s = s_max` or `w = w_max`), or next to the
corner cut. Then the optimum can be outside the box. In this case, BOA doubles `s_max` and
`w_max` (up to `box_abs_max`) and does steps 3 and 4 again. This is
[**widening**](glossary.md#widening). BOA does it at most `max_box_widenings` times (2). The
stored `box_widenings` gives the number of widenings. Widening occurs only when there is a seed:
a pixel with no seed in the first box is not widened.

### 6. Patches

Around each seed, BOA builds a [**patch**](glossary.md#patch): a dense grid of designs
([`patch_lattice`][boa.model.bisection.patch_lattice]).

- The [**patch box**](glossary.md#patch-box) extends from the seed by the larger of
  `patch_halfwidth` (20 %) of the seed coordinate and `coarse_stride` (3) coarse steps, on each
  axis ([`patch_bounds_for_seed`][boa.model.bisection.patch_bounds_for_seed]).
- BOA moves each edge of the patch box outward to the next coarse node. Thus each coarse node is
  either inside a patch box or outside all patch boxes.
- The [**patch nodes**](glossary.md#patch-node) have a fixed spacing of one coarse step divided
  by `lattice_refinement` (2). With the default settings, this is `box / 48` on each axis.

At each patch node, the bisection runs to the full tolerance and gives `b_min`, its coverage and
its served fraction ([`b_min_at`][boa.model.bisection.b_min_at]). When no battery up to the
tested limit meets the target, the node is infeasible, and the query does not use it.

### 7. Battery rungs

At each feasible patch node, BOA stores the dispatch results for `ladder_rungs`
[**battery rungs**](glossary.md#battery-rung). These are battery sizes from `b_min` to
`ladder_max_span · b_min` ([`battery_rungs`][boa.model.bisection.battery_rungs]). The default is
one rung: BOA stores only `b_min`. Thus the query does not evaluate a battery larger than
`b_min`, even if a larger battery with a higher served fraction has a lower LCOE.

When the patches are complete, the pixel gets status code 1.

![Two scatter plots over the plane of solar factor and wind factor for one synthetic pixel. The left plot shows the 25 by 25 coarse grid, coloured by the lower bound on the battery, with the 9 by 9 solved nodes drawn larger, crosses where the lower bound is infinite, the corner-cut line, and the seeds of three cost anchors. The right plot shows a detail with three dashed patch boxes, the patch nodes coloured by their minimum battery, and three stars for the cheapest stored design under each cost set.](assets/methodology/f6_search_stages.svg)

**Figure 3.** The search stages for the pixel of Figure 1 at coverage target 0.85, built with
three synthetic cost anchors A, B and C. (a) The coarse grid. Large squares are the solved
nodes, small squares the filled nodes. White squares have a lower bound of zero. Crosses mark
nodes with an infinite bound: in the lower left, no feasible battery; in the upper right, the
corner cut. Anchor A proposes two seeds. Anchor B proposes the same solar-only seed as anchor A
(the square hides the circle). Anchor C proposes a wind-only seed. (b) The three patch boxes and
their nodes, and the cheapest stored design under each of the three cost sets. Each cost set
selects a different design. For cost set C, the
[containment check](glossary.md#containment-check) (`patch_certified`) is true. For cost sets A
and B it is false. For A, the winner is on an inner edge of its patch, so
[`argmin_truncated`](glossary.md#truncation) is true. The profiles and the costs are synthetic.
The script is `docs_figures/methodology_figures.py`.

### The minimum battery by bisection

At one node `(s, w)`, BOA finds `b_min` in two parts:

1. **Bracket.** When the coverage with no battery meets the target, `b_min = 0`. Otherwise BOA
   tests the batteries 0.25, 0.5, 1, 2, … hours, each twice the one before, while the battery
   is not more than `b_cap` (500 hours). The first battery that meets the target is the upper
   end of the interval, and the one before is the lower end. This interval is the
   [**bracket**](glossary.md#bracket). When no tested battery meets the target, the node is
   infeasible.
2. **Bisection.** BOA halves the bracket until its width is at most `tol_rel_patch` (1 %) of
   the upper end, with a minimum of 10⁻⁶ hours. It keeps the upper end, which meets the target.

At the solved coarse nodes and at the patch nodes, the bracket can start from a neighbour node
in the same grid instead of 0.25 hours. The start value is the result of that neighbour. When
that battery meets the target, BOA halves it until a battery does not meet the target. When it
does not, BOA doubles it while the battery is not more than `b_cap`.

Thus a stored `b_min` meets the coverage target. It is at most about 1 % above the
smallest battery that meets the target at that node. Without a start value, the largest battery
that the bracket tests is 256 hours, because the next doubling (512 hours) is more than
`b_cap`. A node that needs a battery between 256 and 500 hours is thus infeasible when the test
starts at 0.25 hours.

### Cost anchors

An anchor is one set of cost coefficients that the build uses to rank the seeds. The anchors are
the only path from the costs into the build.

- The [**candidates**](glossary.md#candidate) are all pairs of an investment year of the run and
  a cost key of the cost set. Each candidate has its cost coefficients at a demand of 1
  ([`cost_candidates`][boa.model.anchors.cost_candidates]).
- BOA normalises the [**cost mix**](glossary.md#cost-mix) `(a_s, a_w, a_b)` of each candidate to
  a sum of 1. It selects a small set of anchors so that each candidate is within `anchor_tol`
  (0.02) of an anchor, by the largest difference of the three shares. There are at most
  `max_anchors` (32) anchors ([`select_anchors`][boa.model.anchors.select_anchors]).
- The frontier cache records its anchors. When the cache exists, the build compares these anchors
  with the candidates of the run ([`anchors_for_build`][boa.model.anchors.anchors_for_build]).
  When they cover all candidates, the build uses the cache again. When they do not, the build
  makes the cache again with the old anchors and the new ones. A cache with `max_anchors`
  anchors is used again with a warning.
- The query does not compare the anchors of the cache with its costs. A query-only run prices the
  cache that is at the cache path.
- A single-point run builds its frontier with the costs of that point as its only anchor.

The stored dispatch results contain no cost. But the anchors decide where the patches are, and
thus which designs the cache contains. When a build adds anchors to a cache, the patches can
change. Thus the result of a query with the same costs can change after the cache is built
again. See [Known limitations](known-limitations.md).

## The query

[`argmin_lcoe`][boa.model.bisection.argmin_lcoe] prices the stored designs of one pixel with the
cost coefficients of one investment year and one cost key. It evaluates the LCOE formula at each
feasible patch node and each battery rung. It returns the design with the lowest LCOE as an
[`Optimum`][boa.model.bisection.Optimum]. The query does no dispatch simulation. It uses the
served fraction that the build stored.

A pixel with a status code other than 1 has no stored designs. Its LCOE and its design are NaN in
the per-year file.

The query also calculates two diagnostics for each pixel and year:

| Diagnostic | Value `True` means |
|---|---|
| Containment check (`patch_certified`) | At each coarse node outside all patch boxes, a lower bound on the LCOE is equal to or more than the LCOE of the result. The bound is `(a_s·s + a_w·w + a_b·b_lower^GAMMA) / d0`, which uses the coarse lower bound on `b_min` and a served fraction of 1. Nodes that the corner cut removes, and nodes where no tested battery meets the target, always pass this test. |
| [Truncation](glossary.md#truncation) (`argmin_truncated`) | The result is on an edge of its patch that is inside the coarse grid. An edge at `s = 0`, at `w = 0`, or at the outer edge of the coarse grid does not count. |

The containment check tests only the coarse nodes outside the patches. It does not give a limit
for the error inside a patch. When the check is false, the query still reports the cheapest
stored design, and no other search runs.
[`check_repair_budget`][boa.model.bisection.check_repair_budget] exists, but no part of the
pipeline calls it.

The per-year files do not contain the two diagnostics. For each region and year, the query
writes to the log only two percentages. They are the percentage of solved pixels with a true
containment check and the percentage with a truncated result.

## How close the result is to the true optimum

The result is the cheapest of the stored designs. It can be different from the true optimum of
the problem above for these reasons:

- **Patch resolution.** The query evaluates only the patch nodes. A design between two nodes is
  not evaluated. Figure 2 shows an example: the result is 1.0 % above the minimum on a grid with
  half the node spacing.
- **Patch extent.** A cheaper design can be just outside the patch of the result.
  `argmin_truncated` is true when the result is on an inner edge of its patch.
- **Battery tolerance.** Each stored `b_min` can be up to about 1 % above the smallest battery
  that meets the target at that node.
- **One battery rung.** The query does not evaluate batteries larger than `b_min`.
- **Seeds.** A low-cost region of the plane without a seed has no patch. The seed score uses a
  lower bound on the battery and no served fraction. Thus its order can be different from the
  order of the LCOE values. BOA does not search a region that the seeds miss. `patch_certified`
  is true when the lower bound at each coarse node outside the patches is at or above the result.
  Nodes that the corner cut removes, and nodes where no tested battery meets the target, always
  pass.
- **Anchor costs.** The seeds come from the anchor costs. A query-only run does not check that
  its costs are near an anchor of the cache. In this case, a low-cost region of the plane for
  these costs can have no patch. BOA also keeps at most `max_patch_slots` (4) patches for each
  pixel, and it drops the patch boxes with the highest seed scores.
- **Search box.** Designs outside the box, beyond the corner cut, or with a battery above the
  tested limit are not evaluated.
- **Stored precision.** The cache stores the served fraction rounded down to a step of
  1/65535, which can make the LCOE slightly higher. It stores the factors as 32-bit
  floating-point numbers.

[Known limitations](known-limitations.md) describes what these points mean for the results.

## What the frontier cache contains

The frontier cache holds these values for each land pixel of one region
([`RegionFrontierCache`][boa.model.frontier_cache.RegionFrontierCache]):

- the status code, and the number of patches and widenings;
- the coarse grid with its lower bounds;
- for each patch node and battery rung, the factors `s`, `w` and `b`, the coverage and the
  served fraction.

The values have these formats:

| Value | Format |
|---|---|
| Coarse lower bound on `b_min` | 16-bit floating point, rounded toward zero |
| `s`, `w`, `b` of the patch nodes | 32-bit floating point |
| Served fraction | 16-bit integer, rounded down (step 1/65535) |
| Coverage | 16-bit integer, rounded to the nearest step (step 1/65535) |

The arrays of the cache contain no cost, no investment year, no load density and no capacity
ceiling. The metadata of the cache records the search settings, the coverage target, the weather
year and the ERA5 resolution. It also records the anchors (as cost coefficients), the build
time and the code version.

The cache path ([`frontier_cache_path`][boa.model.frontier_cache.frontier_cache_path]) contains
these values: the weather year, the region, the coverage target, the grid sizes, a hash of all
search settings (see [Search settings](#search-settings)) and the ERA5 resolution. The cache directory is
[`PathConfig.frontier_cache_dir`][boa.config.paths.PathConfig.frontier_cache_dir], which depends
on the weather year only. When BOA reads a cache
([`read_frontier_cache`][boa.model.frontier_cache.read_frontier_cache]), it compares the schema
version, the cache version, the search settings, the coverage target and the weather year. It
does not compare the content of the profiles or of the land-sea mask. See
[Known limitations](known-limitations.md).

## Status codes

Each pixel of a per-year file has a status code. The build sets it when it builds the frontier
cache:

- Code 3: in step 1, when the solar and the wind capacity factors are zero in all hours.
- Code 2: in step 4, when no solved node that the corner cut keeps has a finite bound.
- Code 1: when the patches are complete (step 7).

The build does not set the other codes. The code depends on the profiles, the coverage target and
the search settings, not on the investment year. The query copies it. The
[promoted LCOE file](promoted-lcoe-file.md) requires the same status in all years, and
promotion stops with an error when the years do not agree. The meaning of each code, and what it
means for the results, is in [Known limitations](known-limitations.md#status-codes).

## Search settings

The search settings are the fields of
[`SearchParams`][boa.model.bisection.SearchParams]. They are not physical parameters: the
physical parameters and their sources are on the [model assumptions](model-assumptions.md)
page. The command-line tools use the default values.

The frontier cache path contains a hash of all fields
([`params_hash`][boa.model.frontier_cache.params_hash]). The run directory name contains a second
hash ([`non_scenario_params_hash`][boa.config.run_manifest.non_scenario_params_hash]). It covers
all fields and also the technology lifetimes. Thus a changed value gives a new cache and a new
run directory. Each stored design meets the coverage target with any values of these settings.
The settings change the precision and the build time. The box settings, the corner cut and
`b_cap` can also change the status code of a pixel.

??? note "All search settings and their default values"
    | Field | Default | Effect |
    |---|---|---|
    | `box_multiple` | 4.0 | Box size as a multiple of `k / CF` |
    | `overscale_sampling_k` | 0.75 (solar and wind) | `k` in the box size |
    | `box_min` | 2.0 | Smallest box size, per axis |
    | `box_abs_max` | 200.0 | Largest box size, per axis, even after widening |
    | `max_box_widenings` | 2 | Number of times the box can double |
    | `corner_cut_threshold` | 1.2 | Corner cut: nodes with `s/s_max + w/w_max` above this value are not searched. `None` turns the cut off. Permitted values: 1 to 2. |
    | `anchor_tol` | 0.02 | Largest share difference between a candidate cost mix and its anchor |
    | `max_anchors` | 32 | Largest number of anchors in one cache |
    | `coarse_grid` | 25 | Coarse nodes per axis |
    | `coarse_stride` | 3 | Spacing of the solved coarse nodes; also the smallest patch half-width, in coarse steps |
    | `coarse_bisect_steps` | 3 | Bisection steps at each solved coarse node |
    | `patch_grid` | 15 | Part of the cache name and the hash. The patch build does not use it: the patch spacing comes from `lattice_refinement`. |
    | `patch_halfwidth` | 0.20 | Patch half-width as a fraction of the seed coordinate |
    | `lattice_refinement` | 2 | Patch nodes per coarse step |
    | `seed_tolerance` | 0.05 | Score tolerance for more seeds |
    | `max_seeds` | 3 | Largest number of seeds for each anchor |
    | `max_patch_slots` | 4 | Largest number of patches for each pixel |
    | `ladder_rungs` | 1 | Battery sizes stored at each patch node |
    | `ladder_max_span` | 1.05 | Largest rung as a multiple of `b_min`. No effect with one rung. |
    | `b_cap` | 500.0 | Upper limit of the bracket, in hours of demand |
    | `tol_rel_patch` | 0.01 | Relative tolerance of the bisection at the patch nodes |
    | `repair_rate_cap` | 0.02 | Used only by `check_repair_budget`, which no part of the pipeline calls |
