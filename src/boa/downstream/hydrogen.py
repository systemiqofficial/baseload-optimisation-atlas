"""
Levelised cost of hydrogen (LCOH) from the per-pixel LCOE: arithmetic and parameters, no I/O.

The electrolyser is sized at the baseload, 1 kW of electrolyser for each kW of load. It takes the
electricity that the BOA design delivers, so its full-load hours are ``8760 * served_fraction``,
the same delivered energy that the LCOE is divided by. For one pixel and investment year ``y``,
in USD per kg of hydrogen:

    e        = 33.33 / eta(y)                      kWh per kg (LHV)
    H        = 8760 * sf / e                        kg per kW of electrolyser per year
    r        = wacc + premium(y)                    electrolyser WACC (real)
    LCOH     = LCOE * e / 1000                      electricity
             + CAPEX(y) * CRF(r, N) / H             capital
             + f_OM * CAPEX(y) / H                  fixed O&M
             + CRF(r, N) / H * sum_k s * CAPEX(y + t_k) * (1 + r)^-t_k     stack replacement
    t_k      = k * L_stack / (8760 * sf), for every t_k < N

``CRF`` is the annuity of BOA's own LCOE (``boa.downstream.finance.crf``). Every parameter and
its source is in ``electrolysis.csv``; values between the listed years are linear, values
outside them are held. All pixels use the same electrolyser. The table holds the lower and upper
CAPEX of the source range; the default ``mid`` bound is their mean, ``lower`` and ``upper`` are
for sensitivity runs. A parameter with bound ``all`` has one value for every bound.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from boa.config.constants import HOURS_IN_YEAR
from boa.downstream.finance import crf

PARAMETERS_PATH = Path(__file__).with_name("electrolysis.csv")
KWH_PER_KG_H2_LHV = 120.0 / 3.6  # 120 MJ/kg
KWH_PER_MWH = 1000.0
SCENARIOS = ("CPS", "STEPS", "NZE")
TABLE_BOUNDS = ("lower", "upper")
CAPEX_BOUNDS = ("mid", *TABLE_BOUNDS)
ASSUMPTION = "assumption"
PARAMETERS = (
    "capex",
    "efficiency_lhv",
    "fom_fraction",
    "stack_life_hours",
    "stack_share",
    "plant_life_years",
    "wacc_premium",
)


@dataclass(frozen=True)
class Row:
    parameter: str
    bound: str
    scenario: str
    year: int
    value: float
    unit: str
    source: str
    note: str


class ParameterTable:
    """The rows of ``electrolysis.csv``, with lookup by parameter, scenario, year and CAPEX bound."""

    def __init__(self, rows: list[Row]):
        self.rows = rows
        unknown = sorted({r.parameter for r in rows} - set(PARAMETERS))
        if unknown:
            raise ValueError(f"unknown parameters {unknown}")
        bad = sorted({r.bound for r in rows} - {*TABLE_BOUNDS, "all"})
        if bad:
            raise ValueError(f"unknown bounds {bad}")
        for parameter in PARAMETERS:
            for bound in TABLE_BOUNDS:
                for scenario in SCENARIOS:
                    if not self._select(parameter, bound, scenario):
                        raise ValueError(f"no {parameter} for bound {bound}, scenario {scenario}")

    @classmethod
    def read(cls, path: Path = PARAMETERS_PATH) -> ParameterTable:
        with path.open(newline="", encoding="utf-8") as f:
            rows = [
                Row(
                    parameter=r["parameter"],
                    bound=r["bound"],
                    scenario=r["scenario"],
                    year=int(r["year"]),
                    value=float(r["value"]),
                    unit=r["unit"],
                    source=r["source"],
                    note=r["note"],
                )
                for r in csv.DictReader(f)
            ]
        return cls(rows)

    def _select(self, parameter: str, bound: str, scenario: str) -> list[Row]:
        rows = [
            r
            for r in self.rows
            if r.parameter == parameter and r.bound in (bound, "all") and r.scenario in (scenario, "all")
        ]
        return sorted(rows, key=lambda r: r.year)

    def rows_for(self, parameter: str, scenario: str, bound: str = "mid") -> list[Row]:
        """The rows behind a value; for ``mid``, the rows of both table bounds."""
        if bound not in CAPEX_BOUNDS:
            raise ValueError(f"bound must be one of {CAPEX_BOUNDS}, got {bound!r}")
        rows: list[Row] = []
        for b in TABLE_BOUNDS if bound == "mid" else (bound,):
            selected = self._select(parameter, b, scenario)
            if len({r.year for r in selected}) != len(selected):
                raise ValueError(f"{parameter}, {b}, {scenario}: more than one row for a year")
            rows += [r for r in selected if r not in rows]
        return rows

    def value(self, parameter: str, scenario: str, year: float | np.ndarray, bound: str = "mid") -> float | np.ndarray:
        """Linear between the listed years, held before the first and after the last; ``mid`` is the
        mean of the lower and the upper value."""
        result: np.ndarray
        if bound == "mid":
            result = np.mean([self.value(parameter, scenario, year, b) for b in TABLE_BOUNDS], axis=0)
        else:
            rows = self.rows_for(parameter, scenario, bound)
            result = np.asarray(np.interp(year, [r.year for r in rows], [r.value for r in rows]))
        return float(result) if np.ndim(result) == 0 else result


@dataclass(frozen=True)
class Electrolyser:
    """The parameters of one scenario and CAPEX bound, for one investment year."""

    year: int
    capex: float  # USD/kW, installed
    efficiency_lhv: float
    fom_fraction: float
    stack_life_hours: float
    stack_share: float
    plant_life_years: int
    wacc_premium: float
    capex_at: Callable[[np.ndarray], np.ndarray]  # installed CAPEX in a later (fractional) year

    @classmethod
    def from_table(cls, table: ParameterTable, scenario: str, year: int, capex_bound: str = "mid") -> Electrolyser:
        def v(parameter: str) -> float:
            return float(table.value(parameter, scenario, year, capex_bound))

        def capex_at(when: np.ndarray) -> np.ndarray:
            return np.asarray(table.value("capex", scenario, when, capex_bound), dtype=float)

        return cls(
            year=year,
            capex=v("capex"),
            efficiency_lhv=v("efficiency_lhv"),
            fom_fraction=v("fom_fraction"),
            stack_life_hours=v("stack_life_hours"),
            stack_share=v("stack_share"),
            plant_life_years=round(v("plant_life_years")),
            wacc_premium=v("wacc_premium"),
            capex_at=capex_at,
        )

    @property
    def kwh_per_kg(self) -> float:
        return KWH_PER_KG_H2_LHV / self.efficiency_lhv


@dataclass(frozen=True)
class Lcoh:
    """USD per kg of hydrogen (LHV), split by cost component; ``wacc`` is the electrolyser WACC used."""

    electricity: np.ndarray
    capital: np.ndarray
    fom: np.ndarray
    stack: np.ndarray
    wacc: np.ndarray

    @property
    def total(self) -> np.ndarray:
        return self.electricity + self.capital + self.fom + self.stack


def lcoh(lcoe: np.ndarray, served_fraction: np.ndarray, wacc: np.ndarray, p: Electrolyser) -> Lcoh:
    """
    LCOH of every pixel in the arrays, which broadcast against each other. ``lcoe`` in USD/MWh
    delivered, ``served_fraction`` in (0, 1], ``wacc`` the pixel's real cost of capital. A pixel with
    a non-finite input or a served fraction outside (0, 1] gives NaN.
    """
    lcoe, sf, wacc = np.broadcast_arrays(
        np.asarray(lcoe, dtype=float), np.asarray(served_fraction, dtype=float), np.asarray(wacc, dtype=float)
    )
    valid = np.isfinite(lcoe) & np.isfinite(sf) & np.isfinite(wacc) & (sf > 0) & (sf <= 1) & (wacc >= 0)
    sf = np.where(valid, sf, 1.0)
    r = np.where(valid, wacc, 0.0) + p.wacc_premium
    e = p.kwh_per_kg
    hours = HOURS_IN_YEAR * sf
    kg_per_kw = hours / e
    annuity = crf(r, p.plant_life_years)

    electricity = lcoe * e / KWH_PER_MWH
    capital = p.capex * annuity / kg_per_kw
    fom = p.fom_fraction * p.capex / kg_per_kw

    replacements = np.zeros_like(sf)
    interval = p.stack_life_hours / hours  # years between replacements
    k = 1
    while np.any(k * interval < p.plant_life_years):
        t = k * interval
        due = t < p.plant_life_years
        cost = p.stack_share * p.capex_at(p.year + np.where(due, t, 0.0)) * (1.0 + r) ** -t
        replacements += np.where(due, cost, 0.0)
        k += 1
    stack = replacements * annuity / kg_per_kw

    nan = np.full_like(sf, np.nan)
    return Lcoh(
        electricity=np.where(valid, electricity, nan),
        capital=np.where(valid, capital, nan),
        fom=np.where(valid, fom, nan),
        stack=np.where(valid, stack, nan),
        wacc=np.where(valid, r, nan),
    )
