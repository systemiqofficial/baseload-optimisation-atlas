"""
Contracts for the batch pricing kernel, `boa.model.frontier_pricing`.

The region query prices every cell through `price_frontiers`, so the kernel must return what
`argmin_lcoe` returns for each cell, bit for bit: the design, the levelised cost of electricity
(LCOE), both fractions, the winning slot, the containment certificate and the truncation flag.
`argmin_lcoe` is the readable reference it is checked against, as `dispatch_metrics` is checked
against `state_of_charge`, and the query worker is checked against its per-cell form, down to the
bytes of the file it writes.

Every frontier here goes through `stack_pixel_frontiers`, so the kernel and
`argmin_lcoe(frontier_at(cache, k))` read the same float32 and uint16 arrays.
"""

import dataclasses
from typing import Any

import numpy as np
import pytest

from boa.cds.max_capacity import pixel_area
from boa.model.bisection import (
    GAMMA,
    STATUS_NO_OPTIMUM,
    STATUS_OK,
    STATUS_ZERO_POTENTIAL,
    CostCoefficients,
    Optimum,
    PixelFrontier,
    SearchParams,
    argmin_lcoe,
    build_pixel_frontier,
    max_patch_points,
)
from boa.model.cost_calculations import installation_cost_breakdown, lcoe_coefficients
from boa.model.frontier_cache import RegionFrontierCache, build_frontier_meta, frontier_at, stack_pixel_frontiers
from boa.model.frontier_pricing import CostArrays, FrontierOptima, cost_arrays, price_frontiers
from boa.model.global_extension import _assemble_optimal_sol, _query_frontier_tile

PARAMS = SearchParams()
SIX_RUNGS = SearchParams(ladder_rungs=6, ladder_max_span=3.0)
TECHS = ("solar", "wind", "battery")
SECOND_ANCHOR = CostCoefficients(a_s=0.6e6, a_w=2.0e6, a_b=0.15e6, d0=8.76e6)


def _store(frontiers: list[PixelFrontier], params: SearchParams) -> RegionFrontierCache:
    """A region store of the frontiers on a grid one cell wide, one latitude per cell from 60 S to 60 N."""
    n = len(frontiers)
    lats = np.linspace(-60.0, 60.0, n).astype(np.float32)
    return stack_pixel_frontiers(
        frontiers,
        region="TESTREGION",
        all_lats=lats,
        all_lons=np.array([20.0], dtype=np.float32),
        lats=lats,
        lons=np.full(n, 20.0, dtype=np.float32),
        iy=np.arange(n, dtype=np.int32),
        ix=np.zeros(n, dtype=np.int32),
        meta=build_frontier_meta("TESTREGION", n, 0.85, params, 2024, 0.25, []),
    )


def _random_costs(n: int, seed: int = 0) -> CostArrays:
    """
    Coefficients around the anchors' mix, one set per cell. Every third cell gets a battery cheap
    enough to buy a larger battery size than the smallest, and every seventh prices everything at
    zero, so that its nodes tie and a zero served fraction divides zero by zero.
    """
    rng = np.random.default_rng(seed)
    costs = CostArrays(
        a_s=rng.uniform(0.4e6, 1.2e6, n),
        a_w=rng.uniform(0.8e6, 2.2e6, n),
        a_b=rng.uniform(0.1e6, 0.4e6, n),
        d0=rng.uniform(5.0e6, 9.0e6, n),
    )
    costs.a_b[::3] = 1.0e3
    costs.a_s[5::7] = costs.a_w[5::7] = costs.a_b[5::7] = 0.0
    return costs


def _bits(optimum: Optimum) -> tuple:
    """Every field of an `Optimum`, with each float in its exact hexadecimal form, so that equal means bit for bit."""
    return tuple(value.hex() if isinstance(value, float) else value for value in dataclasses.astuple(optimum))


def _assert_equals_argmin_lcoe(cache: RegionFrontierCache, costs: CostArrays, optima: FrontierOptima) -> list[int]:
    """Compare every cell of a whole-store pricing with `argmin_lcoe`, bit for bit; return the solved cells."""
    solved = []
    for k in range(cache.n_points):
        assert optima.status[k] == cache.status[k]
        if cache.status[k] != STATUS_OK:
            continue
        coeffs = CostCoefficients(
            a_s=float(costs.a_s[k]), a_w=float(costs.a_w[k]), a_b=float(costs.a_b[k]), d0=float(costs.d0[k])
        )
        assert _bits(optima.optimum(k)) == _bits(argmin_lcoe(frontier_at(cache, k), coeffs)), f"cell {k}"
        solved.append(k)
    return solved


