"""
Batch pricing of a region's frontier store: `argmin_lcoe` for many cells at once.

`argmin_lcoe` prices one frontier at a time and loops over its patch slots in Python.
`price_frontiers` does the same arithmetic in numpy over batches of cells, reading the region
store's arrays directly, and returns for every cell what `argmin_lcoe` returns: the same design,
the same levelised cost to the last bit, the same containment certificate and the same
truncation flag. `argmin_lcoe` is the readable reference this module is tested against.

Equal to the last bit
---------------------
Floating-point arithmetic rounds after every operation and is not associative, so equal results
need the same operations on the same inputs in the same order. The kernel therefore:

- casts the stored float32 axes and batteries to float64 and decodes the fractions with
  `uint16_to_fraction`, as `frontier_at` and `argmin_lcoe` do;
- evaluates `((a_s*s + a_w*w) + a_b*b**GAMMA) / (d0*served_fraction)` in that order, with one
  set of coefficients per cell (`cost_arrays`);
- calls `np.power` on a float64 array, as `argmin_lcoe` does: numpy can route `power` through
  another maths library for some processors and memory layouts, and that library may round
  differently from the C library behind Python's `**`;
- prices padding, unused slots, infinite batteries and served fractions of zero or below at
  infinity, takes the first minimum within a slot and keeps the first slot that reaches the
  smallest value, which are `argmin_lcoe`'s rules for padding and ties;
- builds the certificate's bound and the truncation test from the operations of
  `_containment_certificate` and `_argmin_truncated`.

`argmin_lcoe` and this module must change together: `tests/test_frontier_pricing.py` compares
them on built and on hand-made frontiers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from boa.config.constants import AVERAGE_IMPLIED_STORAGE, HOURS_IN_YEAR
from boa.model.bisection import GAMMA, STATUS_OK, Optimum
from boa.model.cost_calculations import lcoe_key_terms
from boa.model.frontier_cache import RegionFrontierCache, uint16_to_fraction

# Cells per batch. Every temporary scales with it: at the default `SearchParams` one float64 slot
# of a batch of 1,024 cells is 3.6 MB, and 21.7 MB at six battery sizes. Not a `SearchParams`
# field, because it changes neither a store nor a result.
BATCH_CELLS = 1024

_TECHS = ("solar", "wind", "battery")


@dataclass(frozen=True)
class CostArrays:
    """
    `CostCoefficients` for many cells: one float64 value per cell in each array, in the order of
    the cells `price_frontiers` prices.
    """

    a_s: np.ndarray
    a_w: np.ndarray
    a_b: np.ndarray
    d0: np.ndarray


def cost_arrays(
    investment_horizon: int,
    capex_per_tech: dict,
    opex_per_tech: dict,
    coc_arr: np.ndarray,
    load_mw: np.ndarray,
) -> CostArrays:
    """
    `lcoe_coefficients` for many cells, equal to it bit for bit: one entry per cell of the inputs,
    which are laid out as `global_extension._derive_cost_arrays` returns them (capex as one
    `(n, years)` array per technology, operating shares and cost of capital as `(n,)` arrays),
    with each cell's load in MW.

    A cell's costs reach its coefficients through ten numbers only: capex in year 0 and at the
    horizon for each technology, the three operating shares and the cost of capital. Cells are
    grouped on the bit patterns of those ten, of which a region holds a few dozen, and
    `lcoe_key_terms` runs once per group on one member's own inputs, so it computes what the
    per-cell call would. Each cell's coefficients are then its load times its group's terms, in
    `lcoe_coefficients`' order. The load is cast to float64 first: `pixel_area` returns float32
    for the store's float32 latitudes, and numpy keeps a float32 array times a Python float in
    float32, which would round differently from the per-cell call.
    """
    load = np.asarray(load_mw, dtype=np.float64)
    columns = [capex_per_tech[tech][:, year] for tech in _TECHS for year in (0, investment_horizon)]
    columns += [opex_per_tech[tech] for tech in _TECHS] + [coc_arr]
    inputs = np.column_stack([np.asarray(column, dtype=np.float64).view(np.uint64) for column in columns])
    _, first, group = np.unique(inputs, axis=0, return_index=True, return_inverse=True)
    terms = np.array(
        [
            lcoe_key_terms(
                investment_horizon,
                {tech: capex_per_tech[tech][k] for tech in _TECHS},
                {tech: float(opex_per_tech[tech][k]) for tech in _TECHS},
                float(coc_arr[k]),
            )
            for k in first
        ],
        dtype=np.float64,
    ).reshape(-1, 4)
    x_s, x_w, x_b, s_d = terms[group.reshape(-1)].T
    return CostArrays(
        a_s=load * x_s,
        a_w=load * x_w,
        a_b=load * AVERAGE_IMPLIED_STORAGE ** (1.0 - GAMMA) * x_b,
        d0=load * HOURS_IN_YEAR * s_d,
    )


@dataclass(frozen=True)
class FrontierOptima:
    """
    `Optimum` for many cells: one entry per cell that `price_frontiers` was given, in its order.

    The query never prices a cell whose status is not `STATUS_OK`, and neither does the kernel:
    such a cell keeps its status, its floats are NaN, its `patch_index` is -1 and both flags are
    False.
    """

    status: np.ndarray  # (n,) int8, the store's own
    lcoe: np.ndarray  # (n,) float64
    solar: np.ndarray  # (n,) float64
    wind: np.ndarray  # (n,) float64
    battery: np.ndarray  # (n,) float64
    served_fraction: np.ndarray  # (n,) float64
    hours_covered: np.ndarray  # (n,) float64
    patch_index: np.ndarray  # (n,) int64
    patch_certified: np.ndarray  # (n,) bool
    argmin_truncated: np.ndarray  # (n,) bool

    def optimum(self, i: int) -> Optimum:
        """Entry `i` as the `Optimum` that `argmin_lcoe` returns for it, with the same Python types."""
        if self.status[i] != STATUS_OK:
            raise ValueError(f"entry {i} has status {int(self.status[i])}, not STATUS_OK, so it holds no optimum")
        return Optimum(
            lcoe=float(self.lcoe[i]),
            solar=float(self.solar[i]),
            wind=float(self.wind[i]),
            battery=float(self.battery[i]),
            served_fraction=float(self.served_fraction[i]),
            hours_covered=float(self.hours_covered[i]),
            patch_index=int(self.patch_index[i]),
            patch_certified=bool(self.patch_certified[i]),
            argmin_truncated=bool(self.argmin_truncated[i]),
        )


def price_frontiers(
    cache: RegionFrontierCache,
    costs: CostArrays,
    cells: np.ndarray | None = None,
    *,
    batch_cells: int = BATCH_CELLS,
) -> FrontierOptima:
    """
    `argmin_lcoe` for many cells of a region store at once, on one thread, equal to it bit for bit.

    `cells` lists the store's cells to price, in any order, and `None` prices every cell. `costs`
    holds one entry per cell of `cells`, in the same order, and so does the result. A cell whose
    status is not `STATUS_OK` passes through unpriced (`FrontierOptima`). A cell whose status is
    `STATUS_OK` but whose patches hold no feasible design raises `ValueError`, as `argmin_lcoe` does.

    Memory is bounded by `batch_cells`. Within a batch the kernel loops over the patch slots and
    casts one slot at a time to float64, so every temporary holds `batch_cells x P x P x R` values
    and the store is never copied: a batch of consecutive cells is read as views of the store, and
    any other batch is gathered one slot at a time. Only each winner's design and fractions are read
    back from the store.
    """
    cells = np.arange(cache.n_points) if cells is None else np.asarray(cells)
    n = len(cells)
    if any(len(values) != n for values in (costs.a_s, costs.a_w, costs.a_b, costs.d0)):
        raise ValueError(f"costs must hold one value per cell priced, {n}, in each of their arrays")
    if batch_cells < 1:
        raise ValueError(f"batch_cells must be at least 1, got {batch_cells}")

    optima = FrontierOptima(
        status=np.zeros(n, dtype=cache.status.dtype),
        lcoe=np.full(n, np.nan),
        solar=np.full(n, np.nan),
        wind=np.full(n, np.nan),
        battery=np.full(n, np.nan),
        served_fraction=np.full(n, np.nan),
        hours_covered=np.full(n, np.nan),
        patch_index=np.full(n, -1, dtype=np.int64),
        patch_certified=np.zeros(n, dtype=bool),
        argmin_truncated=np.zeros(n, dtype=bool),
    )
    for lo in range(0, n, batch_cells):
        hi = min(lo + batch_cells, n)
        listed = cells[lo:hi]
        rows = slice(int(listed[0]), int(listed[-1]) + 1) if np.all(np.diff(listed) == 1) else listed
        batch = _price_batch(cache, rows, costs.a_s[lo:hi], costs.a_w[lo:hi], costs.a_b[lo:hi], costs.d0[lo:hi])
        for name, values in batch.items():
            getattr(optima, name)[lo:hi] = values
    return optima


def _price_batch(
    cache: RegionFrontierCache,
    rows: slice | np.ndarray,
    a_s: np.ndarray,
    a_w: np.ndarray,
    a_b: np.ndarray,
    d0: np.ndarray,
) -> dict[str, np.ndarray]:
    """
    Price one batch: `rows` is a slice of consecutive cells or an array of cell indices, and the
    coefficients hold one value per cell of the batch. Returns `FrontierOptima`'s fields.
    """
    cells = np.arange(rows.start, rows.stop) if isinstance(rows, slice) else rows
    n = len(cells)
    _, n_slots, p = cache.s_patch.shape
    n_rungs = cache.b_patch.shape[-1]
    status = cache.status[rows]
    points = cache.patch_points[rows]
    priced = status == STATUS_OK
    # `argmin_lcoe` loops over the slots below `n_patches` only, and the query prices solved cells only.
    used = priced[:, None] & (np.arange(n_slots)[None, :] < cache.n_patches[rows][:, None])
    nodes = np.arange(p)

    slot_value = np.full((n, n_slots), np.inf)
    slot_node = np.zeros((n, n_slots), dtype=np.intp)
    for k in range(n_slots):
        if not used[:, k].any():
            continue
        b = cache.b_patch[rows, k].astype(np.float64)
        sf = uint16_to_fraction(cache.energy_served_frac[rows, k])
        s = cache.s_patch[rows, k].astype(np.float64)
        w = cache.w_patch[rows, k].astype(np.float64)
        lcoe = _slot_lcoe(a_s, a_w, a_b, d0, s, w, b, sf)
        # The slot's real extent, as `argmin_lcoe` slices it: every node beyond it is padding.
        real = (
            used[:, k, None, None, None]
            & (nodes[None, :, None, None] < points[:, k, 0, None, None, None])
            & (nodes[None, None, :, None] < points[:, k, 1, None, None, None])
        )
        lcoe = np.where(real & np.isfinite(b) & (sf > 0), lcoe, np.inf).reshape(n, -1)
        slot_node[:, k] = np.argmin(lcoe, axis=1)
        slot_value[:, k] = lcoe[np.arange(n), slot_node[:, k]]

    slot, node, best = _winners(slot_value, slot_node)
    missing = priced & ~(best < np.inf)
    if missing.any():
        raise ValueError(
            f"cell {int(cells[np.flatnonzero(missing)[0]])} has status STATUS_OK but no feasible design in its "
            "patches; argmin_lcoe refuses such a frontier too"
        )
    i, j, r = np.unravel_index(node, (p, p, n_rungs))
    gc = cache.b_coarse.shape[-1]
    certified = _certificates(cache, rows, a_s, a_w, a_b, d0, best, used)
    truncated = _truncated(i, j, points[np.arange(n), slot], cache.patch_bounds[cells, slot], gc)
    return {
        "status": status,
        "lcoe": np.where(priced, best, np.nan),
        "solar": np.where(priced, cache.s_patch[cells, slot, i].astype(np.float64), np.nan),
        "wind": np.where(priced, cache.w_patch[cells, slot, j].astype(np.float64), np.nan),
        "battery": np.where(priced, cache.b_patch[cells, slot, i, j, r].astype(np.float64), np.nan),
        "served_fraction": np.where(priced, uint16_to_fraction(cache.energy_served_frac[cells, slot, i, j, r]), np.nan),
        "hours_covered": np.where(priced, uint16_to_fraction(cache.hours_covered_frac[cells, slot, i, j, r]), np.nan),
        "patch_index": np.where(priced, slot, -1),
        "patch_certified": priced & certified,
        "argmin_truncated": priced & truncated,
    }


def _slot_lcoe(
    a_s: np.ndarray,
    a_w: np.ndarray,
    a_b: np.ndarray,
    d0: np.ndarray,
    s: np.ndarray,
    w: np.ndarray,
    b: np.ndarray,
    sf: np.ndarray,
) -> np.ndarray:
    """
    The ranking value of every node of one slot across a batch, `(n, P, P, R)`: `argmin_lcoe`'s
    expression with one set of coefficients per cell, before padding and infeasible nodes are
    masked. `s` and `w` are the slot's axes, `(n, P)`; `b` and `sf` its batteries and served
    fractions, all float64.
    """
    a_s, a_w, a_b, d0 = (x[:, None, None, None] for x in (a_s, a_w, a_b, d0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return (a_s * s[:, :, None, None] + a_w * w[:, None, :, None] + a_b * np.power(b, GAMMA)) / (d0 * sf)


def _winners(slot_value: np.ndarray, slot_node: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    The rule across slots, from each slot's minimum `(n, K)` and its node in the slot's flattened
    `(P, P, R)` order. `argmin_lcoe` keeps a slot only if it is strictly cheaper than the best so
    far, so the first slot that reaches the smallest value wins, and a slot whose minimum is NaN
    never wins. Returns each cell's winning slot, its node and its value, which is infinity where
    no slot holds a design.
    """
    ranked = np.where(np.isnan(slot_value), np.inf, slot_value)
    slot = np.argmin(ranked, axis=1)
    rows = np.arange(len(slot))
    return slot, slot_node[rows, slot], ranked[rows, slot]


