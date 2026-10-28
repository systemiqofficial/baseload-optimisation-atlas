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

--like FILE reruns a promoted LCOE file: its run, cost set, weather year, coverage, load density
and years fill every option not given. It stops before any step when the cost workbook here is
not the one the file was produced with, and warns when the file comes from another BOA version.

Examples:
    boa-lcoe --coverage 0.85 0.95
    boa-lcoe --input-file costs.xlsx --scenario mycase --coverage 0.85
    boa-lcoe --run smoke --coverage 0.85 --start-year 2025 --end-year 2026 --dry-run
    boa-lcoe --like ~/.boa/lcoe-only/default_49e8/optimal_lcoe_wy2024_01MWkm2_cov0p85_2025_2060.nc --dry-run
"""

import argparse
import hashlib
import shlex
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import xarray as xr

import boa
from boa.cli import data_prepare, reconfigure_streams_utf8, run_cds, run_simulation
from boa.config import run_manifest
from boa.config.data_packages import COST_DATA_FOLDER, COST_DATA_INSTALLED, COST_DATA_SHA256, COST_DATA_WORKBOOK
from boa.config.paths import DEFAULT_SET, PathConfig
from boa.config.physical_parameters import ERA5_DATA_YEAR

PREPARATION_STEPS = ("boa-data-prepare", "boa-cds-prepare")

# The promoted-file attributes a --like rerun reads (docs/promoted-lcoe-file.md).
LIKE_ATTRS = (
    "run",
    "input_set",
    "cost_set",
    "input_data_sha256",
    "boa_version",
    "era5_weather_year",
    "coverage_fraction",
    "load_density_mw_km2",
    "promoted_years",
)

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
        "--like", type=Path, help="Promoted LCOE file to rerun; its settings fill every option not given."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every step's command, skip both preparation steps and pass --dry-run to boa-run.",
    )
    return parser


def _given(options: list[tuple[str, object]]) -> list[str]:
    """``flag value`` for every option that was given."""
    return [token for flag, value in options if value is not None for token in (flag, str(value))]


def _weather_year(args: argparse.Namespace) -> int:
    """The weather year given, else the one boa-cds-prepare defaults to, since boa-run needs the set it prepares."""
    return ERA5_DATA_YEAR if args.weather_year is None else args.weather_year


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
    weather_year = _weather_year(args)
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


def require_own_cost_set(args: argparse.Namespace) -> None:
    """
    Stop when --input-file is given without a cost-set name of its own.

    Args:
        args: Parsed options, after any --like file has filled them.

    Raises:
        ValueError: When --scenario is missing or names the default cost set.

    Notes:
        Prepared as the default cost set, the workbook would replace the default cost data, and
        its runs would take the default runs' names.
    """
    if args.input_file is not None and args.scenario in (None, DEFAULT_SET):
        raise ValueError(
            f"--input-file needs a cost-set name of its own: add --scenario <name>"
            f"{' and a new --run <label>' if args.like is not None else ''}, so the workbook does not replace "
            f"the '{DEFAULT_SET}' cost set."
        )


def use_prepared_workbook(args: argparse.Namespace) -> None:
    """
    Hand a custom cost set's prepared workbook to boa-data-prepare when no --input-file is given.

    Args:
        args: Parsed options; ``input_file`` is set in place.

    Raises:
        ValueError: When the custom cost set is not prepared here.

    Notes:
        Without --input-file, boa-data-prepare installs the pinned cost data package whatever the
        cost set, which would replace the custom workbook. Given that workbook, it finds it up to date.
    """
    if args.input_file is not None or args.scenario in (None, DEFAULT_SET):
        return
    workbook = PathConfig.from_auto_detect(cost_set=args.scenario).input_data_path
    if not workbook.exists():
        raise ValueError(f"cost set '{args.scenario}' is not prepared here; pass its workbook as --input-file.")
    args.input_file = str(workbook)


def check_run_folder(args: argparse.Namespace) -> None:
    """
    Stop when boa-run would refuse to add to the run folder these options resolve to.

    Args:
        args: Parsed options, with the cost workbook resolved.

    Raises:
        ValueError: When the folder was made by another BOA version, for another cost set, on
            another input set (weather year), or, with --input-file, from another cost workbook.

    Notes:
        boa-run checks a folder's provenance itself, but only after both preparation steps, and
        then fails with a traceback.
    """
    run = run_name(args)
    manifest = run_manifest.load(PathConfig.from_auto_detect(run=run))
    if manifest is None:
        return
    made_by = manifest["provenance"]["boa_version"]
    if made_by != boa.__version__:
        raise ValueError(
            f"the run folder {run} was made by BOA {made_by}, and this is BOA {boa.__version__}; pass a new --run."
        )
    made_for, cost_set = manifest["provenance"]["cost_set"], args.scenario or DEFAULT_SET
    if made_for != cost_set:
        raise ValueError(
            f"the run folder {run} was made for the cost set '{made_for}', not '{cost_set}'; pass a new --run."
        )
    made_on, input_set = manifest["provenance"]["input_set"], run_cds.default_input_set(_weather_year(args), [])
    if made_on != input_set:
        raise ValueError(
            f"the run folder {run} was made on the input set '{made_on}', not '{input_set}'; pass a new --run."
        )
    if args.input_file is not None and manifest["provenance"]["input_data_sha256"] != _sha256(args.input_file):
        raise ValueError(
            f"the run folder {run} was made from another cost workbook than {args.input_file}; pass a new --run."
        )


def pinned_cost_workbook() -> Path | None:
    """
    The workbook boa-data-prepare installs as the default cost set: the pinned cost data package's.

    Returns:
        Its path when the package is installed here at the pinned sha256, else None.
    """
    package_dir = PathConfig.from_auto_detect().data_dir / COST_DATA_FOLDER
    if data_prepare._installed_sha256(package_dir / COST_DATA_INSTALLED) != COST_DATA_SHA256:
        return None
    return package_dir / COST_DATA_WORKBOOK


def check_cost_workbook(args: argparse.Namespace, expected_sha256: str) -> bool:
    """
    Stop when the cost workbook this rerun would use is not the one the --like file was produced with.

    Args:
        args: Options filled from the --like file.
        expected_sha256: The file's ``input_data_sha256``.

    Returns:
        False when there is no workbook to compare yet: the default cost set, whose workbook
        boa-data-prepare installs from the pinned cost data package, before that package is
        installed here. True when it matches.

    Raises:
        ValueError: On another workbook, or on a custom cost set that is not prepared here when
            no --input-file is given.
    """
    if args.input_file is not None:
        workbook = Path(args.input_file)
    elif args.scenario == DEFAULT_SET:
        # boa-data-prepare replaces whatever the default cost set holds with the pinned workbook.
        pinned = pinned_cost_workbook()
        if pinned is None:
            return False
        workbook = pinned
    else:
        workbook = PathConfig.from_auto_detect(cost_set=args.scenario).input_data_path
        if not workbook.exists():
            raise ValueError(
                f"cost set '{args.scenario}' is not prepared here; pass the workbook {args.like.name} "
                f"was produced with as --input-file."
            )
    actual = _sha256(workbook)
    if actual != expected_sha256:
        raise ValueError(
            f"{workbook} (sha256 {actual[:12]}) is not the cost workbook {args.like.name} was produced with "
            f"(sha256 {expected_sha256[:12]}); pass that workbook as --input-file"
            f"{' with a --scenario name of its own and a new --run' if args.scenario == DEFAULT_SET else ''}."
        )
    return True


def fill_from_promoted_file(args: argparse.Namespace) -> str | None:
    """
    Fill every option not given from the --like promoted file, so the steps rerun it.

    Args:
        args: Parsed options; those still None are filled in place, so an explicit flag wins.

    Returns:
        The file's cost workbook sha256 when it can only be checked once boa-data-prepare has
        installed the pinned cost data package, else None.

    Raises:
        ValueError: When the file cannot be rerun as it was: an input set boa-lcoe does not
            prepare, years boa-run cannot produce, or another cost workbook.

    Notes:
        The file is only read. A different BOA version, or a run label that resolves to another
        run folder here, is a warning, not a stop.
    """
    path = args.like
    with xr.open_dataset(path) as ds:
        attrs = dict(ds.attrs)
    missing = [name for name in LIKE_ATTRS if name not in attrs]
    if missing:
        raise ValueError(f"{path} is not a promoted LCOE file: it has no {', '.join(missing)} attribute.")

    weather_year = int(attrs["era5_weather_year"])
    input_set = run_cds.default_input_set(weather_year, [])
    if attrs["input_set"] != input_set:
        raise ValueError(
            f"{path.name} was built on the input set '{attrs['input_set']}', but boa-lcoe prepares only "
            f"'{input_set}' for weather year {weather_year}, with no availability layers."
        )
    # A single year comes back from the file as a scalar.
    years = sorted(int(year) for year in np.atleast_1d(attrs["promoted_years"]))
    frequency = years[1] - years[0] if len(years) > 1 else 1
    if run_simulation.get_simulation_years(years[0], years[-1], frequency) != years:
        raise ValueError(f"boa-run cannot produce the years of {path.name}, {years}, from a start, end and step.")

    run_from_file = args.run is None
    # The file names the run folder, <label>_<hash> (paths.make_run_dirname); --run takes the label.
    label = attrs["run"].rpartition("_")[0] or attrs["run"]
    from_file = {
        "scenario": attrs["cost_set"],
        "weather_year": weather_year,
        "run": label,
        "coverage": [float(attrs["coverage_fraction"])],
        "load_density": float(attrs["load_density_mw_km2"]),
        "start_year": years[0],
        "end_year": years[-1],
        "frequency": frequency if frequency != 1 else None,
    }
    for name, value in from_file.items():
        if getattr(args, name) is None:
            setattr(args, name, value)

    if attrs["boa_version"] != boa.__version__:
        _warn(
            f"{path.name} was produced by BOA {attrs['boa_version']}; this is BOA {boa.__version__}. Results "
            f"may differ if LCOE-changing code landed between the two versions, and if its run folder "
            f"{attrs['run']} is on this machine, the rerun needs a new --run."
        )
    if run_from_file and (resolved := run_name(args)) != attrs["run"]:
        _warn(
            f"{path.name} comes from the run folder {attrs['run']}, but this BOA resolves the label "
            f"'{args.run}' to {resolved}, since its search parameters or physical constants differ."
        )
    if not attrs["input_data_sha256"]:
        _warn(f"{path.name} records no cost workbook sha256, so the workbook is not checked.")
        return None
    if check_cost_workbook(args, attrs["input_data_sha256"]):
        return None
    if args.dry_run:
        _warn("the pinned cost data package is not installed yet, so a dry run cannot check the cost workbook.")
    return attrs["input_data_sha256"]


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _warn(message: str) -> None:
    print(f"boa-lcoe: warning: {message}", file=sys.stderr, flush=True)


def _stop(message: str, code: int = 1) -> int:
    print(f"boa-lcoe: {message}", file=sys.stderr, flush=True)
    return code


def main(argv: list[str] | None = None) -> int:
    """
    Console entry for `boa-lcoe`.

    Args:
        argv: Command-line arguments, ``sys.argv[1:]`` when None.

    Returns:
        0 on success, 1 when a --like file cannot be rerun, the cost workbook options do not name a
        cost set of its own, or boa-run would refuse the run folder, else the exit code of the first
        step that failed.
    """
    args = build_parser().parse_args(argv)
    reconfigure_streams_utf8()
    unchecked_sha256 = None
    try:
        if args.like is not None:
            unchecked_sha256 = fill_from_promoted_file(args)
        require_own_cost_set(args)
        use_prepared_workbook(args)
        check_run_folder(args)
    except (OSError, ValueError) as e:
        return _stop(str(e))
    for name, step, step_argv in plan_steps(args):
        command = shlex.join([name, *step_argv])
        if args.dry_run and name in PREPARATION_STEPS:
            print(f"boa-lcoe: skipped (dry run): {command}", flush=True)
            continue
        print(f"boa-lcoe: {command}", flush=True)
        code = step(step_argv)
        if code:
            return _stop(f"{name} failed with exit code {code}; stopping.", code)
        if name == "boa-data-prepare" and unchecked_sha256 is not None:
            try:
                check_cost_workbook(args, unchecked_sha256)
            except ValueError as e:
                return _stop(str(e))
    run = run_name(args)
    run_dir = PathConfig.from_auto_detect(run=run).lcoe_promotion_dir
    # Last on stdout, after everything the steps logged there, for a caller to parse.
    print(f"BOA_RUN={run}")
    print(f"BOA_RUN_DIR={run_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
