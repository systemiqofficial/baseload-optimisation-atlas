"""
Shared figure style for the docs site.

Every figure script in `docs_figures/` imports this module, so that solar, wind, battery and
demand have the same colour in every figure.

The palette is Okabe-Ito, which is safe for the common types of colour blindness. Each figure
has a solid white background, so it is legible in the light and the dark site theme.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "docs" / "assets"

# Technology colours (Okabe-Ito). Use these in every figure.
SOLAR = "#E69F00"  # orange
WIND = "#0072B2"  # blue
BATTERY = "#009E73"  # bluish green
DEMAND = "#000000"  # black
UNMET = "#CC79A7"  # reddish purple: hours in which the demand is not fully met

# Neutral colours for lines that are not a technology (for example, example pixels).
NEUTRAL = ["#882255", "#999933", "#555555", "#999999"]

BACKGROUND = "#FFFFFF"


def apply() -> None:
    """Set the matplotlib defaults for the docs figures."""
    plt.rcParams.update(
        {
            "figure.facecolor": BACKGROUND,
            "axes.facecolor": BACKGROUND,
            "savefig.facecolor": BACKGROUND,
            "font.family": "sans-serif",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": "#DDDDDD",
            "grid.linewidth": 0.6,
            "legend.frameon": False,
            # Keep text as text (smaller files) and make the output byte-identical between runs.
            "svg.fonttype": "none",
            "svg.hashsalt": "boa-docs",
        }
    )


def save(fig: plt.Figure, page: str, name: str) -> Path:
    """Write `fig` to `docs/assets/<page>/<name>` without a timestamp, so reruns give the same file."""
    out_dir = ASSETS / page
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    fig.savefig(path, metadata={"Date": None}, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return path
