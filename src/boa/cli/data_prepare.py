"""
BOA input-data preparation: the `boa-data-prepare` console script.

Geo side: the pinned core data package (Natural Earth shapefiles and the ERA5 land-sea
mask) is downloaded from steelo-data into ``<root>/data/``, and the per-pixel iso3 grid is
built locally from the 1:50m shapefile (``boa.geo.iso3_grid_builder``).

Cost side: a scenario is a whole cost workbook. By default it is the pinned boa-cost-data
package from steelo-data, kept unchanged with its JSON in ``<root>/data/boa-cost-data/`` and
downloaded again only when the pin changes; ``--input-file`` takes a hand-edited workbook instead. Its sheet
and column names are the contract (``boa.inputs.costs.COST_WORKBOOK_COLUMNS``): the workbook
is checked against them, smoke-tested with BOA's cost loader and copied unchanged to
``<root>/costs/<scenario>/boa_cost_data.xlsx``, which doubles as the provenance record of the
cost data a run used. ``boa-run --cost-input <scenario>`` consumes it.

Examples:
    boa-data-prepare                                                  # pinned cost data -> costs/default/
    boa-data-prepare --input-file wb.xlsx --scenario cheap_renewables
    boa-data-prepare --input-file wb.xlsx --scenario cheap_renewables --year_start 2025 --year_end 2050 --year_step 5
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
    track,
)

from boa.cli import reconfigure_streams_utf8
from boa.config.data_packages import (
    CORE_DATA_INSTALLED,
    CORE_DATA_SHA256,
    CORE_DATA_URL,
    CORE_DATA_VERSION,
    COST_DATA_FOLDER,
    COST_DATA_INSTALLED,
    COST_DATA_SHA256,
    COST_DATA_URL,
    COST_DATA_VERSION,
    COST_DATA_WORKBOOK,
)
from boa.config.paths import DEFAULT_SET, PathConfig
from boa.fetch import fetch_verified_zip
from boa.geo.iso3_grid_builder import BUILD_STAGE_COUNT, build_iso3_grid_from_shapefile, iso3_grid_is_current
from boa.inputs.costs import (
    COST_WORKBOOK_COLUMNS,
    process_global_baseload_simulation_costs,
)

console = Console(legacy_windows=False)


def _installed_sha256(marker: Path) -> str | None:
    """The sha256 of the zip an install marker records, or None when there is no readable marker."""
    try:
        return json.loads(marker.read_text())["sha256"]
    except (OSError, ValueError, KeyError):
        return None


def _write_install_marker(marker: Path, version: str, url: str, sha256: str) -> None:
    installed = {
        "version": version,
        "url": url,
        "sha256": sha256,
        "installed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    marker.write_text(json.dumps(installed, indent=2) + "\n")


def _install_core_data(data_dir: Path) -> None:
    """Download the pinned core data package into ``data_dir`` unless that exact zip is already installed."""
    marker = data_dir / CORE_DATA_INSTALLED
    # Compared by sha256, not version, so a package re-published under the same version is fetched again.
    installed = _installed_sha256(marker)
    if installed == CORE_DATA_SHA256:
        return
    reason = "none installed" if installed is None else "another zip installed"
    console.print(f"Fetching core data v{CORE_DATA_VERSION} ({reason}) [dim]{CORE_DATA_URL}[/dim]")
    # Removed first and written only after a complete extraction, so an interrupted one fetches again.
    marker.unlink(missing_ok=True)
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading core data", total=None)
        fetch_verified_zip(
            CORE_DATA_URL,
            CORE_DATA_SHA256,
            data_dir,
            on_progress=lambda done, total: progress.update(task, completed=done, total=total),
        )
    _write_install_marker(marker, CORE_DATA_VERSION, CORE_DATA_URL, CORE_DATA_SHA256)
    console.print(f"Installed core data v{CORE_DATA_VERSION} into [dim]{data_dir}[/dim]")


def _prepare_geo_data(data_dir: Path, iso3_grid_path: Path, subunits_shapefile_path: Path) -> None:
    """Ensure the static geo inputs exist and build the per-pixel iso3 grid from them."""
    _install_core_data(data_dir)
    if not iso3_grid_is_current(iso3_grid_path, subunits_shapefile_path):
        if iso3_grid_path.exists():
            console.print("iso3 grid is stale (built from a different NE 1:50m shapefile); rebuilding.")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Building the iso3 grid...", total=BUILD_STAGE_COUNT)

            def on_stage(description: str) -> None:
                progress.update(task, description=f"Building the iso3 grid: {description}", advance=1)

            # force=True: a stale grid is only replaced once the new one is written.
            build_iso3_grid_from_shapefile(
                iso3_grid_path, shapefile_path=subunits_shapefile_path, force=True, on_stage=on_stage
            )
            progress.update(task, description="Built the iso3 grid", completed=BUILD_STAGE_COUNT)
    console.print("[green]✓ Geo data ready (NE shapefiles, land-sea mask, iso3 grid).[/green]")


def _validate_workbook(source: Path) -> list[int]:
    """Check the workbook has every sheet and column BOA reads; return the CAPEX sheet's years."""
    available = set(pd.ExcelFile(source).sheet_names)
    problems = [f"missing sheet '{sheet}'" for sheet in COST_WORKBOOK_COLUMNS if sheet not in available]
    headers = {
        sheet: list(pd.read_excel(source, sheet_name=sheet, nrows=0).columns)
        for sheet in COST_WORKBOOK_COLUMNS
        if sheet in available
    }
    for sheet, header in headers.items():
        missing = [column for column in COST_WORKBOOK_COLUMNS[sheet] if column not in header]
        if missing:
            problems.append(f"sheet '{sheet}' is missing column(s) {missing}")
    years = sorted(int(c) for c in headers.get("RES CAPEX projections", []) if isinstance(c, (int, np.integer)))
    if "RES CAPEX projections" in headers and not years:
        problems.append("sheet 'RES CAPEX projections' has no year columns")
    if problems:
        raise ValueError(f"{source.name} does not match the cost workbook layout: " + "; ".join(problems))
    return years


