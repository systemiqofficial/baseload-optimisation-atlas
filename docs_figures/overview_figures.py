"""
Make the data figures of the `overview` page from synthetic test profiles.

    uv run python docs_figures/overview_figures.py

Output (in `docs/assets/overview/`):

- `f3_dispatch_week.svg`: one week of hourly dispatch at one synthetic pixel (figure F3).
- `f4_lcoe_vs_coverage.svg`: LCOE against the coverage target for four synthetic pixels (F4).

The profiles come from the generators in `tests/conftest.py`, and the cost coefficients are the
values of its `anchor_costs` fixture. They are illustrative and not calibrated, so the figures
show LCOE as an index, not in USD/MWh. The search is the production code: `build_pixel_frontier`
and `argmin_lcoe` with the default `SearchParams`.
"""

import importlib.util
import sys

import numpy as np

import _style
from _style import BATTERY, DEMAND, REPO_ROOT, SOLAR, UNMET, WIND

import matplotlib.pyplot as plt  # noqa: E402  (after _style sets the backend)

sys.path.insert(0, str(REPO_ROOT / "src"))

from boa.model.bisection import (  # noqa: E402
    CostCoefficients,
    SearchParams,
    argmin_lcoe,
    build_pixel_frontier,
    dispatch_metrics,
)
from boa.model.logic import state_of_charge  # noqa: E402

PAGE = "overview"

# Same values as the `anchor_costs` fixture in tests/conftest.py (illustrative, not calibrated).
COSTS = CostCoefficients(a_s=1.0e6, a_w=1.6e6, a_b=0.30e6, d0=8.76e6)

# Coverage target of the dispatch figure (F3).
F3_COVERAGE = 0.85
# The week that F3 shows: the second week of the three-week series, hours 168 to 335.
F3_WEEK = slice(168, 336)

# Coverage targets of F4. The upper end stays below 0.986, the highest coverage that the
# solar-only pixel can reach on this short series (the battery starts empty, so the first
# night of the series is always uncovered).
F4_COVERAGES = np.round(np.arange(0.50, 0.981, 0.02), 2)
# The LCOE index is 100 for this pixel at this coverage.
F4_REFERENCE = ("Mixed", 0.50)

# Line style of each F4 pixel: (colour, line style, marker). The colours are not the solar,
# wind, battery or demand colours of `_style`, because the lines are pixels, not technologies:
# wine and olive (Paul Tol "muted") and two greys. Each line also has its own line style and
# marker, so the lines stay different without colour.
F4_LINES = {
    "Mixed": ("#882255", "-", "o"),
    "Sunny": ("#999933", "--", "s"),
    "Solar only": ("#555555", "-.", "^"),
    "Poor resource": ("#999999", ":", "D"),
}


