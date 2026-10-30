"""
Make the data figures of the `methodology` page from synthetic test profiles.

    uv run python docs_figures/methodology_figures.py

Output (in `docs/assets/methodology/`):

- `f3_dispatch_rules.svg`: the hourly energy balance of one design for three days (figure F3,
  methodology variant).
- `f5_frontier.svg`: the minimum battery and its LCOE over the (solar, wind) plane of one pixel
  (figure F5).
- `f6_search_stages.svg`: the coarse grid, the seeds, the patches and the query results of one
  pixel (figure F6).

All three figures use one synthetic pixel: the "Sunny" pixel of the `overview` figures (strong
sun, some wind), at a coverage target of 0.85. The profiles come from the generators in
`tests/conftest.py`. The cost coefficients are illustrative and not calibrated, so the figures
show LCOE as an index, not in USD/MWh. The search is the production code (`build_pixel_frontier`,
`argmin_lcoe`, `b_min_at`) with the default `SearchParams`.
"""

import importlib.util
import sys

import _style
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from _style import BATTERY, DEMAND, NEUTRAL, REPO_ROOT, SOLAR, UNMET, WIND
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

sys.path.insert(0, str(REPO_ROOT / "src"))

from boa.model.bisection import (
    GAMMA,
    STATUS_OK,
    CostCoefficients,
    SearchParams,
    anchor_score,
    argmin_lcoe,
    b_min_at,
    build_pixel_frontier,
    dispatch_metrics,
    search_box,
    select_seeds,
)

PAGE = "methodology"
COVERAGE = 0.85
PARAMS = SearchParams()

# Cost coefficients. A is the `anchor_costs` fixture of tests/conftest.py and the cost set of the
# `overview` figures. B has cheaper solar and battery, C has cheaper wind. All are illustrative.
D0 = 8.76e6
COST_SETS = {
    "A": CostCoefficients(a_s=1.0e6, a_w=1.6e6, a_b=0.30e6, d0=D0),
    "B": CostCoefficients(a_s=0.6e6, a_w=1.8e6, a_b=0.20e6, d0=D0),
    "C": CostCoefficients(a_s=1.4e6, a_w=1.0e6, a_b=0.40e6, d0=D0),
}
ANCHOR_MARKERS = {"A": "o", "B": "s", "C": "^"}
ANCHOR_COLOURS = {"A": NEUTRAL[0], "B": NEUTRAL[1], "C": NEUTRAL[3]}

# F6: the (solar, wind) region that panel (b) shows, and where the labels of the results go.
F6_ZOOM = (7.8, 6.5)
F6_LABEL_OFFSETS = {"A": (-60, 22), "B": (12, 10), "C": (10, 10)}

# F3: the three days that the figure shows (hours 192 to 263 of the three-week series).
F3_HOURS = slice(192, 264)

# F5: points per axis of the reference grid. 97 points give half the spacing of the patch lattice
# (the coarse spacing is 1/24 of the box, and the patch lattice halves it). The reference
# bisection runs to a relative tolerance of 1e-4 instead of the default 1e-2.
F5_POINTS = 97
F5_PARAMS = SearchParams(tol_rel_patch=1e-4)
# F5: the (solar, wind) region that panel (b) shows.
F5_ZOOM = (6.0, 6.0)

CURTAIL = "#999999"
INFEASIBLE = "#D9D9D9"


def _pixel() -> tuple[np.ndarray, np.ndarray]:
    """The "Sunny" pixel of the overview figures, from the generators in `tests/conftest.py`."""
    spec = importlib.util.spec_from_file_location("boa_test_fixtures", REPO_ROOT / "tests" / "conftest.py")
    fx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fx)
    return fx._daily_solar(peak=0.8), fx._noisy_wind(mean=0.25)