def _smoke_test(workbook: Path, year: int) -> None:
    """Build one year's costs in a throwaway folder, so bad cost data fails before the workbook is copied."""
    with tempfile.TemporaryDirectory() as tmp:
        process_global_baseload_simulation_costs(year, workbook, Path(tmp))


def _cache_years(available: list[int], args: argparse.Namespace) -> range:
    """All years available in the RES CAPEX projections sheet, narrowed by the --year_* flags."""
    start = args.year_start if args.year_start is not None else available[0]
    end = args.year_end if args.year_end is not None else available[-1]
    step = args.year_step if args.year_step is not None else 1
    return range(int(start), int(end) + 1, step)


def _build_cost_cache(input_data_path: Path, cost_cache_dir: Path, years: range) -> None:
    """Pre-build the per-year cost cache the model would otherwise build on first run."""
    for year in track(years, description="Building cost cache...", console=console):
        process_global_baseload_simulation_costs(year, input_data_path, cost_cache_dir)
    console.print(
        f"[green]✓ Cost cache ready for {len(years)} year(s) "
        f"{years.start}-{years.stop - 1} (step {years.step}) in {cost_cache_dir}[/green]"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_cost_data(package_dir: Path) -> None:
    """Download the pinned cost data package into ``package_dir`` unless that exact zip is already installed."""
    # Compared by sha256, not version, so a package re-published under the same version is fetched again.
    if _installed_sha256(package_dir / COST_DATA_INSTALLED) == COST_DATA_SHA256:
        return
    console.print(f"Fetching cost data v{COST_DATA_VERSION} [dim]{COST_DATA_URL}[/dim]")
    # Unpack beside the installed package and swap it in, so a failed download leaves it intact.
    staged = package_dir.with_name(package_dir.name + ".staged")
    shutil.rmtree(staged, ignore_errors=True)
    try:
        fetch_verified_zip(COST_DATA_URL, COST_DATA_SHA256, staged)
        _write_install_marker(staged / COST_DATA_INSTALLED, COST_DATA_VERSION, COST_DATA_URL, COST_DATA_SHA256)
        shutil.rmtree(package_dir, ignore_errors=True)
        staged.rename(package_dir)
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    console.print(f"Installed cost data v{COST_DATA_VERSION} into [dim]{package_dir}[/dim]")


def _prepare(args: argparse.Namespace) -> None:
    """Prepare from --input-file, else from the pinned cost data package installed under data/."""
    if args.input_file is not None:
        if not args.input_file.exists():
            raise FileNotFoundError(f"Input workbook not found: {args.input_file}")
        _prepare_from(args, args.input_file, {"source_workbook": str(args.input_file.resolve())})
        return
    package_dir = PathConfig.from_auto_detect(cost_set=args.scenario).data_dir / COST_DATA_FOLDER
    _install_cost_data(package_dir)
    origin = {
        "source_workbook": str(package_dir / COST_DATA_WORKBOOK),
        "source_package": {"version": COST_DATA_VERSION, "url": COST_DATA_URL, "sha256": COST_DATA_SHA256},
    }
    _prepare_from(args, package_dir / COST_DATA_WORKBOOK, origin)


def _prepare_from(args: argparse.Namespace, source: Path, origin: dict) -> None:
    """Install the static geo data, then copy the checked cost workbook into costs/<scenario>/boa_cost_data.xlsx."""
    console.print(f"Checking the cost workbook [cyan]{source}[/cyan]")
    years = _validate_workbook(source)
    _smoke_test(source, years[0])

    paths = PathConfig.from_auto_detect(cost_set=args.scenario)
    _prepare_geo_data(paths.data_dir, paths.iso3_grid_path, paths.subunits_50m_shapefile_path)
    target = paths.input_data_path
    source_sha256 = _sha256(source)
    if target.exists() and _sha256(target) == source_sha256:
        console.print(f"[green]✓ Costs scenario '{args.scenario}' is already up to date.[/green]")
        _build_cost_cache(target, paths.cost_cache_dir, _cache_years(years, args))
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    replaced = target.exists()
    # Copy then rename, so an interrupted copy never leaves a half-written workbook behind.
    staged = target.with_suffix(".staged.xlsx")
    try:
        shutil.copyfile(source, staged)
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)

    if paths.cost_cache_dir.exists():
        shutil.rmtree(paths.cost_cache_dir)
        console.print("Removed the scenario's stale cost cache.")

    provenance = {
        "scenario": args.scenario,
        "prepared_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **origin,
        "source_sha256": source_sha256,
    }
    (paths.costs_dir / "source.json").write_text(json.dumps(provenance, indent=2) + "\n")

    verb = "Updated" if replaced else "Created"
    console.print(f"[green]✓ {verb} costs scenario '{args.scenario}'[/green] [dim]({target})[/dim]")
    _build_cost_cache(target, paths.cost_cache_dir, _cache_years(years, args))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="boa-data-prepare",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help=(
            "Cost workbook for a custom scenario, copied unchanged into costs/<scenario>/ "
            f"(default: the pinned boa-cost-data v{COST_DATA_VERSION} package)."
        ),
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SET,
        help=f"Cost-set name under <boa root>/costs/ (default: {DEFAULT_SET}).",
    )
    parser.add_argument("--year_start", type=int, help="First cache year (default: earliest in the sheet).")
    parser.add_argument("--year_end", type=int, help="Last cache year (default: latest in the sheet).")
    parser.add_argument("--year_step", type=int, help="Step between cache years (default: 1).")
    args = parser.parse_args(argv)

    reconfigure_streams_utf8()
    started = time.monotonic()
    try:
        _prepare(args)
    except (OSError, ValueError, KeyError) as e:
        console.print(f"[red]✗ boa-data-prepare failed: {e}[/red]")
        return 1
    console.print(f"Run a full BOA simulation with it via [cyan]boa-run --cost-input {args.scenario}[/cyan]")
    console.print(f"[green]boa-data-prepare completed in {time.monotonic() - started:.1f} s[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