def _certificates(
    cache: RegionFrontierCache,
    rows: slice | np.ndarray,
    a_s: np.ndarray,
    a_w: np.ndarray,
    a_b: np.ndarray,
    d0: np.ndarray,
    best: np.ndarray,
    used: np.ndarray,
) -> np.ndarray:
    """
    `_containment_certificate` for a batch: True where no coarse cell outside the used slots'
    patches has a bound below the cell's winning levelised cost, `best`, less the same slack of 1e-9.
    """
    s_c = cache.s_coarse[rows].astype(np.float64)
    w_c = cache.w_coarse[rows].astype(np.float64)
    b_lo = np.maximum(cache.b_coarse[rows].astype(np.float64), 0.0)
    a_s, a_w, a_b, d0 = (x[:, None, None] for x in (a_s, a_w, a_b, d0))
    bound = (a_s * s_c[:, :, None] + a_w * w_c[:, None, :] + a_b * np.power(b_lo, GAMMA)) / d0
    inside = _patch_membership(cache.patch_bounds[rows], used, cache.b_coarse.shape[-1])
    return np.all(inside | (bound >= (best - 1e-9)[:, None, None]), axis=(1, 2))


def _truncated(i: np.ndarray, j: np.ndarray, points: np.ndarray, bounds: np.ndarray, gc: int) -> np.ndarray:
    """`_argmin_truncated` for a batch of winners: `points` `(n, 2)` and `bounds` `(n, 4)` are the winning slot's."""
    n_s, n_w = points[:, 0], points[:, 1]
    i0, i1, j0, j1 = bounds.T
    return (
        ((i == 0) & (i0 > 0))
        | ((i == n_s - 1) & (i1 < gc - 1))
        | ((j == 0) & (j0 > 0))
        | ((j == n_w - 1) & (j1 < gc - 1))
    )