def _dispatch_flows(solar: np.ndarray, wind: np.ndarray, s: float, w: float, b: float) -> dict[str, np.ndarray]:
    """
    The hourly energy flows of one design, in multiples of the demand.

    The same rules as `bisection.dispatch_metrics`, written out per flow. The battery starts
    empty. Surplus generation charges the battery up to its capacity, and the rest is curtailed.
    A deficit is taken from the battery as far as its charge permits, and the rest is unmet.
    """
    n = solar.shape[0]
    out = {k: np.zeros(n) for k in ("direct", "charge", "curtail", "discharge", "unmet", "soc", "covered")}
    prev = 0.0
    for t in range(n):
        gen = s * solar[t] + w * wind[t]
        net = gen - 1.0
        available = prev + net
        out["covered"][t] = available >= 0.0
        current = min(max(available, 0.0), b)
        out["direct"][t] = min(gen, 1.0)
        if net >= 0.0:
            out["charge"][t] = current - prev
            out["curtail"][t] = net - (current - prev)
        else:
            out["discharge"][t] = prev - current
            out["unmet"][t] = -net - (prev - current)
        out["soc"][t] = current
        prev = current
    return out


def figure_dispatch_rules(solar: np.ndarray, wind: np.ndarray) -> None:
    """F3 (methodology variant): where the energy goes in each hour, for three days."""
    frontier = build_pixel_frontier(solar, wind, COVERAGE, PARAMS, COST_SETS["A"])
    opt = argmin_lcoe(frontier, COST_SETS["A"])
    s, w, b = opt.solar, opt.wind, opt.battery
    flows = _dispatch_flows(solar, wind, s, w, b)

    # The figure must show the same physics as the search: check against the fast kernel.
    hours_covered, served = dispatch_metrics(solar, wind, s, w, b)
    assert np.isclose(flows["covered"].mean(), hours_covered)
    assert np.isclose(1.0 - flows["unmet"].mean(), served)

    sl = F3_HOURS
    hours = np.arange(sl.stop - sl.start)
    gen = (s * solar + w * wind)[sl]
    solar_share = np.divide(s * solar[sl], gen, out=np.zeros_like(gen), where=gen > 0)
    direct = flows["direct"][sl]
    layers = [
        (direct * (1.0 - solar_share), WIND, None, "Wind to demand"),
        (direct * solar_share, SOLAR, None, "Solar to demand"),
        (flows["discharge"][sl], BATTERY, None, "Battery discharge to demand"),
        (flows["unmet"][sl], UNMET, None, "Unmet demand"),
        (flows["charge"][sl], "#FFFFFF", BATTERY, "Surplus that charges the battery"),
        (flows["curtail"][sl], CURTAIL, None, "Curtailed surplus"),
    ]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.0, 5.6), sharex=True, height_ratios=[3, 2])
    base = np.zeros_like(gen)
    handles = []
    for values, colour, hatch_colour, label in layers:
        top = base + values
        if hatch_colour is None:
            ax1.fill_between(hours, base, top, step="mid", color=colour, linewidth=0)
            handles.append(Patch(facecolor=colour, label=label))
        else:
            ax1.fill_between(
                hours, base, top, step="mid", facecolor=colour, edgecolor=hatch_colour, hatch="////", linewidth=0
            )
            handles.append(Patch(facecolor=colour, edgecolor=hatch_colour, hatch="////", label=label))
        base = top
    ax1.axhline(1.0, color=DEMAND, linewidth=1.4)
    handles.append(Line2D([0], [0], color=DEMAND, linewidth=1.4, label="Demand (1)"))
    ax1.set_ylabel("Energy in the hour\n(multiples of demand)")
    ax1.set_ylim(bottom=0)

    ax2.fill_between(hours, 0, flows["soc"][sl], step="mid", color=BATTERY, alpha=0.85, linewidth=0)
    ax2.axhline(b, color=BATTERY, linewidth=1.2, linestyle="--")
    handles.append(Patch(facecolor=BATTERY, alpha=0.85, label="Battery charge at the end of the hour"))
    handles.append(Line2D([0], [0], color=BATTERY, linestyle="--", label=f"Battery capacity ({b:.1f} h)"))
    for h in np.flatnonzero(flows["covered"][sl] == 0):
        ax2.axvspan(h - 0.5, h + 0.5, color=UNMET, alpha=0.30, linewidth=0)
    handles.append(Patch(facecolor=UNMET, alpha=0.30, label="Hour not covered"))
    ax2.set_ylabel("Battery charge\n(hours of demand)")
    ax2.set_ylim(0, b * 1.15)
    ax2.set_xlabel("Hour of the three days shown")
    ax2.set_xticks(np.arange(0, len(hours) + 1, 12))
    ax2.set_xlim(-0.5, len(hours) - 0.5)

    ax1.set_title(
        f"Design: solar {s:.2f}, wind {w:.2f}, battery {b:.1f} h  |  "
        f"over three weeks: coverage {hours_covered:.3f}, served fraction {served:.3f}",
        fontsize=9,
        loc="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.0), fontsize=8.5)
    _style.save(fig, PAGE, "f3_dispatch_rules.svg")


def _reference_grid(solar: np.ndarray, wind: np.ndarray) -> tuple[np.ndarray, ...]:
    """Minimum battery, served fraction and LCOE (cost set A) on a fine grid over the search box."""
    s_max, w_max = search_box(solar, wind, PARAMS)
    s_vals = np.linspace(0.0, s_max, F5_POINTS)
    w_vals = np.linspace(0.0, w_max, F5_POINTS)
    b_min = np.empty((F5_POINTS, F5_POINTS))
    served = np.empty((F5_POINTS, F5_POINTS))
    for i, s in enumerate(s_vals):
        for j, w in enumerate(w_vals):
            b_min[i, j], _, served[i, j] = b_min_at(solar, wind, s, w, COVERAGE, F5_PARAMS)
    c = COST_SETS["A"]
    feasible = np.isfinite(b_min)
    numerator = c.a_s * s_vals[:, None] + c.a_w * w_vals[None, :] + c.a_b * np.where(feasible, b_min, 0.0) ** GAMMA
    lcoe = np.where(feasible, numerator / (c.d0 * np.where(served > 0, served, 1.0)), np.nan)
    return s_vals, w_vals, b_min, lcoe, s_max, w_max


def figure_frontier(solar: np.ndarray, wind: np.ndarray) -> None:
    """F5: the minimum battery b_min(s, w) and the LCOE of that design, for one pixel."""
    s_vals, w_vals, b_min, lcoe, s_max, w_max = _reference_grid(solar, wind)
    i_ref, j_ref = np.unravel_index(int(np.nanargmin(lcoe)), lcoe.shape)
    ref_lcoe = float(lcoe[i_ref, j_ref])

    frontier = build_pixel_frontier(solar, wind, COVERAGE, PARAMS, COST_SETS["A"])
    opt = argmin_lcoe(frontier, COST_SETS["A"])
    gap = 100.0 * (opt.lcoe / ref_lcoe - 1.0)
    print(
        f"F5: reference minimum s={s_vals[i_ref]:.3f} w={w_vals[j_ref]:.3f} b={b_min[i_ref, j_ref]:.3f}; "
        f"search s={opt.solar:.3f} w={opt.wind:.3f} b={opt.battery:.3f}; LCOE gap {gap:.2f} %; "
        f"certified={opt.patch_certified}, truncated={opt.argmin_truncated}"
    )

    extent = (0.0, s_max, 0.0, w_max)
    cut = PARAMS.corner_cut_threshold
    cut_s = np.linspace(0.0, s_max, 50)
    cut_w = w_max * (cut - cut_s / s_max)
    on_box = (cut_w >= 0.0) & (cut_w <= w_max)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 4.6))
    grey = mcolors.ListedColormap([INFEASIBLE])

    # (a) Minimum battery. Zero is shown in white: generation alone meets the target there.
    feasible = np.isfinite(b_min)
    positive = feasible & (b_min > 0)
    infeasible_layer = np.ma.masked_where(feasible.T, np.ones_like(b_min.T))
    ax1.imshow(infeasible_layer, origin="lower", extent=extent, aspect="auto", cmap=grey, interpolation="nearest")
    norm = mcolors.LogNorm(vmin=0.1, vmax=float(np.nanmax(np.where(positive, b_min, np.nan))))
    shown = np.where(positive, np.maximum(b_min, 0.1), np.nan)
    im = ax1.imshow(
        shown.T, origin="lower", extent=extent, aspect="auto", cmap="viridis", norm=norm, interpolation="nearest"
    )
    levels = [0.5, 1, 2, 4, 8]
    cs = ax1.contour(s_vals, w_vals, np.where(positive, b_min, np.nan).T, levels=levels, colors="black", linewidths=0.7)
    ax1.clabel(cs, fmt="%g h", fontsize=7)
    fig.colorbar(im, ax=ax1, label="Minimum battery (hours of demand)", pad=0.02)
    ax1.set_title("(a) Minimum battery that meets the coverage target", fontsize=9.5, loc="left")

    # (b) LCOE of the design with the minimum battery, as an index (reference minimum = 100).
    index = 100.0 * lcoe / ref_lcoe
    ax2.imshow(infeasible_layer, origin="lower", extent=extent, aspect="auto", cmap=grey, interpolation="nearest")
    vmax = 130.0
    im2 = ax2.imshow(
        np.minimum(index, vmax).T,
        origin="lower",
        extent=extent,
        aspect="auto",
        cmap="cividis_r",
        vmin=100.0,
        vmax=vmax,
        interpolation="nearest",
    )
    cs2 = ax2.contour(s_vals, w_vals, index.T, levels=[102, 105, 110, 120], colors="black", linewidths=0.7)
    ax2.clabel(cs2, fmt="%g", fontsize=7)
    fig.colorbar(im2, ax=ax2, label="LCOE index (reference minimum = 100)", pad=0.02)
    ax2.plot(
        s_vals[i_ref],
        w_vals[j_ref],
        marker="*",
        markersize=14,
        color="white",
        markeredgecolor="black",
        linestyle="none",
        label="Minimum on the reference grid",
        clip_on=False,
        zorder=5,
    )
    ax2.plot(
        opt.solar,
        opt.wind,
        marker="D",
        markersize=8,
        color=NEUTRAL[1],
        markeredgecolor="black",
        linestyle="none",
        label=f"Result of the search ({gap:+.1f} %)",
        clip_on=False,
        zorder=5,
    )
    ax2.set_title("(b) LCOE of that design, cost set A (detail)", fontsize=9.5, loc="left")

    ax1.plot(cut_s[on_box], cut_w[on_box], color="black", linestyle="--", linewidth=1.0)
    ax1.set_xlim(0, s_max)
    ax1.set_ylim(0, w_max)
    ax2.set_xlim(0, F5_ZOOM[0])
    ax2.set_ylim(0, F5_ZOOM[1])
    ax1.add_patch(Rectangle((0, 0), F5_ZOOM[0], F5_ZOOM[1], fill=False, edgecolor=NEUTRAL[1], linewidth=1.2))
    for ax in (ax1, ax2):
        ax.set_xlabel("Solar factor s (MW per MW of demand)")
        ax.set_ylabel("Wind factor w (MW per MW of demand)")
        ax.grid(False)

    handles = [
        Patch(facecolor=INFEASIBLE, label="No battery of 256 h or less meets the target"),
        Patch(facecolor="white", edgecolor="#999999", label="No battery needed"),
        Line2D([0], [0], color="black", linestyle="--", label="Corner cut of the search"),
        Patch(facecolor="none", edgecolor=NEUTRAL[1], label="Region shown in (b)"),
    ] + ax2.get_legend_handles_labels()[0]
    fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.08), fontsize=8.5)
    fig.tight_layout()
    _style.save(fig, PAGE, "f5_frontier.svg")


