# BOA: Baseload Optimisation Atlas

BOA answers one question, for any location on Earth: what's the cheapest combination of
solar panels, wind turbines, and batteries that can reliably supply a fixed, round-the-clock
power demand?

Industrial processes like steelmaking often need power around the clock, but solar and wind
output rises and falls with the hour and the season. BOA works out, for a given place, how
much solar, wind, and battery capacity is needed so that renewables cover a chosen share of
that steady demand (say, 85% of the time) — and what that costs per unit of energy delivered
(LCOE), using whichever mix gets there most cheaply.

## How it works

BOA runs on real hourly weather history (sun and wind) for every region of the world. For
each region, it first works out — across a fine grid of possible solar/wind/battery sizes —
how well each combination actually meets the demand target against that real weather record.
This step depends only on the weather, not on cost, so it's computed once per region and
reused afterwards. Equipment and financing costs (which vary by country and by year) are then
applied on top, to pick the cheapest combination that still meets the demand target for a
given year and location. The result — cost per unit of energy delivered — feeds into a wider
industry simulation (`steelo`) as the going rate for renewable power at that place and time.

## Install

Requires Python >=3.13.

```bash
uv sync --extra cds   # --extra cds pulls in the CDS API client (lazy-imported, optional)
uv run pytest         # full test suite
```

## Quickstart

```bash
boa-data-prepare                                    # cost workbook + static geo data -> costs/default/
boa-cds-prepare --weather_year 2024                  # weather-side stores          -> inputs/cds-2024/
boa-run --load-density 1.0 --coverage 0.95 --dry-run # sanity-check, then drop --dry-run to run
```

## Documentation

- [docs/running-the-model.md](docs/running-the-model.md) — `boa-run` in depth, and handing a run's LCOE to the steel simulation.
- [docs/cds-data-pipeline.md](docs/cds-data-pipeline.md) — building the weather-side Zarr stores from raw CDS data.
- [docs/cost-data-prep.md](docs/cost-data-prep.md) — the cost workbook, static geo data, and the on-disk data layout.
- [docs/model-assumptions.md](docs/model-assumptions.md) — sourced references for the physical parameter assumptions.
- [docs/roadmap.md](docs/roadmap.md) — open items.
- [HANDOFF_cost_schema_contract.md](HANDOFF_cost_schema_contract.md) — open task: publish and validate the cost-workbook contract as its own doc.
- [src/boa/CHANGELOG.md](src/boa/CHANGELOG.md) — the Monte-Carlo → grid-bisection search rewrite.