def _fixtures():
    """Load `tests/conftest.py` as a module, to reuse its profile generators."""
    spec = importlib.util.spec_from_file_location("boa_test_fixtures", REPO_ROOT / "tests" / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pixels(fx) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """The four synthetic pixels: three test fixtures and one more from the same generators."""
    return {
        # The `profiles` fixture: both technologies usable, neither dominant.
        "Mixed": (fx._daily_solar(), fx._noisy_wind()),
        # Stronger sun, weaker wind than `profiles`. Also the pixel of F3.
        "Sunny": (fx._daily_solar(peak=0.8), fx._noisy_wind(mean=0.25)),
        # The `solar_only_profiles` fixture.
        "Solar only": (fx._daily_solar(), np.zeros(fx.HOURS)),
        # The `poor_profiles` fixture: very low capacity factors for both technologies.
        "Poor resource": (fx._daily_solar(peak=0.04), fx._noisy_wind(mean=0.02, seed=1)),
    }


def _optimum(solar: np.ndarray, wind: np.ndarray, coverage: float):
    frontier = build_pixel_frontier(solar, wind, coverage, SearchParams(), COSTS)
    if frontier.status != 1:
        return None
    return argmin_lcoe(frontier, COSTS)


def figure_dispatch(solar: np.ndarray, wind: np.ndarray) -> None:
    """F3: hourly generation, demand, battery state of charge and uncovered hours for one week."""
    opt = _optimum(solar, wind, F3_COVERAGE)
    s, w, b = opt.solar, opt.wind, opt.battery

    # Dispatch with the production rules: `state_of_charge` (battery starts empty, surplus above
    # the capacity is lost), and an hour is covered when the charge of the previous hour plus
    # the net generation of this hour is not negative.
    net = s * solar + w * wind - 1.0
    soc = state_of_charge(net, b)
    soc_prev = np.concatenate(([0.0], soc[:-1]))
    covered = soc_prev + net >= 0.0

    # The figure must show the same physics as the search: check against the fast kernel.
    hours_covered, _ = dispatch_metrics(solar, wind, s, w, b)
    assert np.isclose(covered.mean(), hours_covered), (covered.mean(), hours_covered)

    hours = np.arange(F3_WEEK.stop - F3_WEEK.start)
    gen_wind = (w * wind)[F3_WEEK]
    gen_solar = (s * solar)[F3_WEEK]
    soc_week = soc[F3_WEEK]
    uncovered = ~covered[F3_WEEK]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.0, 5.2), sharex=True, height_ratios=[3, 2])
    for ax in (ax1, ax2):
        for h in np.flatnonzero(uncovered):
            ax.axvspan(h - 0.5, h + 0.5, color=UNMET, alpha=0.30, linewidth=0)

    ax1.fill_between(hours, 0, gen_wind, step="mid", color=WIND, alpha=0.85, linewidth=0, label="Wind generation")
    ax1.fill_between(
        hours, gen_wind, gen_wind + gen_solar, step="mid", color=SOLAR, alpha=0.85, linewidth=0, label="Solar generation"
    )
    ax1.axhline(1.0, color=DEMAND, linewidth=1.6, label="Demand")
    ax1.set_ylabel("Power\n(multiples of demand)")
    ax1.set_ylim(bottom=0)

    ax2.fill_between(hours, 0, soc_week, step="mid", color=BATTERY, alpha=0.85, linewidth=0, label="Battery charge")
    ax2.axhline(b, color=BATTERY, linewidth=1.2, linestyle="--", label=f"Battery capacity ({b:.1f} h)")
    ax2.set_ylabel("Battery charge\n(hours of demand)")
    ax2.set_ylim(0, b * 1.15)
    ax2.set_xlabel("Day of the week shown")
    ax2.set_xticks(np.arange(0, len(hours) + 1, 24))
    ax2.set_xticklabels([str(d) for d in range(1, 9)])
    ax2.set_xlim(-0.5, len(hours) - 0.5)

    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    unmet_patch = plt.Rectangle((0, 0), 1, 1, color=UNMET, alpha=0.30, linewidth=0)
    fig.legend(
        handles1 + handles2 + [unmet_patch],
        labels1 + labels2 + ["Hour not fully covered"],
        loc="upper center",
        ncol=3,
        bbox_to_anchor=(0.5, 1.06),
    )
    ax1.set_title(
        f"Design: solar {s:.2f}, wind {w:.2f}, battery {b:.1f} h  |  "
        f"hours covered {hours_covered:.0%} over three weeks (target {F3_COVERAGE:.0%})",
        fontsize=9,
        loc="left",
    )
    fig.tight_layout()
    _style.save(fig, PAGE, "f3_dispatch_week.svg")


def figure_lcoe_vs_coverage(pixels: dict[str, tuple[np.ndarray, np.ndarray]]) -> None:
    """F4: LCOE of the optimum against the coverage target, for each pixel."""
    lcoe = {name: [] for name in pixels}
    for name, (solar, wind) in pixels.items():
        for cov in F4_COVERAGES:
            opt = _optimum(solar, wind, float(cov))
            lcoe[name].append(np.nan if opt is None else opt.lcoe)
    ref_name, ref_cov = F4_REFERENCE
    ref = lcoe[ref_name][int(np.flatnonzero(np.isclose(F4_COVERAGES, ref_cov))[0])]

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    for name in pixels:
        colour, style, marker = F4_LINES[name]
        index = 100.0 * np.asarray(lcoe[name]) / ref
        ax.plot(
            F4_COVERAGES,
            index,
            color=colour,
            marker=marker,
            markersize=4,
            linestyle=style,
            linewidth=1.5,
            label=name,
        )
    ax.set_yscale("log")
    ticks = [100, 200, 500, 1000, 2000]
    ax.set_yticks(ticks)
    ax.set_yticklabels([str(t) for t in ticks])
    ax.yaxis.set_minor_formatter(plt.NullFormatter())
    ax.set_ylim(80, 2000)
    ax.set_xlabel("Coverage target (fraction of hours with the demand fully met)")
    ax.set_ylabel(f"LCOE index\n({ref_name.lower()} pixel at coverage {ref_cov:.2f} = 100)")
    ax.grid(True, which="both", axis="y")
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5))
    fig.tight_layout()
    _style.save(fig, PAGE, "f4_lcoe_vs_coverage.svg")


def main() -> None:
    _style.apply()
    pixels = _pixels(_fixtures())
    figure_dispatch(*pixels["Sunny"])
    figure_lcoe_vs_coverage(pixels)


if __name__ == "__main__":
    main()
