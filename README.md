# BOA: Baseload Optimisation Atlas

BOA answers one question, for any location on Earth: what's the cheapest combination of
solar panels, wind turbines, and batteries that can reliably supply a fixed, round-the-clock
power demand?

Industrial processes like steelmaking often need power around the clock, but solar and wind
output rises and falls with the hour and the season. BOA works out, for a given place, how
much solar, wind, and battery capacity is needed so that renewables cover a chosen share of
that steady demand (say, 85% of the time) — and what that costs per unit of energy delivered
(LCOE), using whichever mix gets there most cheaply.

## About

<a href="https://www.systemiq.earth"><img src="docs/assets/logos/systemiq-logo.png" alt="SYSTEMIQ" height="50"></a>&nbsp;&nbsp;<a href="https://it-u.at/en/"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/assets/logos/itu-logo-white.png"><img src="docs/assets/logos/itu-logo-black.png" alt="Interdisciplinary Transformation University (IT:U)" height="50"></picture></a>

BOA is a collaboration between [SYSTEMIQ](https://www.systemiq.earth) and the
[Interdisciplinary Transformation University (IT:U)](https://it-u.at/en/). It was first created as part of
[Steel-IQ](https://github.com/systemiqofficial/steel-iq) (see also
[steel-iq.systemiq.earth](https://steel-iq.systemiq.earth)) and has since become a standalone
package, developed in [this repository](https://github.com/systemiqofficial/baseload-optimisation-atlas).

**Web front end.** [boa.systemiq.earth](https://boa.systemiq.earth), hosted by SYSTEMIQ, still runs
the earlier stochastic (Monte-Carlo) version of BOA. An update to the new
[bisection-search methodology](docs/methodology.md) is coming shortly.

**Using BOA?** We'd like to hear about it: please
[open an issue](https://github.com/systemiqofficial/baseload-optimisation-atlas/issues) and tell us
how you use it.

## How it works

BOA runs on real hourly weather history (sun and wind) for every region of the world. For
each region, it first works out — across a fine grid of possible solar/wind/battery sizes —
how well each combination actually meets the demand target against that real weather record.
This step depends only on the weather, not on cost, so it's computed once per region and
reused afterwards. Equipment and financing costs (which vary by country and by year) are then
applied on top, to pick the cheapest combination that still meets the demand target for a
given year and location. The result — cost per unit of energy delivered — feeds into a wider
industry simulation (Steel-IQ) as the going rate for renewable power at that place and time.

## Install

Requires Python >=3.13.

```bash
uv sync --extra cds        # --extra cds pulls in the CDS API client (lazy-imported, optional)
source .venv/bin/activate  # puts boa-run, boa-lcoe and the other commands on PATH
uv run pytest              # full test suite
```

The commands below assume the environment is activated. Without activating it, prefix each one with
`uv run`.

## Quickstart

```bash
boa-data-prepare                                    # cost workbook + static geo data -> costs/default/
boa-cds-download --year 2024                         # raw weather data from CDS    -> data/cds/
boa-cds-prepare --weather_year 2024                  # weather-side stores          -> inputs/cds-2024/
boa-run --load-density 1.0 --coverage 0.95 --dry-run # sanity-check, then drop --dry-run to run
```

`boa-cds-download` needs a CDS account, `~/.cdsapirc` and `uv sync --extra cds`. Without an account,
skip it and run `boa-cds-prepare --weather_year 2024 --use-republished`, which downloads the
re-published copy of that year's capacity factors instead (weather years 2020 to 2025).

## One command: `boa-lcoe`

`boa-lcoe` runs `boa-data-prepare` and `boa-cds-prepare --use-republished`, then
`boa-run --promote-lcoe` once per coverage, so it needs no CDS account. The prepared data, the
frontier caches and the per-year results are reused when already in place, so a rerun after a
failure picks up where it stopped; only the promoted LCOE files are written again on every call.

```bash
boa-lcoe --coverage 0.85 0.95                         # one boa-run per coverage
boa-lcoe --input-file costs.xlsx --scenario mycase    # a custom cost workbook, under a name of its own
boa-lcoe --run smoke --start-year 2025 --end-year 2026 --dry-run
boa-lcoe --like ~/.boa/lcoe-only/default_49e8/optimal_lcoe_wy2024_01MWkm2_cov0p85_2025_2060.nc --run rerun
```

- **`--dry-run`** prints each step's command, skips both preparation steps and runs
  `boa-run --dry-run`, which checks the arguments against the data on disk.
- **`--like FILE`** reruns the run behind a promoted LCOE file, taking its cost set, weather year,
  coverage, load density, years and run label from the file; options given on the command line
  take precedence. It stops when the cost workbook here is not the one the file was produced with:
  pass that workbook as `--input-file`. A file from another BOA version usually needs a new
  `--run`, as in the example, since its run folder may be on this machine.
- **Custom cost workbooks**: `--input-file` needs a `--scenario` name of its own, so the default
  cost set is never replaced. Later runs of that cost set can leave out `--input-file`: its prepared
  workbook is kept. A cost set not prepared on this machine needs `--input-file`.
- **Run folders**: a run folder made by another BOA version, for another cost set, on another
  weather year or from another cost workbook is refused before any step; pass a new `--run`.
- **Output**: the last two lines of standard output are `BOA_RUN=<run>` and `BOA_RUN_DIR=<folder>`,
  the run name and its folder of promoted LCOE files under `lcoe-only/`. Steel-IQ takes the run name as
  `run_simulation --boa-run <run>`.

A full run from 2025 to 2060 takes about 75 minutes per coverage, and one weather year with five
coverages needs about 60 GB under the data root.

## Documentation

- [docs/running-the-model.md](docs/running-the-model.md) — `boa-run` in depth, and handing a run's LCOE to the steel simulation.
- [docs/promoted-lcoe-file.md](docs/promoted-lcoe-file.md): the format of the promoted LCOE file the steel simulation reads.
- [docs/cds-data-pipeline.md](docs/cds-data-pipeline.md) — building the weather-side Zarr stores from raw CDS data.
- [docs/cost-data-prep.md](docs/cost-data-prep.md) — the cost workbook, static geo data, and the on-disk data layout.
- [docs/methodology.md](docs/methodology.md) — the bisection search: conceptual walkthrough, parameters, and a worked figure.
- [docs/model-assumptions.md](docs/model-assumptions.md) — sourced references for the physical parameter assumptions.
- [docs/comparing-code-versions.md](docs/comparing-code-versions.md) — a separate data root per code version, sharing the large inputs.
- [docs/roadmap.md](docs/roadmap.md) — open items.
- [CHANGELOG.md](CHANGELOG.md): changes by version.