def _patch_membership(bounds: np.ndarray, used: np.ndarray, gc: int) -> np.ndarray:
    """
    `_patch_membership_mask` for a batch, `(n, Gc, Gc)`: True where a coarse cell lies inside the
    bounds of a used slot. `bounds` is `(n, K, 4)` and `used` `(n, K)`.

    Comparisons stand in for `_patch_membership_mask`'s slices. The two agree for every bound of
    zero or more: a slice clamps a bound beyond the far end of the grid, and a comparison then
    holds for the same cells. A negative bound would slice from the far end of the grid, so a
    negative bound raises rather than give another answer; `patch_bounds_for_seed` never writes one.
    """
    in_use = bounds[used]
    if in_use.size and in_use.min() < 0:
        raise ValueError(f"negative patch bound {in_use.min()}: argmin_lcoe would slice it from the grid's far end")
    grid = np.arange(gc)
    inside = np.zeros((len(bounds), gc, gc), dtype=bool)
    for k in range(bounds.shape[1]):
        i0, i1, j0, j1 = (bounds[:, k, m, None] for m in range(4))
        rows_in = (grid >= i0) & (grid <= i1)
        cols_in = (grid >= j0) & (grid <= j1)
        inside |= used[:, k, None, None] & rows_in[:, :, None] & cols_in[:, None, :]
    return inside