def _winning_rung(cache: RegionFrontierCache, k: int, optimum: Optimum) -> int:
    """The battery size a winner sits on, found from its battery among its slot's stored ones."""
    return int(np.argwhere(cache.b_patch[k, optimum.patch_index] == np.float32(optimum.battery))[0, -1])


def _assert_same_optima(a: FrontierOptima, b: FrontierOptima) -> None:
    """Every field equal, floats bit for bit, NaN where the other has NaN."""
    for field in dataclasses.fields(FrontierOptima):
        x, y = getattr(a, field.name), getattr(b, field.name)
        assert x.dtype == y.dtype, field.name
        if x.dtype.kind == "f":
            x, y = x.view(np.uint64), y.view(np.uint64)
        assert np.array_equal(x, y), field.name


# --------------------------------------------------------------------------
# Frontiers built on the suite's profiles
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_stores(profiles, poor_profiles, solar_only_profiles, dead_profiles, anchor_costs):
    """
    Two stores of real builds: one battery size per node, as `SearchParams()` stores, and six.
    Each holds every profile at three coverages, under one anchor and under two, so cells use one
    or two slots, and the dead profile adds cells with no potential.
    """
    return {
        params.ladder_rungs: _store(
            [
                build_pixel_frontier(p["solar"], p["wind"], coverage, params, anchors)
                for p in (profiles, poor_profiles, solar_only_profiles, dead_profiles)
                for coverage in (0.75, 0.85, 0.95)
                for anchors in ([anchor_costs], [anchor_costs, SECOND_ANCHOR])
            ],
            params,
        )
        for params in (PARAMS, SIX_RUNGS)
    }


@pytest.mark.parametrize("rungs", [1, 6])
def test_the_kernel_equals_argmin_lcoe_on_built_frontiers(built_stores, rungs):
    """
    Real builds at one and at six battery sizes, priced under a different mix of costs per cell:
    every solved cell must come out of the kernel exactly as out of `argmin_lcoe`, and every cell
    with no potential must pass through unpriced.
    """
    cache = built_stores[rungs]
    costs = _random_costs(cache.n_points)
    optima = price_frontiers(cache, costs)
    solved = _assert_equals_argmin_lcoe(cache, costs, optima)

    assert len(solved) == 18 and np.sum(cache.status == STATUS_ZERO_POTENTIAL) == 6
    if rungs == 6:
        assert any(_winning_rung(cache, k, optima.optimum(k)) > 0 for k in solved), "no larger battery ever won"


# --------------------------------------------------------------------------
# Hand-made frontiers: padding, ties and infeasible designs
# --------------------------------------------------------------------------


