"""
`boa-lcoe` runs boa-data-prepare, boa-cds-prepare and boa-run in order, passing on only the options given.

The three commands are replaced by recorders, except in one test, where boa-run's own parser
and run naming are checked against a dry run on synthetic stores under `tmp_path`. The --like
tests read a small promoted file whose attributes come from BOA's own promotion code.
"""

import hashlib
import json
import logging
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr

import boa
from boa.cli import data_prepare, lcoe_pipeline, run_cds, run_simulation
from boa.config import run_manifest
from boa.config.data_packages import COST_DATA_FOLDER, COST_DATA_INSTALLED, COST_DATA_SHA256, COST_DATA_WORKBOOK
from boa.config.paths import PathConfig
from boa.config.physical_parameters import ERA5_DATA_YEAR, REGION_COORDS
from boa.model import lcoe_promotion
from boa.model.bisection import SearchParams
from boa.store_schema import max_cap_store_stem, profile_store_stem

HASH = run_manifest.non_scenario_params_hash(SearchParams())


def _prepare_cost_set(root, cost_set, workbook=b"a prepared cost workbook"):
    """Write `cost_set`'s prepared workbook under `root`, as boa-data-prepare would, and return its path."""
    path = PathConfig.from_root(root, cost_set=cost_set).input_data_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(workbook)
    return path


@pytest.fixture
def steps(tmp_path, monkeypatch):
    """
    Replaces the three commands with recorders that print to stdout, as BOA's logging does.

    `codes[name]` lists the exit codes that command returns on successive calls; 0 once used up.
    `effects[name]` runs on each call, standing in for what the command writes.
    """
    monkeypatch.setenv("BOA_DATA_ROOT", str(tmp_path))
    recorded = SimpleNamespace(log=[], codes={}, effects={})

    def recorder(name):
        def step(argv):
            recorded.log.append((name, list(argv)))
            recorded.effects.get(name, lambda: None)()
            print(f"{name} is logging to stdout")
            codes = recorded.codes.get(name, [])
            return codes.pop(0) if codes else 0

        return step

    monkeypatch.setattr(data_prepare, "main", recorder("data_prepare"))
    monkeypatch.setattr(run_cds, "main_prepare", recorder("cds_prepare"))
    monkeypatch.setattr(run_simulation, "main_run", recorder("run"))
    return recorded


def test_each_step_gets_the_options_given_in_order(steps):
    given = "--run smoke --start-year 2025 --end-year 2026 --frequency 1 --load-density 2.0 --workers fast"
    argv = f"--input-file costs.xlsx --scenario mycase --weather-year 2023 --coverage 0.85 0.95 {given}"
    assert lcoe_pipeline.main(argv.split()) == 0

    def run(coverage):
        return (
            "--promote-lcoe --weather-input cds-2023 --cost-input mycase --run smoke "
            f"--coverage {coverage} --start-year 2025 --end-year 2026 --frequency 1 --load-density 2.0 --workers fast"
        ).split()

    assert steps.log == [
        ("data_prepare", ["--input-file", "costs.xlsx", "--scenario", "mycase"]),
        ("cds_prepare", ["--weather_year", "2023", "--use-republished"]),
        ("run", run("0.85")),
        ("run", run("0.95")),
    ]


def test_without_options_each_command_keeps_its_own_defaults(steps):
    """One boa-run at its default coverage; the weather year is boa-cds-prepare's default."""
    assert lcoe_pipeline.main([]) == 0
    assert steps.log == [
        ("data_prepare", []),
        ("cds_prepare", ["--weather_year", str(ERA5_DATA_YEAR), "--use-republished"]),
        ("run", ["--promote-lcoe", "--weather-input", f"cds-{ERA5_DATA_YEAR}"]),
    ]


