# Changelog

Changes to BOA by version, newest first. Each version is a git tag, for example `v1.10.0`.

## 1.10.0

### Added

- **`boa-lcoe`**: one command from cost data to promoted LCOE file. It runs `boa-data-prepare` and
  `boa-cds-prepare --use-republished`, then `boa-run --promote-lcoe` once per value of `--coverage`,
  and stops at the first step that fails, with that step's exit code. Its last two lines of
  standard output are `BOA_RUN=<run>` and `BOA_RUN_DIR=<folder>`. A custom cost set's prepared
  workbook is handed to `boa-data-prepare`, so the pinned workbook never replaces it. Before any
  step, it stops when `--input-file` comes without a `--scenario` name of its own, when a custom
  cost set has neither `--input-file` nor a prepared workbook here, and when the run folder was
  made by another BOA version, for another cost set or from another cost workbook, asking for a
  new `--run`.
- **`boa-lcoe --dry-run`**: prints each step's command, skips the two preparation steps and runs
  `boa-run --dry-run`.
- **`boa-lcoe --like FILE`**: reruns the run that produced a promoted LCOE file, taking its cost set,
  weather year, coverage, load density, years and run label from the file. Options given on the
  command line take precedence. It stops before any step when the file was built on an input set
  `boa-lcoe` does not prepare, or when the cost workbook the run would use is not the one the file
  was produced with. For the default cost set that workbook is the pinned cost data package's; when
  the package is not installed yet, the check runs once `boa-data-prepare` has installed it. It
  warns when the file comes from another BOA version, whose run folder needs a new `--run`.

### Changed

- **Frontier cache version**: each frontier cache records `FRONTIER_CACHE_VERSION`, raised by hand
  whenever code that changes the LCOE lands. A build rebuilds a cache from another version, and
  `boa-run query`, which never builds, refuses one. Caches written before this field count as
  version 1, the current version, so they stay valid.
- **Recorded commit**: `run.json` (`git_sha`, promoted as `run_git_sha`) and the frontier cache
  (`code_git_sha`) now record BOA's own commit, read from the installed package (as `uvx --from
  git+...@<tag>` installs it) or from git in the package's folder when git tracks the package
  there, and none otherwise. Before, they recorded the commit of the directory BOA was started
  from. Both hold 12 characters; `run.json` held git's short form, usually 7, before.
- **Packaging**: `uv build` gives a wheel that contains the `boa` package. The source distribution
  moved `src/boa` to its top level, so the wheel built from it held no code.

### Documentation

- This changelog replaces `src/boa/CHANGELOG.md`.
- The README adds activating the environment, the weather-data step and a `boa-lcoe` section.
- `docs/running-the-model.md` and `docs/comparing-code-versions.md` describe the frontier cache version.

## 1.9.0

### Added

- **`boa-data-prepare`**: installs the pinned core data package (Natural Earth shapefiles and the
  ERA5 land-sea mask) and cost data package (`boa-cost-data` v0.1), builds the iso3 grid, and
  checks, smoke-tests and copies a cost workbook into `costs/<scenario>/` (`--input-file`,
  `--scenario`).
- **`boa-cds-prepare --use-republished`**: downloads the re-published copy of a year's capacity
  factors (2020 to 2025) when the raw CDS data is missing, so no CDS account is needed.
- **Promoted file contract**: promoted LCOE files carry `schema_version`, `lcoe_basis` and
  `capacity_ceiling_applied`, described in `docs/promoted-lcoe-file.md`. Promotion refuses
  per-year files that do not record `capacity_ceiling_applied`.
- **Documentation**: the bisection-search methodology, comparing two code versions, the cost
  workbook's units, fallbacks and checks, and an About section in the README.

### Changed

- **Data root**: `$BOA_DATA_ROOT`, else `~/.boa`, with a warning when only the previous default
  root exists. Promoted LCOE files go to `lcoe-only/` instead of `lcoe-for-steel-iq/`.
- **No optimum is NaN**: pixels without an optimum hold NaN, not 0, in every field the search did
  not produce.
- **Frontier cache reuse**: a cache records the anchors it was built with and is reused only while
  they cover the run's cost mixes; otherwise it is rebuilt over its old anchors plus the new ones.
- **Cost workbook**: columns are read as the workbook names them; RES OPEX can differ by IRENA
  region; missing CAPEX comes from the costliest IRENA region, with a warning, instead of a mean
  across technologies; CAPEX is interpolated linearly between year columns; blank or non-numeric
  values fail; surrounding spaces in key columns are ignored; and a warning names countries whose
  cost of capital falls back to the highest rate.
- **Cost cache**: rebuilt when its workbook or the cost loader changes.
- **`boa-cost-data` v0.1 re-pinned**: corrected the RES OPEX unit label and revised some solar PV
  and onshore wind CAPEX rows.
- **iso3 grid**: rebuilt when the region remap (`NE_TO_BOA`) changes, not only the shapefile.
- **`boa-cds-prepare`**: leaves nothing in `staging/` once it has installed its stores.

## Earlier versions

Versions before 1.9.0 are recorded only in their git tags and commit history, for example
`git log --oneline v1.7.0..v1.8.0`.
