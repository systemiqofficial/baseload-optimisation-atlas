"""
The capacity potential of a pixel: how much baseload its land can supply at the minimum LCOE.

The search finds the cheapest design as dimensionless overscale factors per MW of baseload:
`s` MW of solar and `w` MW of wind for each MW of demand. LCOE is baseload-invariant, so the
same design scaled to any baseload `P` has the same LCOE, and needs `P*s` MW of solar and `P*w`
MW of wind. The capacity ceiling limits each technology separately, and solar and wind may
share the same land, so the largest baseload at that LCOE is

    max_baseload_mw = min(solar_ceiling_mw / s, wind_ceiling_mw / w)

The technology that gives the minimum is the binding one. A technology the design does not use
(factor 0) cannot bind. The battery has no land limit and scales with `P`.

This is a lower bound on what the land can supply at a higher cost, because a design with a
different mix could use the land of the non-binding technology. It does not change the LCOE,
and it does not depend on `--load-density`.
"""

import numpy as np
from numpy.typing import ArrayLike

from boa.config.constants import HOURS_IN_YEAR

# Values of the `ceiling_binding` output variable. 0 is also what a sea pixel or a pixel with
# no design gets, as for `status`.
BINDING_NONE = 0
BINDING_SOLAR = 1
BINDING_WIND = 2
BINDING_CODES = {BINDING_NONE: "no design", BINDING_SOLAR: "solar", BINDING_WIND: "wind"}


def max_baseload(
    solar_factor: ArrayLike,
    wind_factor: ArrayLike,
    solar_ceiling_mw: ArrayLike,
    wind_ceiling_mw: ArrayLike,
) -> tuple[np.ndarray, np.ndarray]:
    """
    `(max_baseload_mw, ceiling_binding)` per pixel, for the designs given as overscale factors.

    A pixel whose design is NaN (no optimum) gets NaN and `BINDING_NONE`. A ceiling of 0 for a
    technology the design uses gives 0: the land cannot hold that design at all. On a tie, solar
    is reported as binding.
    """
    s = np.asarray(solar_factor, dtype=np.float64)
    w = np.asarray(wind_factor, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        by_solar = np.where(s > 0, np.asarray(solar_ceiling_mw, dtype=np.float64) / s, np.inf)
        by_wind = np.where(w > 0, np.asarray(wind_ceiling_mw, dtype=np.float64) / w, np.inf)
    p_max = np.minimum(by_solar, by_wind)
    binding = np.where(by_solar <= by_wind, BINDING_SOLAR, BINDING_WIND).astype(np.int8)

    # No design, a design with neither technology, or a ceiling missing for a technology in use.
    undefined = np.isnan(s) | np.isnan(w) | ~np.isfinite(p_max)
    p_max = np.where(undefined, np.nan, p_max)
    binding = np.where(undefined, BINDING_NONE, binding).astype(np.int8)
    return p_max, binding


def max_annual_energy_twh(max_baseload_mw: ArrayLike, served_fraction: ArrayLike) -> np.ndarray:
    """Energy the potential delivers in a year of `HOURS_IN_YEAR` hours, in TWh."""
    return np.asarray(max_baseload_mw) * HOURS_IN_YEAR * np.asarray(served_fraction) / 1e6