@pytest.mark.parametrize(
    ("failing", "ran"),
    [
        ("data_prepare", ["data_prepare"]),
        ("cds_prepare", ["data_prepare", "cds_prepare"]),
        ("run", ["data_prepare", "cds_prepare", "run"]),
    ],
)
def test_stops_at_the_first_failing_step_with_its_exit_code(steps, capsys, failing, ran):
    steps.codes[failing] = [3]

    assert lcoe_pipeline.main(["--coverage", "0.85", "0.95"]) == 3
    assert [name for name, _ in steps.log] == ran
    assert "BOA_RUN" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "label"),
    [
        ([], "default"),
        (["--scenario", "mycase"], "mycase"),
        (["--scenario", "mycase", "--run", "smoke"], "smoke"),
    ],
)
def test_the_last_two_stdout_lines_name_the_run_and_its_folder(steps, capsys, tmp_path, argv, label):
    _prepare_cost_set(tmp_path, "mycase")

    assert lcoe_pipeline.main(argv) == 0

    run = f"{label}_{HASH}"
    assert capsys.readouterr().out.splitlines()[-2:] == [
        f"BOA_RUN={run}",
        f"BOA_RUN_DIR={tmp_path / 'lcoe-only' / run}",
    ]


def test_dry_run_prints_every_step_and_runs_only_boa_run_with_dry_run(steps, capsys, tmp_path):
    workbook = _prepare_cost_set(tmp_path, "mycase")
    before = sorted(tmp_path.rglob("*"))

    assert lcoe_pipeline.main(["--scenario", "mycase", "--coverage", "0.85", "0.95", "--dry-run"]) == 0

    assert [name for name, _ in steps.log] == ["run", "run"]
    assert all(argv[-1] == "--dry-run" for _, argv in steps.log)
    out = capsys.readouterr().out
    assert f"skipped (dry run): boa-data-prepare --input-file {workbook} --scenario mycase" in out
    assert f"skipped (dry run): boa-cds-prepare --weather_year {ERA5_DATA_YEAR} --use-republished" in out
    assert out.splitlines()[-2:] == [
        f"BOA_RUN=mycase_{HASH}",
        f"BOA_RUN_DIR={tmp_path / 'lcoe-only' / f'mycase_{HASH}'}",
    ]
    assert sorted(tmp_path.rglob("*")) == before


def test_dry_run_through_boa_runs_own_parser_writes_nothing(tmp_path, monkeypatch, caplog, capsys):
    """boa-run accepts every option routed to it, and resolves the run the last lines name."""
    monkeypatch.setenv("BOA_DATA_ROOT", str(tmp_path))
    config = PathConfig.from_root(tmp_path, input_set="cds-2023", cost_set="mycase")
    for region in REGION_COORDS:
        (config.zarr_dir / (profile_store_stem(region, 2023) + ".zarr")).mkdir(parents=True)
        (config.zarr_dir / (max_cap_store_stem(region, 2023) + ".zarr")).mkdir(parents=True)
    config.input_data_path.parent.mkdir(parents=True)
    config.input_data_path.touch()
    before = sorted(tmp_path.rglob("*"))

    def never(argv):
        raise AssertionError("a preparation step ran in a dry run")

    monkeypatch.setattr(data_prepare, "main", never)
    monkeypatch.setattr(run_cds, "main_prepare", never)
    argv = ["--scenario", "mycase", "--weather-year", "2023", "--run", "smoke", "--coverage", "0.85", "0.95"]
    argv += ["--start-year", "2025", "--end-year", "2026", "--frequency", "1", "--load-density", "1.0"]
    with caplog.at_level(logging.INFO):
        assert lcoe_pipeline.main([*argv, "--workers", "2", "--dry-run"]) == 0

    assert caplog.text.count(f"run: smoke_{HASH}") == 2
    assert capsys.readouterr().out.splitlines()[-2] == f"BOA_RUN=smoke_{HASH}"
    assert sorted(tmp_path.rglob("*")) == before


def test_a_prepared_custom_workbook_is_kept_by_boa_data_prepare(tmp_path, monkeypatch):
    """
    boa-data-prepare runs for real, with its downloads, workbook checks, geo data and cost cache stubbed.
    Without --input-file it would install the pinned package's workbook over the custom one.
    """
    monkeypatch.setenv("BOA_DATA_ROOT", str(tmp_path))
    workbook = _prepare_cost_set(tmp_path, "mycase", b"the custom cost workbook")

    def install_pinned_package(package_dir):
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / data_prepare.COST_DATA_WORKBOOK).write_bytes(b"the pinned cost workbook")

    monkeypatch.setattr(data_prepare, "_install_cost_data", install_pinned_package)
    monkeypatch.setattr(data_prepare, "_validate_workbook", lambda source: [2025])
    monkeypatch.setattr(data_prepare, "_smoke_test", lambda workbook, year: None)
    monkeypatch.setattr(data_prepare, "_prepare_geo_data", lambda *paths: None)
    monkeypatch.setattr(data_prepare, "_build_cost_cache", lambda *args: None)
    monkeypatch.setattr(run_cds, "main_prepare", lambda argv: 0)
    seen_by_boa_run = []
    monkeypatch.setattr(run_simulation, "main_run", lambda argv: seen_by_boa_run.append(workbook.read_bytes()) or 0)

    assert lcoe_pipeline.main(["--scenario", "mycase", "--coverage", "0.85"]) == 0
    assert seen_by_boa_run == [b"the custom cost workbook"]