def figure_search_stages(solar: np.ndarray, wind: np.ndarray) -> None:
    """F6: coarse grid and seeds (left); patches and query results (right)."""
    anchors = list(COST_SETS.values())
    frontier = build_pixel_frontier(solar, wind, COVERAGE, PARAMS, anchors)
    assert frontier.status == STATUS_OK
    s_c = frontier.s_coarse.astype(np.float64)
    w_c = frontier.w_coarse.astype(np.float64)
    b_c = frontier.b_coarse.astype(np.float64)
    gc = s_c.shape[0]
    s_max, w_max = float(s_c[-1]), float(w_c[-1])
    lattice = np.unique(np.append(np.arange(0, gc, PARAMS.coarse_stride), gc - 1))

    # Replay the seed selection of each anchor on the stored coarse grid (the same calls as in
    # `build_pixel_frontier`), to show which anchor proposed which seed.
    seeds = {}
    for name, coeffs in COST_SETS.items():
        scores = anchor_score(s_c[lattice], w_c[lattice], b_c[np.ix_(lattice, lattice)], coeffs)
        seeds[name] = [
            (int(lattice[a]), int(lattice[b]))
            for a, b in select_seeds(scores, PARAMS.seed_tolerance, 2, PARAMS.max_seeds)
        ]

    winners = {name: argmin_lcoe(frontier, coeffs) for name, coeffs in COST_SETS.items()}
    for name, o in winners.items():
        print(
            f"F6: cost set {name}: patch {o.patch_index}, s={o.solar:.3f} w={o.wind:.3f} b={o.battery:.3f}, "
            f"certified={o.patch_certified}, truncated={o.argmin_truncated}"
        )

    finite = np.isfinite(b_c)
    positive_max = float(np.nanmax(np.where(finite, b_c, np.nan)))
    norm = mcolors.LogNorm(vmin=0.1, vmax=max(positive_max, 1.0))
    cmap = plt.get_cmap("viridis")
    sg, wg = np.meshgrid(s_c, w_c, indexing="ij")
    on_lattice = np.zeros((gc, gc), dtype=bool)
    on_lattice[np.ix_(lattice, lattice)] = True

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.4, 4.9))

    # (a) Coarse grid: lower bound on the minimum battery, solved lattice nodes, seeds.
    for mask, size, edge in ((~on_lattice, 14, "none"), (on_lattice, 46, "black")):
        pos = mask & finite & (b_c > 0)
        zero = mask & finite & (b_c <= 0)
        ax1.scatter(
            sg[pos],
            wg[pos],
            c=np.maximum(b_c[pos], 0.1),
            cmap=cmap,
            norm=norm,
            s=size,
            marker="s",
            edgecolors=edge,
            linewidths=0.5,
            zorder=2,
        )
        ax1.scatter(
            sg[zero], wg[zero], color="white", s=size, marker="s", edgecolors="#777777", linewidths=0.5, zorder=2
        )
    ax1.scatter(sg[~finite], wg[~finite], marker="x", color="#AAAAAA", s=14, linewidths=0.8, zorder=2)
    for name, cells in seeds.items():
        for i, j in cells:
            ax1.scatter(
                s_c[i],
                w_c[j],
                marker=ANCHOR_MARKERS[name],
                s=170,
                facecolors="none",
                edgecolors=ANCHOR_COLOURS[name],
                linewidths=2.0,
                zorder=4,
            )
    ax1.set_title("(a) Coarse grid and seeds", fontsize=9.5, loc="left")

    # (b) Patches: the union of the snapped patch boxes, their lattice nodes, and the query results.
    for slot in range(frontier.n_patches):
        i0, i1, j0, j1 = (int(x) for x in frontier.patch_bounds[slot])
        ax2.add_patch(
            Rectangle(
                (s_c[i0], w_c[j0]),
                s_c[i1] - s_c[i0],
                w_c[j1] - w_c[j0],
                fill=False,
                edgecolor="black",
                linestyle="--",
                linewidth=1.2,
                zorder=3,
            )
        )
        n_s, n_w = (int(x) for x in frontier.patch_points[slot])
        ps, pw = np.meshgrid(frontier.s_patch[slot, :n_s], frontier.w_patch[slot, :n_w], indexing="ij")
        pb = frontier.b_patch[slot, :n_s, :n_w, 0].astype(np.float64)
        ok = np.isfinite(pb)
        pos = ok & (pb > 0)
        ax2.scatter(
            ps[pos], pw[pos], c=np.maximum(pb[pos], 0.1), cmap=cmap, norm=norm, s=9, marker="o", linewidths=0, zorder=2
        )
        ax2.scatter(
            ps[ok & (pb <= 0)], pw[ok & (pb <= 0)], color="white", edgecolors="#777777", s=9, linewidths=0.4, zorder=2
        )
        ax2.scatter(ps[~ok], pw[~ok], marker="x", color="#AAAAAA", s=9, linewidths=0.6, zorder=2)
    for name, o in winners.items():
        ax2.scatter(
            o.solar, o.wind, marker="*", s=260, color=ANCHOR_COLOURS[name], edgecolors="black", linewidths=0.8, zorder=5
        )
        ax2.annotate(
            f"{name}: s = {o.solar:.2f}, w = {o.wind:.2f}, b = {o.battery:.1f} h",
            (o.solar, o.wind),
            textcoords="offset points",
            xytext=F6_LABEL_OFFSETS[name],
            fontsize=8,
            zorder=6,
            bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "#999999"},
        )
    ax2.set_title("(b) Patches and the cheapest stored design per cost set", fontsize=9.5, loc="left")

    cut = PARAMS.corner_cut_threshold
    cut_s = np.linspace(0.0, s_max, 50)
    cut_w = w_max * (cut - cut_s / s_max)
    on_box = (cut_w >= 0.0) & (cut_w <= w_max)
    ax1.plot(cut_s[on_box], cut_w[on_box], color="black", linestyle=":", linewidth=1.0)
    ax1.set_xlim(-0.3, s_max + 0.3)
    ax1.set_ylim(-0.3, w_max + 0.3)
    ax1.add_patch(
        Rectangle((-0.2, -0.2), F6_ZOOM[0] + 0.2, F6_ZOOM[1] + 0.2, fill=False, edgecolor=NEUTRAL[1], linewidth=1.2)
    )
    ax2.set_xlim(-0.2, F6_ZOOM[0])
    ax2.set_ylim(-0.2, F6_ZOOM[1])
    for ax in (ax1, ax2):
        ax.set_xlabel("Solar factor s (MW per MW of demand)")
        ax.set_ylabel("Wind factor w (MW per MW of demand)")

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    fig.colorbar(sm, ax=[ax1, ax2], label="Battery (hours of demand)", pad=0.02, fraction=0.03)

    handles = [
        Line2D(
            [0],
            [0],
            marker="s",
            linestyle="none",
            markerfacecolor=cmap(0.5),
            markeredgecolor="black",
            markersize=7,
            label="Solved coarse node (lower bound)",
        ),
        Line2D(
            [0],
            [0],
            marker="s",
            linestyle="none",
            markerfacecolor=cmap(0.5),
            markeredgecolor="none",
            markersize=4,
            label="Filled coarse node (lower bound)",
        ),
        Line2D([0], [0], marker="x", linestyle="none", color="#AAAAAA", label="No feasible battery found"),
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markerfacecolor=cmap(0.5),
            markeredgecolor="none",
            markersize=4,
            label="Patch node (minimum battery)",
        ),
        Line2D([0], [0], color="black", linestyle=":", label="Corner cut"),
        Rectangle((0, 0), 1, 1, fill=False, edgecolor="black", linestyle="--", label="Patch box"),
        Rectangle((0, 0), 1, 1, fill=False, edgecolor=NEUTRAL[1], label="Region shown in (b)"),
    ]
    for name in COST_SETS:
        handles.append(
            Line2D(
                [0],
                [0],
                marker=ANCHOR_MARKERS[name],
                linestyle="none",
                markerfacecolor="none",
                markeredgecolor=ANCHOR_COLOURS[name],
                markeredgewidth=2,
                markersize=9,
                label=f"Seed of anchor {name}",
            )
        )
    handles.append(
        Line2D(
            [0],
            [0],
            marker="*",
            linestyle="none",
            markerfacecolor="#BBBBBB",
            markeredgecolor="black",
            markersize=12,
            label="Cheapest stored design",
        )
    )
    fig.legend(handles=handles, loc="upper center", ncol=4, bbox_to_anchor=(0.46, 1.13), fontsize=8.5)
    _style.save(fig, PAGE, "f6_search_stages.svg")


def main() -> None:
    _style.apply()
    solar, wind = _pixel()
    figure_dispatch_rules(solar, wind)
    figure_frontier(solar, wind)
    figure_search_stages(solar, wind)


if __name__ == "__main__":
    main()