def _hand_made(
    rng: np.random.Generator,
    n_used: int,
    *,
    tie: str | None = None,
    infeasible_node: bool = False,
    infeasible_rung: bool = False,
    empty_slot: bool = False,
    no_design: bool = False,
) -> PixelFrontier:
    """
    A solved frontier at the six-rung store's shape with `n_used` populated slots of random extent.

    The padding beyond each slot's extent and every unused slot hold a nearly free design at a
    full served fraction, which would win outright if the kernel read it.
    """
    n_slots, p, rungs = SIX_RUNGS.max_patch_slots, max_patch_points(SIX_RUNGS), SIX_RUNGS.ladder_rungs
    gc = SIX_RUNGS.coarse_grid
    s = np.full((n_slots, p), 0.1, dtype=np.float32)
    w = np.full((n_slots, p), 0.1, dtype=np.float32)
    b = np.full((n_slots, p, p, rungs), 1e-6, dtype=np.float32)
    sf = np.ones((n_slots, p, p, rungs))
    hc = np.ones((n_slots, p, p, rungs))
    bounds = np.zeros((n_slots, 4), dtype=np.int32)
    points = np.zeros((n_slots, 2), dtype=np.int32)
    for k in range(n_used):
        n_s, n_w = (int(x) for x in rng.integers(2, p + 1, size=2))
        i0, j0 = (int(x) for x in rng.integers(0, 10, size=2))
        bounds[k] = (i0, min(gc - 1, i0 + int(rng.integers(1, 12))), j0, min(gc - 1, j0 + int(rng.integers(1, 12))))
        points[k] = (n_s, n_w)
        s[k, :n_s] = np.sort(rng.uniform(0.0, 8.0, n_s))
        w[k, :n_w] = np.sort(rng.uniform(0.0, 8.0, n_w))
        # Each larger battery serves a little more energy, as a built ladder does.
        b[k, :n_s, :n_w] = rng.uniform(0.5, 40.0, (n_s, n_w, 1)) * np.linspace(1.0, 3.0, rungs)
        sf[k, :n_s, :n_w] = rng.uniform(0.85, 0.99, (n_s, n_w, 1)) + np.linspace(0.0, 0.009, rungs)
        hc[k, :n_s, :n_w] = sf[k, :n_s, :n_w] - 0.01
        if infeasible_node:
            b[k, 0, 0], sf[k, 0, 0] = np.inf, 0.0
        if infeasible_rung:
            # One battery size infeasible in some feasible nodes, marked by its served fraction
            # alone, so that only `argmin_lcoe`'s test of the served fraction keeps it out.
            sf[k, :n_s, :n_w, 2][rng.random((n_s, n_w)) < 0.3] = 0.0
        if no_design:
            b[k, :n_s, :n_w], sf[k, :n_s, :n_w] = np.inf, 0.0
    # Each tie is made to hold at the winner: two free nodes in slot 0, or every slot or every
    # battery size alike.
    if tie == "within a slot":
        s[0, :2] = w[0, :2] = 0.0
        b[0, 1, 1], sf[0, 1, 1] = b[0, 0, 0], sf[0, 0, 0]
        b[0, 0, 0] = b[0, 1, 1] = 1e-3
    elif tie == "across slots":
        for k in range(1, n_used):
            s[k], w[k], b[k], sf[k], points[k] = s[0], w[0], b[0], sf[0], points[0]
    elif tie == "across battery sizes":
        b[:n_used], sf[:n_used] = b[:n_used, :, :, :1], sf[:n_used, :, :, :1]
    if empty_slot:
        points[1, 0] = 0
    return PixelFrontier(
        status=STATUS_OK,
        n_patches=n_used,
        box_widenings=0,
        s_coarse=np.linspace(0.0, 8.0, gc, dtype=np.float32),
        w_coarse=np.linspace(0.0, 8.0, gc, dtype=np.float32),
        b_coarse=np.where(rng.random((gc, gc)) < 0.2, np.inf, rng.uniform(0.0, 60.0, (gc, gc))).astype(np.float16),
        s_patch=s,
        w_patch=w,
        b_patch=b,
        energy_served_frac=sf,
        hours_covered_frac=hc,
        patch_bounds=bounds,
        patch_points=points,
    )


@pytest.fixture(scope="module")
def hand_made_store() -> RegionFrontierCache:
    """
    Twelve plain frontiers of one to four slots, two of each tie, six with a battery size
    infeasible inside feasible nodes, two with an infeasible node per slot, two with an empty slot
    below `n_patches`, and two cells the build found no optimum or no potential for.
    """
    rng = np.random.default_rng(55)
    cases: list[dict[str, Any]] = [{"n_used": n} for n in (1, 2, 3, 4) for _ in range(3)]
    cases += [{"n_used": 3, "tie": tie} for tie in ("within a slot", "across slots", "across battery sizes")] * 2
    cases += [{"n_used": 2, "infeasible_rung": True}] * 6
    cases += [{"n_used": 4, "infeasible_node": True}] * 2
    cases += [{"n_used": 3, "empty_slot": True}] * 2
    frontiers = [_hand_made(rng, **case) for case in cases]
    for status in (STATUS_NO_OPTIMUM, STATUS_ZERO_POTENTIAL):
        no_points = np.zeros_like(frontiers[0].patch_points)
        frontiers.append(dataclasses.replace(frontiers[0], status=status, n_patches=0, patch_points=no_points))
    return _store(frontiers, SIX_RUNGS)


def test_the_kernel_equals_argmin_lcoe_on_padding_ties_and_infeasible_designs(hand_made_store):
    """
    The cases where a batch layout could pick another answer: attractive padding and unused
    slots, ties within a slot, across slots and across battery sizes, infeasible nodes and
    battery sizes, an empty slot, and costs of zero. `argmin_lcoe` keeps the first minimum within
    a slot and the first slot that reaches it, and the kernel must too.
    """
    cache = hand_made_store
    costs = _random_costs(cache.n_points, seed=1)
    optima = price_frontiers(cache, costs)
    solved = _assert_equals_argmin_lcoe(cache, costs, optima)

    assert len(solved) == cache.n_points - 2
    assert any(_winning_rung(cache, k, optima.optimum(k)) > 0 for k in solved), "no larger battery ever won"
    for flag in (optima.patch_certified[solved], optima.argmin_truncated[solved]):
        assert flag.any() and not flag.all(), "a flag never changed, so the test cannot tell it apart"