def test_a_custom_cost_set_not_prepared_here_stops_before_any_step(steps, capsys):
    assert lcoe_pipeline.main(["--scenario", "mycase", "--coverage", "0.85"]) == 1
    assert steps.log == []
    assert "cost set 'mycase' is not prepared here; pass its workbook as --input-file" in capsys.readouterr().err


@pytest.mark.parametrize("scenario", [[], ["--scenario", "default"]], ids=["no-scenario", "default-scenario"])
def test_input_file_without_a_cost_set_of_its_own_stops_before_any_step(steps, capsys, tmp_path, scenario):
    """Prepared as the default cost set, a custom workbook would replace the default cost data."""
    workbook = tmp_path / "costs.xlsx"
    workbook.write_bytes(b"a custom cost workbook")

    assert lcoe_pipeline.main(["--input-file", str(workbook), *scenario]) == 1
    assert steps.log == []
    assert "--input-file needs a cost-set name of its own: add --scenario <name>" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("change", "made"),
    [
        ({"boa_version": "0.1.0"}, "was made by BOA 0.1.0"),
        ({"cost_set": "other"}, "was made for the cost set 'other', not 'mycase'"),
        ({"input_set": "cds-2023"}, f"was made on the input set 'cds-2023', not 'cds-{ERA5_DATA_YEAR}'"),
        ("workbook", "was made from another cost workbook"),
    ],
    ids=["version", "cost-set", "input-set", "workbook"],
)
def test_a_run_folder_boa_run_would_refuse_stops_before_any_step(steps, capsys, tmp_path, change, made):
    """
    boa-run refuses to add to a run folder of another BOA version, cost set, input set or cost workbook,
    so even a dry run stops.
    """
    config = PathConfig.from_root(tmp_path, input_set=f"cds-{ERA5_DATA_YEAR}", cost_set="mycase", run=f"mycase_{HASH}")
    _prepare_cost_set(tmp_path, "mycase", b"the workbook the run was made from")
    run_manifest.record_invocation(config, "run", [])
    if change == "workbook":
        _prepare_cost_set(tmp_path, "mycase", b"another cost workbook")
    else:
        manifest = json.loads(config.run_manifest_path.read_text())
        manifest["provenance"].update(change)
        config.run_manifest_path.write_text(json.dumps(manifest))

    assert lcoe_pipeline.main(["--scenario", "mycase", "--dry-run"]) == 1
    assert steps.log == []
    assert f"the run folder mycase_{HASH} {made}" in capsys.readouterr().err
    assert lcoe_pipeline.main(["--scenario", "mycase", "--run", "fresh", "--dry-run"]) == 0


# ---- --like ------------------------------------------------------------------

WORKBOOK = b"the original cost workbook"


def _install_pinned_cost_package(root, workbook):
    """
    Install the pinned cost data package under `root` as boa-data-prepare does, with `workbook` as its
    workbook, and copy it into the default cost set. Returns the default set's workbook path.
    """
    package_dir = PathConfig.from_root(root).data_dir / COST_DATA_FOLDER
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / COST_DATA_WORKBOOK).write_bytes(workbook)
    (package_dir / COST_DATA_INSTALLED).write_text(json.dumps({"sha256": COST_DATA_SHA256}))
    return _prepare_cost_set(root, "default", workbook)


