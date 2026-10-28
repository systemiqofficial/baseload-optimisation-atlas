"""
`boa-lcoe` runs boa-data-prepare, boa-cds-prepare and boa-run in order, passing on only the options given.

The three commands are replaced by recorders, except in the last test, where boa-run's own
parser and run naming are checked against a dry run on synthetic stores under `tmp_path`.
"""

import logging
from types import SimpleNamespace

import pytest

from boa.cli import data_prepare, lcoe_pipeline, run_cds, run_simulation
from boa.config import run_manifest
from boa.config.paths import PathConfig
from boa.config.physical_parameters import ERA5_DATA_YEAR, REGION_COORDS
from boa.model.bisection import SearchParams
from boa.store_schema import max_cap_store_stem, profile_store_stem

HASH = run_manifest.non_scenario_params_hash(SearchParams())


@pytest.fixture
def steps(tmp_path, monkeypatch):
    """
    Replaces the three commands with recorders that print to stdout, as BOA's logging does.

    `codes[name]` lists the exit codes that command returns on successive calls; 0 once used up.
    """
    monkeypatch.setenv("BOA_DATA_ROOT", str(tmp_path))
    recorded = SimpleNamespace(log=[], codes={})

    def recorder(name):
        def step(argv):
            recorded.log.append((name, list(argv)))
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
    assert lcoe_pipeline.main(argv) == 0

    run = f"{label}_{HASH}"
    assert capsys.readouterr().out.splitlines()[-2:] == [
        f"BOA_RUN={run}",
        f"BOA_RUN_DIR={tmp_path / 'lcoe-only' / run}",
    ]


def test_dry_run_prints_every_step_and_runs_only_boa_run_with_dry_run(steps, capsys, tmp_path):
    assert lcoe_pipeline.main(["--scenario", "mycase", "--coverage", "0.85", "0.95", "--dry-run"]) == 0

    assert [name for name, _ in steps.log] == ["run", "run"]
    assert all(argv[-1] == "--dry-run" for _, argv in steps.log)
    out = capsys.readouterr().out
    assert "skipped (dry run): boa-data-prepare --scenario mycase" in out
    assert f"skipped (dry run): boa-cds-prepare --weather_year {ERA5_DATA_YEAR} --use-republished" in out
    assert out.splitlines()[-2:] == [
        f"BOA_RUN=mycase_{HASH}",
        f"BOA_RUN_DIR={tmp_path / 'lcoe-only' / f'mycase_{HASH}'}",
    ]
    assert not any(tmp_path.iterdir())


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