def test_cells_without_an_optimum_pass_through_unpriced(hand_made_store):
    """
    The query never prices a cell the build found no optimum or no potential for. The kernel keeps
    its status and marks everything else as not found, and refuses to turn it into an `Optimum`.
    """
    cache = hand_made_store
    optima = price_frontiers(cache, _random_costs(cache.n_points))
    for k in (cache.n_points - 2, cache.n_points - 1):
        assert optima.status[k] in (STATUS_NO_OPTIMUM, STATUS_ZERO_POTENTIAL)
        for name in ("lcoe", "solar", "wind", "battery", "served_fraction", "hours_covered"):
            assert np.isnan(getattr(optima, name)[k]), name
        assert optima.patch_index[k] == -1
        assert not optima.patch_certified[k] and not optima.argmin_truncated[k]
        with pytest.raises(ValueError, match="not STATUS_OK"):
            optima.optimum(k)


def test_the_kernel_equals_argmin_lcoe_where_only_a_guard_decides():
    """
    Two cases a build never stores, in each of which one of `argmin_lcoe`'s guards alone decides
    the answer. In the first cell an infinite battery serves a positive fraction at zero battery
    cost, so its cost is zero times infinity, which is NaN, and only the test of the battery itself
    keeps it out of the argmin: the winner is the next battery size of the same node, which costs
    nothing. In each of the other cells one slot holds a NaN solar size, so that slot's minimum is
    NaN, and `argmin_lcoe` passes over the slot.
    """
    rng = np.random.default_rng(56)
    free = _hand_made(rng, 2)
    free.s_patch[0, 0] = free.w_patch[0, 0] = 0.0
    free.b_patch[0, 0, 0, 0] = np.inf
    nan_slots = [_hand_made(rng, 3) for _ in range(3)]
    for slot, frontier in enumerate(nan_slots):
        frontier.s_patch[slot, 0] = np.nan
    cache = _store([free, *nan_slots], SIX_RUNGS)
    costs = _random_costs(cache.n_points, seed=5)
    costs.a_b[0] = 0.0
    optima = price_frontiers(cache, costs)

    _assert_equals_argmin_lcoe(cache, costs, optima)
    assert optima.lcoe[0] == 0.0 and _winning_rung(cache, 0, optima.optimum(0)) == 1
    assert all(optima.patch_index[1 + slot] != slot for slot in range(3))


def _three_by_three(bounds: tuple[int, int, int, int], cheapest: tuple[int, int], b_coarse=None) -> PixelFrontier:
    """
    One 3 x 3 slot on the coarse cells `bounds`, in the style of `test_query.py`. Under costs of
    battery alone its node `cheapest`, the one with the smallest battery, wins. Every coarse cell
    is infeasible unless `b_coarse` says otherwise, so none can fail the certificate.
    """
    gc, gp = PARAMS.coarse_grid, 3
    b = np.full((1, gp, gp, 1), 5.0, dtype=np.float32)
    b[0, cheapest[0], cheapest[1]] = 1.0
    return PixelFrontier(
        status=STATUS_OK,
        n_patches=1,
        box_widenings=0,
        s_coarse=np.linspace(0.0, 8.0, gc, dtype=np.float32),
        w_coarse=np.linspace(0.0, 8.0, gc, dtype=np.float32),
        b_coarse=np.full((gc, gc), np.inf, dtype=np.float16) if b_coarse is None else b_coarse,
        s_patch=np.linspace(1.0, 3.0, gp, dtype=np.float32)[None, :],
        w_patch=np.linspace(1.0, 3.0, gp, dtype=np.float32)[None, :],
        b_patch=b,
        energy_served_frac=np.ones((1, gp, gp, 1)),
        hours_covered_frac=np.full((1, gp, gp, 1), 0.95),
        patch_bounds=np.array([bounds], dtype=np.int32),
        patch_points=np.array([[gp, gp]], dtype=np.int32),
    )


def _battery_only(n: int) -> CostArrays:
    """Costs of battery alone for `n` cells, under which the smallest battery wins."""
    return CostArrays(a_s=np.zeros(n), a_w=np.zeros(n), a_b=np.ones(n), d0=np.ones(n))


