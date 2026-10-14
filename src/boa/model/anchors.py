"""
Turning a cost dataset into the anchor set the frontier build searches under.

An anchor is one set of cost coefficients. It decides *where* the build places its dense
patches and nothing else: the values stored at those patches are pure dispatch, so a badly
chosen anchor costs search quality, never accuracy. The containment certificate detects the
case where it mattered.

Anchors have to span two axes, and the second is the larger of the two:

- **Investment year.** Capex declines over the horizon, and the mix shifts with it.
- **Cost key.** Each pixel is priced with its own country's capex, opex and WACC. Measured on
  the real workbook, the spread of mixes across the 244 keys at a single year is 0.157 against
  0.088 of drift across the whole 2025-2060 horizon -- so *where* a key sits matters about
  twice as much as *when* it is queried.

Anchoring on years alone would leave keys at the edges of that spread served by an anchor built
for the middle. `covering_anchors` therefore selects over the joint set, guaranteeing every
`(key, year)` combination lies within `tol` of some anchor.

The build takes the candidate mixes as an *input* and never derives a cost key itself, which is
what keeps the frontier cache independent of the canonical iso3 grid. It records the anchors it
used, so a later run can tell whether a stored cache covers what it is about to query
(`anchors_for_build`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence

import numpy as np
import xarray as xr

from boa.model.bisection import CostCoefficients, SearchParams, cost_ratio_simplex, covering_anchors
from boa.model.cost_calculations import lcoe_coefficients
from boa.model.single_point_run import costs_for_key

Candidates = Mapping[tuple[int, str], CostCoefficients]


def cost_candidates(years: Sequence[int], costs_for_year: Callable[[int], tuple[xr.Dataset, int]]) -> Candidates:
    """
    Every `(investment year, cost key)` pair this cost set can produce, with the coefficients a
    query would price it at.

    `costs_for_year` returns that year's cost dataset and investment horizon, already sliced so
    index 0 is the investment year -- the same shape the query uses, so an anchor is priced
    exactly as a real query would price it. It is called once per year.

    Coefficients are built at baseload 1.0. Baseload scales all four linearly and so cancels
    out of the mix entirely, which is the same reason LCOE is exactly baseload-invariant.
    """
    candidates: dict[tuple[int, str], CostCoefficients] = {}
    for year in years:
        costs, horizon = costs_for_year(year)
        for key in costs["iso3"].values:
            capex, opex_pct, cost_of_capital = costs_for_key(str(key), costs)
            candidates[(year, str(key))] = lcoe_coefficients(horizon, capex, opex_pct, cost_of_capital, 1.0)
    if not candidates:
        raise ValueError("no (cost key, year) candidates; the cost set has no iso3 coordinate")
    return candidates


def select_anchors(
    candidates: Candidates,
    params: SearchParams | None = None,
    keep: Sequence[CostCoefficients] = (),
) -> list[CostCoefficients]:
    """
    The anchor set covering every candidate, always including `keep` (listed first).

    `params.anchor_tol`/`params.max_anchors` govern the selection (see `SearchParams` --
    folded in there rather than kept as this module's own constants, so the same value that
    shaped a build's anchors is part of what the frontier cache's identity hash covers).
    """
    params = SearchParams() if params is None else params
    tol, max_anchors = params.anchor_tol, params.max_anchors

    kept_labels: list[tuple] = [("kept", i) for i in range(len(keep))]
    coefficients = {**dict(zip(kept_labels, keep)), **candidates}
    labels = kept_labels + list(candidates)
    chosen = covering_anchors(labels, coefficients.__getitem__, tol=tol, max_anchors=max_anchors, keep=len(keep))
    if len(chosen) == max_anchors:
        logging.warning(
            f"Anchor selection hit max_anchors={max_anchors} at tol={tol}; some cost keys sit "
            f"further than {tol} from every anchor. Seeds may be misplaced for those keys, which "
            f"costs uncertified queries rather than wrong answers -- raise tol or max_anchors."
        )
    new_years = sorted({label[0] for label in chosen if label[0] != "kept"})
    kept_note = f" ({len(keep)} kept from the stored cache)" if keep else ""
    logging.info(
        f"Anchor set: {len(chosen)} anchors{kept_note} covering {len(candidates)} (cost key, year) "
        f"combinations at tol={tol} — {new_years}"
    )
    return [coefficients[label] for label in chosen]


def uncovered(anchors: Sequence[CostCoefficients], candidates: Candidates, tol: float) -> int:
    """How many candidates lie further than `tol` from every anchor, by `covering_anchors`' distance."""
    kept = [np.asarray(cost_ratio_simplex(a)) for a in anchors]
    return sum(
        min(float(np.max(np.abs(np.asarray(cost_ratio_simplex(c)) - k))) for k in kept) > tol
        for c in candidates.values()
    )


def anchors_for_build(
    stored: Sequence[CostCoefficients] | None,
    candidates: Candidates,
    params: SearchParams | None = None,
) -> list[CostCoefficients] | None:
    """
    The anchors to build a frontier cache with, or None when the anchors it was built with
    (`stored`) already cover every candidate and the store can be reused as it is.

    An uncovered store is rebuilt over the union: its own anchors plus whatever the request
    needs. Coverage then only grows, so alternating cost sets or horizons settles after one
    rebuild each instead of rebuilding back and forth. A store that records no anchors
    (`stored` is None) can't show what it covers, so it is rebuilt for the request alone.

    A store already at `max_anchors` is reused even when it leaves candidates uncovered:
    the union would add nothing, so the rebuild would reproduce the store on every run.
    `select_anchors` warns about the gap.
    """
    params = SearchParams() if params is None else params
    if stored is None:
        return select_anchors(candidates, params)
    if not uncovered(stored, candidates, params.anchor_tol):
        return None
    anchors = select_anchors(candidates, params, keep=stored)
    return None if len(anchors) == len(stored) else anchors


def anchor_cost_coefficients(
    years: Sequence[int],
    costs_for_year: Callable[[int], tuple[xr.Dataset, int]],
    params: SearchParams | None = None,
) -> list[CostCoefficients]:
    """The anchor set covering every `(cost key, investment year)` this cost set can produce."""
    return select_anchors(cost_candidates(years, costs_for_year), params)
