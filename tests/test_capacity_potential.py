"""The capacity potential: the largest baseload a pixel's land supplies at the minimum LCOE."""

import numpy as np
import pytest

from boa.model.capacity_potential import (
    BINDING_NONE,
    BINDING_SOLAR,
    BINDING_WIND,
    max_annual_energy_twh,
    max_baseload,
)


def _one(solar, wind, solar_cap, wind_cap):
    p, b = max_baseload(np.array([solar]), np.array([wind]), np.array([solar_cap]), np.array([wind_cap]))
    return float(p[0]), int(b[0])


def test_the_tighter_ceiling_sets_the_potential():
    # 2 MW solar and 1 MW wind per MW of baseload; 1000 MW solar and 800 MW wind of land.
    # Solar allows 500 MW of baseload, wind 800 MW, so solar binds at 500 MW.
    assert _one(2.0, 1.0, 1000.0, 800.0) == (pytest.approx(500.0), BINDING_SOLAR)
    assert _one(2.0, 1.0, 2000.0, 800.0) == (pytest.approx(800.0), BINDING_WIND)


def test_a_technology_the_design_does_not_use_cannot_bind():
    """A wind-only design is not limited by the solar ceiling, even when that ceiling is 0."""
    assert _one(0.0, 1.5, 0.0, 300.0) == (pytest.approx(200.0), BINDING_WIND)


def test_a_zero_ceiling_for_a_technology_in_use_gives_zero_potential():
    assert _one(1.0, 1.0, 0.0, 500.0) == (0.0, BINDING_SOLAR)


def test_no_design_gives_nan_and_no_binding():
    p, b = _one(np.nan, np.nan, 100.0, 100.0)
    assert np.isnan(p) and b == BINDING_NONE


def test_a_missing_ceiling_for_a_technology_in_use_gives_nan():
    p, b = _one(1.0, 1.0, np.nan, 100.0)
    assert np.isnan(p) and b == BINDING_NONE


def test_a_tie_reports_solar():
    assert _one(1.0, 1.0, 100.0, 100.0) == (pytest.approx(100.0), BINDING_SOLAR)


def test_works_elementwise_and_returns_int8_codes():
    p, b = max_baseload(np.array([2.0, 0.0]), np.array([1.0, 1.0]), np.array([1000.0, 5.0]), np.array([800.0, 50.0]))
    np.testing.assert_allclose(p, [500.0, 50.0])
    assert b.dtype == np.int8
    assert b.tolist() == [BINDING_SOLAR, BINDING_WIND]


def test_annual_energy_counts_only_the_served_share():
    # 1000 MW over 8760 h is 8.76 TWh; 90 % served gives 7.884 TWh.
    assert max_annual_energy_twh(1000.0, 0.9) == pytest.approx(7.884)