def test_truncation_on_every_patch_edge_equals_argmin_lcoe():
    """
    A winner on a patch edge is truncated only where the patch imposed that edge, not the search
    box. Each node of a 3 x 3 slot wins in turn, with the slot inside the coarse grid and against
    its lower and its upper corner.
    """
    frontiers = [
        _three_by_three(bounds, (i, j))
        for bounds in ((5, 7, 5, 7), (0, 2, 0, 2), (22, 24, 22, 24))
        for i in range(3)
        for j in range(3)
    ]
    cache = _store(frontiers, PARAMS)
    costs = _battery_only(cache.n_points)
    optima = price_frontiers(cache, costs)

    assert len(_assert_equals_argmin_lcoe(cache, costs, optima)) == 27
    assert optima.argmin_truncated.sum() == 8 + 5 + 5


def test_the_certificate_keeps_argmin_lcoes_slack():
    """
    The certificate passes a coarse cell whose bound lies below the winner's LCOE by less than
    `_containment_certificate`'s slack of 1e-9, and fails one that lies further below. Outside
    the slot, one coarse cell's battery is a float16 step below the winner's, and the battery's
    price sets how far its bound falls below the winner: 0.5e-9 in the first cell, 2e-9 in the
    second.
    """
    b_coarse = np.full((PARAMS.coarse_grid, PARAMS.coarse_grid), np.inf, dtype=np.float16)
    b_coarse[20, 20] = 1.0 - 2.0**-11
    cache = _store([_three_by_three((5, 7, 5, 7), (1, 1), b_coarse)] * 2, PARAMS)
    gap = 1.0 - (1.0 - 2.0**-11) ** GAMMA
    costs = CostArrays(a_s=np.zeros(2), a_w=np.zeros(2), a_b=np.array([0.5e-9, 2e-9]) / gap, d0=np.ones(2))
    optima = price_frontiers(cache, costs)

    _assert_equals_argmin_lcoe(cache, costs, optima)
    assert optima.patch_certified.tolist() == [True, False]


def test_the_certificate_at_its_edges_equals_argmin_lcoe():
    """
    `_containment_certificate` floors each coarse battery at zero before the power, and passes a
    coarse cell whose bound is at least the winner's LCOE less 1e-9. One coarse cell outside the
    slot decides each certificate here: a negative battery, which must count as zero; a bound
    exactly at the slack, which passes; and a bound one unit in the last place (ulp) below it, which
    fails. The last two winners use no solar, so that the price of solar alone moves the bound.
    """
    gc = PARAMS.coarse_grid
    negative = np.full((gc, gc), np.inf, dtype=np.float16)
    negative[20, 20] = -1.0
    at_slack = np.full((gc, gc), np.inf, dtype=np.float16)
    at_slack[3, 0] = 0.0
    no_solar = dataclasses.replace(
        _three_by_three((5, 7, 5, 7), (0, 0), at_slack), s_patch=np.array([[0.0, 1.0, 2.0]], dtype=np.float32)
    )
    cache = _store([_three_by_three((5, 7, 5, 7), (0, 0), negative), no_solar, no_solar], PARAMS)
    # The first winner costs 2 and the other two cost 1. At the coarse cell (3, 0), with a solar
    # size of 1, no wind and no battery, the bound is the price of solar.
    slack = 1.0 - 1e-9
    costs = CostArrays(
        a_s=np.array([1.0, slack, np.nextafter(slack, 0.0)]), a_w=np.zeros(3), a_b=np.ones(3), d0=np.ones(3)
    )
    optima = price_frontiers(cache, costs)

    _assert_equals_argmin_lcoe(cache, costs, optima)
    assert optima.lcoe.tolist() == [2.0, 1.0, 1.0]
    assert optima.patch_certified.tolist() == [True, True, False]


def test_a_solved_cell_without_a_feasible_design_raises_as_argmin_lcoe_does():
    """
    A solved cell whose every node is infeasible is a broken store, not a result. `argmin_lcoe`
    raises on it, so the kernel must raise too rather than report a cell as unpriced.
    """
    rng = np.random.default_rng(7)
    cache = _store([_hand_made(rng, 2), _hand_made(rng, 2, no_design=True)], SIX_RUNGS)
    costs = _random_costs(2)

    with pytest.raises(ValueError):
        argmin_lcoe(frontier_at(cache, 1), CostCoefficients(1.0, 1.0, 1.0, 1.0))
    with pytest.raises(ValueError, match="cell 1 "):
        price_frontiers(cache, costs)
    price_frontiers(cache, CostArrays(*(x[:1] for x in dataclasses.astuple(costs))), np.array([0]))


