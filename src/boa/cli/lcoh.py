#!/usr/bin/env python
"""
Levelised cost of hydrogen from a BOA run: the `boa-lcoh` console script (optional).

Prices hydrogen for every pixel and investment year of each scenario (weather year, load density,
coverage) of a run, from the run's per-year GLOBAL outputs. Writes one LCOH file per scenario,
plus a CSV of the parameters it used, to `<root>/downstream/<run>/`. The electrolyser parameters
and their sources are in `boa/downstream/electrolysis.csv`; the method is in
`boa.downstream.hydrogen`.

Examples:
    boa-lcoh --run wy2025-core-steps
    boa-lcoh --run wy2025-core-steps --scenario NZE --coverage 0.9
    boa-lcoh --run wy2025-core-steps --capex-bound upper
"""

import argparse
import logging
import sys

from boa.cli import reconfigure_streams_utf8
from boa.config.paths import PathConfig, default_root, resolve_run_dir

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    from boa.downstream.hydrogen import CAPEX_BOUNDS, SCENARIOS

    parser = argparse.ArgumentParser(
        prog="boa-lcoh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run", required=True, help="Run label, as passed to boa-run.")
    parser.add_argument(
        "--scenario", default="STEPS", choices=SCENARIOS, help="IEA WEO 2025 scenario of the electrolyser CAPEX."
    )
    parser.add_argument(
        "--capex-bound",
        default="mid",
        choices=CAPEX_BOUNDS,
        help="Point of the WEO CAPEX range: its mean (mid), its lower or its upper value. All pixels use it.",
    )
    parser.add_argument("--coverage", type=float, nargs="+", help="Only these coverage levels (default: all).")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    args = parser.parse_args(argv)

    reconfigure_streams_utf8()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    from boa.downstream.lcoh_file import build_lcoh
    from boa.model.lcoe_promotion import discover_scenarios

    try:
        run_dir = resolve_run_dir(default_root(), args.run)
        path_config = PathConfig.from_auto_detect(run=run_dir.name)
        scenarios = discover_scenarios(path_config)
        if args.coverage:
            scenarios = [s for s in scenarios if any(abs(s[2] - c) < 1e-9 for c in args.coverage)]
        if not scenarios:
            log.error(f"Run '{path_config.run}' has no GLOBAL outputs for the chosen coverage levels.")
            return 1
        for weather_year, load_density, coverage in scenarios:
            build_lcoh(path_config, weather_year, load_density, coverage, args.scenario, args.capex_bound)
    except (FileNotFoundError, ValueError) as e:
        log.error(str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
