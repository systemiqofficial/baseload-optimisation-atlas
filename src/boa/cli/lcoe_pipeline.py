"""
Cost data to promoted LCOE file in one command: the `boa-lcoe` console script.

Runs the existing commands in process, in order, passing on only the options given here, so
every default stays the command's own:

    1. boa-data-prepare   the cost set: --input-file and --scenario, else the pinned cost data
    2. boa-cds-prepare    the weather year's stores, from the re-published copy if the raw data
                          is missing, so no CDS account is needed
    3. boa-run --promote-lcoe, once per --coverage (once at boa-run's default without one)

Every step reuses what is already in place, so a rerun after a failure resumes. The command
stops at the first failing step with that step's exit code. On success the last two stdout
lines are `BOA_RUN=<run>` and `BOA_RUN_DIR=<path>`: the run name, as the steel simulation's
--boa-run takes it, and the run's folder of promoted LCOE files under <root>/lcoe-only/.

--dry-run prints every step's command, skips the two preparation steps and passes --dry-run to
boa-run, so the arguments can be checked against the data on disk without any compute.

Examples:
    boa-lcoe --coverage 0.85 0.95
    boa-lcoe --input-file costs.xlsx --scenario mycase --coverage 0.85
    boa-lcoe --run smoke --coverage 0.85 --start-year 2025 --end-year 2026 --dry-run
"""

import argparse
import shlex
import sys
from collections.abc import Callable

from boa.cli import data_prepare, reconfigure_streams_utf8, run_cds, run_simulation
from boa.config.paths import PathConfig
from boa.config.physical_parameters import ERA5_DATA_YEAR

PREPARATION_STEPS = ("boa-data-prepare", "boa-cds-prepare")

# A command's name, its entry function and the argv it receives.
Step = tuple[str, Callable[[list[str]], int], list[str]]


def build_parser() -> argparse.ArgumentParser:
    """
    The options `boa-lcoe` routes to the three commands.

    Returns:
        A parser whose options all default to None (``--dry-run`` to False), so an option left
        out reaches no command and each command applies its own default.
    """
    parser = argparse.ArgumentParser(
        prog="boa-lcoe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input-file", help="Cost workbook for a custom scenario (boa-data-prepare --input-file).")
    parser.add_argument("--scenario", help="Cost-set name (boa-data-prepare --scenario, boa-run --cost-input).")
    parser.add_argument(
        "--weather-year",
        type=int,
        help=f"Weather year (boa-cds-prepare --weather_year, boa-run --weather-input cds-<year>; "
        f"default: {ERA5_DATA_YEAR}).",
    )
    parser.add_argument("--run", help="Run label (boa-run --run).")
    parser.add_argument(
        "--coverage", type=float, nargs="+", help="Coverage fractions, one boa-run each (boa-run --coverage)."
    )
    parser.add_argument("--start-year", type=int, help="boa-run --start-year.")
    parser.add_argument("--end-year", type=int, help="boa-run --end-year.")
    parser.add_argument("--frequency", type=int, help="boa-run --frequency.")
    parser.add_argument("--load-density", type=float, help="boa-run --load-density.")
    parser.add_argument("--workers", help="boa-run --workers.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every step's command, skip both preparation steps and pass --dry-run to boa-run.",
    )
    return parser


def _given(options: list[tuple[str, object]]) -> list[str]:
    """``flag value`` for every option that was given."""
    return [token for flag, value in options if value is not None for token in (flag, str(value))]


def plan_steps(args: argparse.Namespace) -> list[Step]:
    """
    The steps in order, each with the argv it receives.

    Args:
        args: Parsed `boa-lcoe` options.

    Returns:
        boa-data-prepare, boa-cds-prepare, then one boa-run per coverage.

    Notes:
        The weather year defaults to the constant boa-cds-prepare defaults to, since boa-run
        needs the input set it prepares. The input set is the geometry-only one.
    """
    weather_year = ERA5_DATA_YEAR if args.weather_year is None else args.weather_year
    steps: list[Step] = [
        (
            "boa-data-prepare",
            data_prepare.main,
            _given([("--input-file", args.input_file), ("--scenario", args.scenario)]),
        ),
        ("boa-cds-prepare", run_cds.main_prepare, ["--weather_year", str(weather_year), "--use-republished"]),
    ]
    for coverage in args.coverage or [None]:
        run_argv = [
            "--promote-lcoe",
            "--weather-input",
            run_cds.default_input_set(weather_year, []),
            *_given(
                [
                    ("--cost-input", args.scenario),
                    ("--run", args.run),
                    ("--coverage", coverage),
                    ("--start-year", args.start_year),
                    ("--end-year", args.end_year),
                    ("--frequency", args.frequency),
                    ("--load-density", args.load_density),
                    ("--workers", args.workers),
                ]
            ),
        ]
        if args.dry_run:
            run_argv.append("--dry-run")
        steps.append(("boa-run", run_simulation.main_run, run_argv))
    return steps


def run_name(args: argparse.Namespace) -> str:
    """
    The run folder name boa-run resolves for these options.

    Args:
        args: Parsed `boa-lcoe` options.

    Returns:
        ``<run>_<hash>``, from boa-run's own defaults and naming.
    """
    selection = argparse.Namespace(run=args.run, cost_input=args.scenario, weather_input=None)
    run_simulation.resolve_data_sets(selection)
    return run_simulation.resolve_run_id(selection)


def main(argv: list[str] | None = None) -> int:
    """
    Console entry for `boa-lcoe`.

    Args:
        argv: Command-line arguments, ``sys.argv[1:]`` when None.

    Returns:
        0 on success, else the exit code of the first step that failed.
    """
    args = build_parser().parse_args(argv)
    reconfigure_streams_utf8()
    for name, step, step_argv in plan_steps(args):
        command = shlex.join([name, *step_argv])
        if args.dry_run and name in PREPARATION_STEPS:
            print(f"boa-lcoe: skipped (dry run): {command}", flush=True)
            continue
        print(f"boa-lcoe: {command}", flush=True)
        code = step(step_argv)
        if code:
            print(f"boa-lcoe: {name} failed with exit code {code}; stopping.", file=sys.stderr, flush=True)
            return code
    run = run_name(args)
    run_dir = PathConfig.from_auto_detect(run=run).lcoe_promotion_dir
    # Last on stdout, after everything the steps logged there, for a caller to parse.
    print(f"BOA_RUN={run}")
    print(f"BOA_RUN_DIR={run_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