def test_negative_patch_bounds_raise():
    """
    The kernel tests coarse cells against each slot's bounds where `argmin_lcoe` slices with them.
    A negative bound slices from the far end of the grid, so it must raise rather than give
    another certificate.
    """
    frontier = _hand_made(np.random.default_rng(3), 2)
    frontier.patch_bounds[1, 0] = -1
    cache = _store([frontier], SIX_RUNGS)
    with pytest.raises(ValueError, match="negative"):
        price_frontiers(cache, _random_costs(1))


def test_patch_bounds_beyond_the_coarse_grid_give_argmin_lcoes_answer():
    """
    A slice clamps a bound beyond the far end of the coarse grid, so the kernel must read such a
    bound as reaching the grid's edge, as `argmin_lcoe` does, not refuse it. The first slot reaches
    past the grid's far corner and covers the grid's one cheap coarse cell, so its cell is
    certified only if the bound is read that way; the second slot lies wholly beyond the grid and
    covers nothing.
    """
    gc = PARAMS.coarse_grid
    b_coarse = np.full((gc, gc), np.inf, dtype=np.float16)
    b_coarse[gc - 1, gc - 1] = 0.0
    frontiers = [
        _three_by_three((gc - 3, gc + 5, gc - 3, gc + 5), (1, 1), b_coarse),
        _three_by_three((gc + 1, gc + 3, gc + 1, gc + 3), (1, 1), b_coarse),
    ]
    cache = _store(frontiers, PARAMS)
    costs = _battery_only(cache.n_points)
    optima = price_frontiers(cache, costs)

    _assert_equals_argmin_lcoe(cache, costs, optima)
    assert optima.patch_certified.tolist() == [True, False]


def test_batch_size_and_cell_order_do_not_change_the_result(hand_made_store, built_stores):
    """
    A batch of consecutive cells is read as views of the store, and any other batch is gathered.
    Neither the batch size nor the order or choice of the cells may change any cell's answer,
    including at batch edges: all cells, the cells in a shuffled order, every third cell, and a run
    of cells that starts inside the store.
    """
    cache = hand_made_store
    costs = _random_costs(cache.n_points, seed=2)
    whole = price_frontiers(cache, costs)
    for batch_cells in (1, 7, 1024):
        _assert_same_optima(price_frontiers(cache, costs, batch_cells=batch_cells), whole)

    order = np.random.default_rng(4).permutation(cache.n_points)
    for cells in (order, np.arange(0, cache.n_points, 3), np.arange(5, cache.n_points - 3)):
        listed = price_frontiers(
            cache, CostArrays(*(x[cells] for x in dataclasses.astuple(costs))), cells, batch_cells=7
        )
        _assert_same_optima(listed, FrontierOptima(*(x[cells] for x in dataclasses.astuple(whole))))

    cache = built_stores[1]
    costs = _random_costs(cache.n_points, seed=3)
    _assert_same_optima(price_frontiers(cache, costs, batch_cells=5), price_frontiers(cache, costs))


def test_no_cells_price_to_empty_results():
    """A caller can have no cell to price, so both `cost_arrays` and `price_frontiers` must take none."""
    costs = cost_arrays(
        25,
        {tech: np.zeros((0, 26)) for tech in TECHS},
        {tech: np.zeros(0) for tech in TECHS},
        np.zeros(0),
        np.zeros(0, dtype=np.float32),
    )
    for name in ("a_s", "a_w", "a_b", "d0"):
        assert getattr(costs, name).shape == (0,) and getattr(costs, name).dtype == np.float64, name

    cache = _store([_hand_made(np.random.default_rng(8), 1)], SIX_RUNGS)
    optima = price_frontiers(cache, costs, np.array([], dtype=np.int64))
    for field in dataclasses.fields(FrontierOptima):
        assert getattr(optima, field.name).shape == (0,), field.name


# --------------------------------------------------------------------------
# Cost coefficients
# --------------------------------------------------------------------------