def _promoted_file(root, cost_set="mycase", years=(2030, 2035, 2040), **overrides):
    """
    A small promoted LCOE file for a run of `cost_set` on weather year 2023, at coverage 0.9 and
    2.0 MW/km2, with its cost workbook prepared under `root`. `overrides` replace attributes.
    """
    config = PathConfig.from_root(root, input_set="cds-2023", cost_set=cost_set, run=f"{cost_set}_{HASH}")
    config.input_data_path.parent.mkdir(parents=True)
    config.input_data_path.write_bytes(WORKBOOK)
    run_manifest.record_invocation(config, "run", [])
    scenario = {
        "investment_horizon_years": 25,
        "load_density_mw_km2": 2.0,
        "coverage_fraction": 0.9,
        "search_params_hash": "a7d2c707",
        "era5_weather_year": 2023,
        "era5_resolution_deg": 0.25,
        "capacity_ceiling_applied": 0,
    }
    attrs = {**lcoe_promotion._provenance_attrs(config, xr.Dataset(attrs=scenario), list(years)), **overrides}
    path = config.promoted_lcoe_path(2023, 2.0, 0.9, years[0], years[-1])
    path.parent.mkdir(parents=True)
    xr.Dataset(
        {"lcoe": ("year", np.zeros(len(years), dtype=np.float32))}, coords={"year": list(years)}, attrs=attrs
    ).to_netcdf(path)
    return path


def _run_argv(coverage="0.9", rest="--start-year 2030 --end-year 2040 --frequency 5 --load-density 2.0"):
    return (
        f"--promote-lcoe --weather-input cds-2023 --cost-input mycase --run mycase --coverage {coverage} {rest}".split()
    )


def test_like_fills_every_option_from_the_file(steps, capsys, tmp_path):
    like = _promoted_file(tmp_path)

    prepared = PathConfig.from_root(tmp_path, cost_set="mycase").input_data_path

    assert lcoe_pipeline.main(["--like", str(like)]) == 0
    assert steps.log == [
        ("data_prepare", ["--input-file", str(prepared), "--scenario", "mycase"]),
        ("cds_prepare", ["--weather_year", "2023", "--use-republished"]),
        ("run", _run_argv()),
    ]
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-2] == f"BOA_RUN=mycase_{HASH}"
    assert "warning" not in captured.err


def test_explicit_flags_win_over_the_file(steps, tmp_path):
    like = _promoted_file(tmp_path)
    argv = ["--like", str(like), "--coverage", "0.85", "0.95", "--start-year", "2035", "--load-density", "1.5"]

    assert lcoe_pipeline.main(argv) == 0
    rest = "--start-year 2035 --end-year 2040 --frequency 5 --load-density 1.5"
    assert [argv for name, argv in steps.log if name == "run"] == [_run_argv("0.85", rest), _run_argv("0.95", rest)]


def test_a_single_year_file_is_rerun_for_that_year(steps, tmp_path):
    """netCDF hands a one-element attribute back as a scalar."""
    like = _promoted_file(tmp_path, years=(2030,))

    assert lcoe_pipeline.main(["--like", str(like)]) == 0
    assert steps.log[-1] == ("run", _run_argv(rest="--start-year 2030 --end-year 2030 --load-density 2.0"))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("prepared", "pass that workbook as --input-file"),
        ("input_file", "pass that workbook as --input-file"),
        ("unprepared", "is not prepared here; pass the workbook"),
    ],
)
def test_another_cost_workbook_stops_before_any_step(steps, capsys, tmp_path, change, message):
    like = _promoted_file(tmp_path)
    prepared = PathConfig.from_root(tmp_path, cost_set="mycase").input_data_path
    argv = ["--like", str(like)]
    if change == "prepared":
        prepared.write_bytes(b"another cost workbook")
    elif change == "input_file":
        (tmp_path / "another.xlsx").write_bytes(b"another cost workbook")
        argv += ["--input-file", str(tmp_path / "another.xlsx")]
    else:
        prepared.unlink()

    assert lcoe_pipeline.main(argv) == 1
    assert steps.log == []
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("given", ["matching", "mismatching"])
def test_a_default_set_file_rerun_from_its_workbook_asks_for_a_cost_set_of_its_own(steps, capsys, tmp_path, given):
    """
    Whichever way the workbook reaches the run, it must not land in the default cost set: passed as
    --input-file, or found to differ from the pinned workbook boa-data-prepare installs there.
    """
    like = _promoted_file(tmp_path, cost_set="default")
    argv = ["--like", str(like)]
    if given == "matching":
        original = tmp_path / "original.xlsx"
        original.write_bytes(WORKBOOK)
        argv += ["--input-file", str(original)]
    else:
        _install_pinned_cost_package(tmp_path, b"another cost workbook")

    assert lcoe_pipeline.main(argv) == 1
    assert steps.log == []
    err = capsys.readouterr().err
    assert "--scenario" in err and "of its own" in err and "a new --run" in err


