# Handoff: publish and validate the cost-workbook input contract

## Context

This package (`boa`) was extracted from the `steel-iq` monorepo into this standalone
repo, keeping the full commit history. `steel-iq` now consumes `boa` as an ordinary
git dependency (see its `pyproject.toml` / `[tool.uv.sources]`) and imports `boa.*`
directly — there is no steelo dependency inside this package, except one lazily
imported, try/except-guarded convenience flag (`--data-prepare` in
`src/boa/cli/run_simulation.py`, which degrades gracefully if steelo isn't
installed).

## The problem

`boa`'s cost-side input is a single xlsx workbook (conventionally named
`boa_cost_data.xlsx`) with four sheets. Today that shape is **implicit** — it exists
only as whatever `boa/inputs/costs.py` and `boa/geo/geospatial.py`'s
`CountryMappings.from_excel` happen to read via `pandas.read_excel(sheet_name=...)`.
Nothing in this repo documents or validates the contract as a public interface.

Meanwhile, `steel-iq`'s own repo has a producer for this workbook
(`src/steelo/entrypoints/boa_data_cli.py`) that extracts these four sheets out of a
much larger, steelo-proprietary master workbook and reshapes them (column renames, a
`Tech == "Renewables"` filter, territory deduplication) to match what `boa`'s loaders
expect. That producer currently has to read `boa`'s source to know the target shape —
there's no documented contract to code against. If this loading logic ever changes
here, the fix has to happen blind, in a different repo, by someone reverse-engineering
the diff.

## What's expected today (reverse-engineered from the current loaders — verify and formalize, don't just trust this list)

Sheet **`RES CAPEX projections`** (read by `preprocess_renewable_energy_cost_data`):
- `Technology` — one of `"Solar PV"`, `"Onshore wind"`, `"Battery"` (mapped internally
  to `solar`/`wind`/`battery`; unknown labels raise).
- `irena_region` — region name; whitespace gets stripped before matching.
- `Subregion code` — optional; format `<iso3>:<subregion>` (ISO 3166-2 style, e.g.
  `CHN:CN-HB`). If absent, synthesized as all-NA.
- One column per year (integer-typed column names), e.g. `2024`, `2025`, ... `2050`.
- Optional `Unit`, `Value` columns (dropped if present).
- Each `(Region/Subregion, Technology)` combination must be unique.

Sheet **`RES OPEX`** (same file, read by the same function):
- `Region`, `Technology` (same label set as above), `Opex` (world-wide percentage,
  applied uniformly per technology — i.e. effectively one row per technology).
- Optional `Unit` column (dropped if present).

Sheet **`Cost of capital`**:
- `Code` — ISO-3 country code. **Must be `"ESH"` for Western Sahara**, not the
  non-standard `"WES"` (a real past incident — a prior revision of this sheet had
  `"WES"` and silently dropped out of every join).
- `Tech` — only rows where `Tech == "Renewables"` are consumed (other tech rows, e.g.
  hydrogen, are tolerated in the sheet but ignored).
- `Cost of capital` — WACC value; missing values get filled with the sheet's own max
  as a fallback.
- One row per `Code` among the `Renewables` rows — duplicates raise.

Sheet **`Country mapping`** (read by `CountryMappings.from_excel`):
- `Code` — ISO-3 country code, must be unique (duplicates raise).
- `irena_region` — IRENA region name (joins against `RES CAPEX projections`/`RES OPEX`).
- `irena_name` — IRENA country name (builds `code_to_irena_map`; confirm what actually
  consumes this map and whether it has its own format constraints).

## The task

1. Read `src/boa/inputs/costs.py` and `src/boa/geo/geospatial.py` (`CountryMappings`)
   in full and write down the *exact* contract each sheet/column must satisfy —
   confirm or correct every point above, and fill in anything this handoff missed
   (e.g. the second `Country mapping` column, exact dtype expectations, whether
   columns can appear in any order, case-sensitivity of sheet/column names).
2. Publish that contract somewhere a producer can code against without reading this
   package's internals — a docs page (e.g. `docs/cost_workbook_schema.md`) is the
   minimum bar. A machine-checkable schema (e.g. a `pandera`/`pydantic` schema, or a
   plain `validate_cost_workbook(path) -> list[str]` function returning human-readable
   problems) is preferred if it's not much more work, since it turns "the loader threw
   a confusing pandas KeyError three calls deep" into an actionable error at the door.
3. If you add a validator, wire it into `boa-data-prepare`'s consumer-side flow isn't
   your job (that's steelo's repo) — just make the validator importable and documented
   so steelo's `boa_data_cli.py` can eventually call it instead of guessing.
4. Add/extend tests in `tests/` covering the documented contract (valid workbook
   passes, each documented violation is caught with a clear message).

## Non-goals

- Don't touch the `steel-iq` repo. This is scoped entirely to `boa`.
- Don't change the actual sheet/column names the loaders read today unless you find
  and fix a genuine bug — the goal is documenting and validating the existing
  contract, not redesigning it.
- The `--data-prepare` lazy steelo import in `run_simulation.py` is intentional
  (a convenience shortcut) and out of scope — don't remove or "fix" it.