@pytest.mark.parametrize("horizon", [25, 30])
def test_cost_arrays_equal_lcoe_coefficients_bit_for_bit(horizon):
    """
    `cost_arrays` evaluates the cost terms once per distinct set of costs and multiplies them by
    each cell's load, so it must equal the per-cell call bit for bit: with loads in float32, as
    `pixel_area` returns them for the store's latitudes, and at a horizon of 30 years, where the
    25-year technologies are installed twice and capex at the horizon counts.

    The cells share twelve cost keys: one base key; for each of the ten inputs the coefficients
    read, a key that differs from it in that input alone, so that grouping on any fewer inputs
    would merge two keys; and a key one unit in the last place (ulp) above the base in its wind
    capex in year 0, so that grouping on rounded values would merge that key with the base. Two
    cells, of the base key and of the one-ulp key, have a load of 1 MW, which scales their
    coefficients exactly, so they differ in the last bit and must still be priced apart. One cell
    also differs in a capex year the coefficients never read, and one has no key and is priced at
    zero.
    """
    rng = np.random.default_rng(horizon)
    capex_keys = {tech: np.tile(rng.uniform(1.0e5, 2.0e6, horizon + 1), (12, 1)) for tech in TECHS}
    opex_keys = {tech: np.full(12, rng.uniform(0.0, 0.03)) for tech in TECHS}
    coc_keys = np.full(12, rng.uniform(0.03, 0.12))
    inputs = [capex_keys[tech][:, year] for tech in TECHS for year in (0, horizon)]
    for key, column in enumerate([*inputs, *opex_keys.values(), coc_keys], start=1):
        column[key] *= 1.01
    capex_keys["wind"][11, 0] = np.nextafter(capex_keys["wind"][11, 0], np.inf)

    n = 200
    key = rng.integers(0, 12, n)
    key[2:4] = 0, 11
    capex = {tech: capex_keys[tech][key] for tech in TECHS}
    opex = {tech: opex_keys[tech][key] for tech in TECHS}
    coc = coc_keys[key]
    capex["solar"][1, 5] += 1.0
    for values in (*capex.values(), *opex.values(), coc):
        values[0] = 0.0
    load_mw = 1.0 * pixel_area(rng.uniform(-70.0, 70.0, n).astype(np.float32))
    load_mw[2:4] = 1.0
    assert load_mw.dtype == np.float32

    costs = cost_arrays(horizon, capex, opex, coc, load_mw)
    assert costs.a_w[2] != costs.a_w[3], "keys one ulp apart price alike, so this test cannot tell them apart"
    for k in range(n):
        want = lcoe_coefficients(
            horizon,
            {tech: capex[tech][k] for tech in TECHS},
            {tech: float(opex[tech][k]) for tech in TECHS},
            float(coc[k]),
            float(load_mw[k]),
        )
        got = (costs.a_s[k], costs.a_w[k], costs.a_b[k], costs.d0[k])
        assert [float(x).hex() for x in got] == [float(x).hex() for x in dataclasses.astuple(want)], f"cell {k}"


# --------------------------------------------------------------------------
# The query worker
# --------------------------------------------------------------------------


def _region_costs(rng: np.random.Generator, n: int, horizon: int) -> tuple[dict, dict, np.ndarray]:
    """
    Costs laid out as `_derive_cost_arrays` returns them, for `n` cells sharing five cost keys,
    the first cell without a key and so priced at zero, as `_derive_cost_arrays` leaves it.
    """
    key = rng.integers(0, 5, n)
    capex = {tech: rng.uniform(1.0e5, 2.0e6, (5, horizon + 1))[key] for tech in TECHS}
    opex = {tech: rng.uniform(0.0, 0.03, 5)[key] for tech in TECHS}
    coc = rng.uniform(0.03, 0.12, 5)[key]
    for values in (*capex.values(), *opex.values(), coc):
        values[0] = 0.0
    return capex, opex, coc


