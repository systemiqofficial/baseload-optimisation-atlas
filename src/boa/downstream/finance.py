"""Annuity arithmetic for the downstream steps."""

import numpy as np


def crf(wacc: np.ndarray | float, years: int) -> np.ndarray | float:
    """
    Capital recovery factor: the share of an up-front cost paid each year over ``years`` at
    discount rate ``wacc``, with payments at year ends.

    This is ``1 / sum(DF[1..years])``, the annuity that BOA's own LCOE uses (``d0`` in
    ``boa.model.cost_calculations.lcoe_coefficients``), so a plant priced with it carries the same
    capital charge as the renewable plant that powers it. A zero rate gives ``1 / years``.
    """
    if years <= 0:
        raise ValueError(f"years must be positive, got {years}.")
    wacc = np.asarray(wacc, dtype=float)
    if np.any(wacc < 0):
        raise ValueError("wacc must not be negative.")
    safe = np.where(wacc == 0, 1.0, wacc)  # avoid 0/0; the zero-rate branch is chosen below
    result = np.where(wacc == 0, 1.0 / years, safe / (1.0 - (1.0 + safe) ** -years))
    return float(result) if result.ndim == 0 else result