def test_the_original_workbook_as_input_file_reruns(steps, tmp_path):
    like = _promoted_file(tmp_path)
    PathConfig.from_root(tmp_path, cost_set="mycase").input_data_path.unlink()
    original = tmp_path / "original.xlsx"
    original.write_bytes(WORKBOOK)

    assert lcoe_pipeline.main(["--like", str(like), "--input-file", str(original)]) == 0
    assert steps.log[0] == ("data_prepare", ["--input-file", str(original), "--scenario", "mycase"])


@pytest.mark.parametrize(
    ("installed", "ran"), [(WORKBOOK, ["data_prepare", "cds_prepare", "run"]), (b"x", ["data_prepare"])]
)
def test_an_unprepared_default_cost_set_is_checked_once_boa_data_prepare_installs_it(steps, tmp_path, installed, ran):
    like = _promoted_file(tmp_path, cost_set="default")
    PathConfig.from_root(tmp_path, cost_set="default").input_data_path.unlink()
    steps.effects["data_prepare"] = lambda: _install_pinned_cost_package(tmp_path, installed)

    assert lcoe_pipeline.main(["--like", str(like)]) == (0 if installed == WORKBOOK else 1)
    assert [name for name, _ in steps.log] == ran


@pytest.mark.parametrize(
    ("pinned", "prepared", "ran"),
    [
        (b"another cost workbook", WORKBOOK, []),
        (WORKBOOK, b"another cost workbook", ["data_prepare", "cds_prepare", "run"]),
    ],
    ids=["pinned-differs", "prepared-differs"],
)
def test_a_default_set_file_is_checked_against_the_workbook_boa_data_prepare_installs(
    steps, tmp_path, pinned, prepared, ran
):
    """The default set's workbook is replaced by the pinned package's, so that is the one compared."""
    like = _promoted_file(tmp_path, cost_set="default")
    _install_pinned_cost_package(tmp_path, pinned)
    _prepare_cost_set(tmp_path, "default", prepared)

    assert lcoe_pipeline.main(["--like", str(like)]) == (1 if not ran else 0)
    assert [name for name, _ in steps.log] == ran


def test_another_boa_version_warns(steps, capsys, tmp_path):
    like = _promoted_file(tmp_path, boa_version="0.1.0")

    assert lcoe_pipeline.main(["--like", str(like)]) == 0
    err = capsys.readouterr().err
    assert f"produced by BOA 0.1.0; this is BOA {boa.__version__}" in err
    assert "may differ if LCOE-changing code landed" in err
    assert f"if its run folder mycase_{HASH} is on this machine, the rerun needs a new --run" in err


def test_a_label_resolving_to_another_run_folder_warns(steps, capsys, tmp_path):
    like = _promoted_file(tmp_path, run="mycase_0000")

    assert lcoe_pipeline.main(["--like", str(like)]) == 0
    assert f"resolves the label 'mycase' to mycase_{HASH}" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"input_set": "cds-2023-lulc"}, "prepares only 'cds-2023'"),
        ({"promoted_years": np.array([2030, 2031, 2035], dtype="int32")}, "cannot produce the years"),
    ],
)
def test_a_file_boa_lcoe_cannot_rerun_stops_before_any_step(steps, capsys, tmp_path, overrides, message):
    like = _promoted_file(tmp_path, **overrides)

    assert lcoe_pipeline.main(["--like", str(like)]) == 1
    assert steps.log == []
    assert message in capsys.readouterr().err


def test_a_file_without_the_attributes_stops(steps, capsys, tmp_path):
    other = tmp_path / "other.nc"
    xr.Dataset({"lcoe": ("year", np.zeros(1))}).to_netcdf(other)

    assert lcoe_pipeline.main(["--like", str(other)]) == 1
    assert "is not a promoted LCOE file" in capsys.readouterr().err


def test_like_dry_run_reads_the_file_only_and_writes_nothing(steps, tmp_path):
    like = _promoted_file(tmp_path)
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")}
    digest = hashlib.sha256(like.read_bytes()).hexdigest()

    assert lcoe_pipeline.main(["--like", str(like), "--dry-run"]) == 0
    assert steps.log == [("run", [*_run_argv(), "--dry-run"])]
    assert {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*")} == before
    assert hashlib.sha256(like.read_bytes()).hexdigest() == digest