def _per_cell_tile(tile_indices, cache, capex_per_tech, opex_per_tech, coc_arr, cost_keys, load_mw, horizon):
    """`_query_frontier_tile` as per-cell calls: `lcoe_coefficients` and `argmin_lcoe` for each solved cell."""
    results = []
    counters = {"certified": 0, "truncated": 0, "no_optimum": 0, "zero_potential": 0}
    for k in tile_indices:
        known = {
            "cost_of_capital": float(coc_arr[k]),
            "cost_key": str(cost_keys[k]) if cost_keys[k] else "",
            "load_mw": float(load_mw[k]),
        }
        status = int(cache.status[k])
        if status != STATUS_OK:
            counters["zero_potential" if status == STATUS_ZERO_POTENTIAL else "no_optimum"] += 1
            nothing = {tech: np.nan for tech in TECHS}
            results.append(
                {
                    "design": nothing,
                    "lcoe": np.nan,
                    "lcoe_coverage_based": np.nan,
                    "installation_cost": np.nan,
                    "installation_cost_breakdown": dict(nothing),
                    "coverage": np.nan,
                    "served_fraction": np.nan,
                    "status": status,
                    **known,
                }
            )
            continue
        capex_k = {tech: capex_per_tech[tech][k] for tech in TECHS}
        opex_k = {tech: float(opex_per_tech[tech][k]) for tech in TECHS}
        coeffs = lcoe_coefficients(horizon, capex_k, opex_k, float(coc_arr[k]), float(load_mw[k]))
        optimum = argmin_lcoe(frontier_at(cache, int(k)), coeffs)
        total, ic_s, ic_w, ic_b = installation_cost_breakdown(
            optimum.solar, optimum.wind, optimum.battery, float(load_mw[k]), capex_k
        )
        counters["certified"] += int(optimum.patch_certified)
        counters["truncated"] += int(optimum.argmin_truncated)
        results.append(
            {
                "design": {"solar": optimum.solar, "wind": optimum.wind, "battery": optimum.battery},
                "lcoe": optimum.lcoe,
                "lcoe_coverage_based": optimum.lcoe * optimum.served_fraction,
                "installation_cost": total,
                "installation_cost_breakdown": {"solar": ic_s, "wind": ic_w, "battery": ic_b},
                "coverage": optimum.hours_covered,
                "served_fraction": optimum.served_fraction,
                "status": STATUS_OK,
                **known,
            }
        )
    return results, counters


def _exact(value):
    """A result with every float in its exact hexadecimal form, so that equal means bit for bit."""
    if isinstance(value, dict):
        return {key: _exact(item) for key, item in value.items()}
    return value.hex() if isinstance(value, float) else value


@pytest.mark.parametrize("rungs", [1, 6])
def test_the_worker_equals_its_per_cell_form_down_to_the_file(built_stores, rungs, tmp_path):
    """
    The query worker prices through the kernel, so every number it reports, and the file the query
    writes from them, must equal what per-cell calls of `argmin_lcoe` give. The cells come in a
    shuffled order, as a strided tile lists them, and the loads in float32, as the query computes
    them.
    """
    cache = built_stores[rungs]
    n = cache.n_points
    rng = np.random.default_rng(rungs)
    capex, opex, coc = _region_costs(rng, n, 25)
    keys = np.array([""] + [f"KEY{i % 5}" for i in range(1, n)])
    load_mw = 1.0 * pixel_area(cache.lats)
    tile = rng.permutation(n)

    _, results, counters = _query_frontier_tile(tile, cache, capex, opex, coc, keys, load_mw, 25)
    reference, reference_counters = _per_cell_tile(tile, cache, capex, opex, coc, keys, load_mw, 25)

    assert counters == reference_counters
    assert [_exact(r) for r in results] == [_exact(r) for r in reference]
    attrs = {"region": "TESTREGION", "created_at": "2026-10-19T00:00:00+00:00"}
    grid = (n, cache.all_lats, cache.all_lons, cache.iy, cache.ix, attrs)
    _assemble_optimal_sol([tile], [results], *grid, tmp_path / "kernel.nc")
    _assemble_optimal_sol([tile], [reference], *grid, tmp_path / "per_cell.nc")
    assert (tmp_path / "kernel.nc").read_bytes() == (tmp_path / "per_cell.nc").read_bytes()


@pytest.mark.parametrize("tile", ["unsolved", "empty"])
def test_the_worker_reports_a_tile_with_no_solved_cell_as_its_per_cell_form_does(hand_made_store, tile):
    """
    Every run has a region with no solved cell, as KERGUELEN's twelve cells are at every level, and
    the worker may be handed an empty tile. Neither holds anything to price, and the worker must
    report each as its per-cell form does.
    """
    cache = hand_made_store
    n = cache.n_points
    capex, opex, coc = _region_costs(np.random.default_rng(9), n, 25)
    keys = np.array([""] + [f"KEY{i % 5}" for i in range(1, n)])
    load_mw = 1.0 * pixel_area(cache.lats)
    cells = np.flatnonzero(cache.status != STATUS_OK) if tile == "unsolved" else np.array([], dtype=np.int64)

    _, results, counters = _query_frontier_tile(cells, cache, capex, opex, coc, keys, load_mw, 25)
    reference, reference_counters = _per_cell_tile(cells, cache, capex, opex, coc, keys, load_mw, 25)

    assert counters == reference_counters
    assert [_exact(r) for r in results] == [_exact(r) for r in reference]
    assert len(results) == (2 if tile == "unsolved" else 0)
