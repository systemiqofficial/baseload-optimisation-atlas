# Running the model

`boa-run` is always GLOBAL (all regions in `REGION_COORDS`); the one exception is the single-point mode:

```bash
boa-run --load-density 1.0 --coverage 0.95       # full run: build caches if missing, query every year
boa-run build-cache                              # year- and baseload-independent frontier caches only
boa-run query --start-year 2030 --end-year 2030  # NetCDFs from pre-built caches (--force to re-derive)
boa-run point --lat 52.5 --lon 13.4              # single point; region auto-derived
boa-run --weather-input cds-2023 --cost-input rev3 --dry-run  # resolve paths + preflight, run nothing
```

`--weather-input` alone identifies the weather side (stores + frontier cache; the weather
year is read off the store filenames, never passed; default `cds-2024`), `--cost-input`
the cost side (xlsx + per-year cost cache), and `--run` labels the output (default
`<cost-input>`; the on-disk directory is always `<label>_<hash>`, forking automatically
whenever a physical or search-tuning parameter changes -- `boa-promote-lcoe --run <label>`
resolves the label back to it). A preflight
check fails fast with the exact `boa-cds-prepare` / `boa-data-prepare` command when the
selected sets are incomplete. Frontier caches are baseload-independent and year-independent:
one cache per (coverage, weather year, search parameters) serves every `--load-density` and
every investment year, and is shared across every cost set and every land-availability layer
set built on the same weather. Each cache records the anchors it was built with (the cost mixes
that placed its dense search patches). The full run reuses a cache while those anchors cover
every (cost key, year) it is about to query, and otherwise rebuilds it over its old anchors
plus the new ones, so a new cost set or a longer horizon rebuilds once and then stays covered.
A cache built under another `FRONTIER_CACHE_VERSION`, raised by hand when code that changes the
LCOE lands, is rebuilt instead, and `query` refuses it.
Once a cache holds `max_anchors` anchors it is reused as it is, with a warning, since a rebuild
could add no anchor. Use `build-cache --force` or `query --force` for targeted rebuilds. `--load-density` is MW/km2, not
an absolute demand (D1): each pixel's own demand is
`load_density * pixel_area(lat)`, so results are latitude-correct rather than one flat MW
figure applied everywhere. A `query` against a warm cache is arithmetic per pixel and takes
minutes per year.

Map PNGs (`lcoe`, `solar_factor`, `wind_factor`, `battery_factor`, per region and GLOBAL) are
**off by default** — pass `--plots` to `boa-run` or `boa-run query` to generate them. The
"Regridding regional datasets onto the global grid" log line that prints right before a query
finishes is the GLOBAL-NetCDF assembly step, not plot generation; it prints whether or not
`--plots` was given.

**The capacity ceiling is not yet applied at query time** (tracked as M4,
follow-up "Grid 2" work): every query currently reports the *unconstrained* optimum for
its coverage target, regardless of `--load-density`, and logs a warning saying so. Do not
promote results from a run in this window.

`--exact-designs`, on `boa-run` and each of its subcommands, makes the dense patch search
dispatch only the float32 sizes that a frontier keeps, so every design it keeps meets the
coverage target. Without it, the float32 rounding leaves a few stored designs short of their
target: 1 in about 12,000 over ten sample cells of BOA's 2024 weather. The flag is off by
default. It gives the run a folder of its own, since it enters the run's hash, and the run's
frontier caches names of their own, ending in `_exact`. When one label has run folders with
and without it, `boa-promote-lcoe --run` needs the folder's full name, `<label>_<hash>`.

## A process with a minimum load

`--min-load <share>` builds and prices for a process that can turn down. In any hour when the
battery's charge and the hour's solar and wind reach that share of full load, the process runs,
taking up to its full load; below it, the process stops and the battery stores the hour's
generation. Coverage then counts the hours the process runs, the served fraction is the energy
it uses, and the levelised cost of electricity (LCOE) is per MWh used.

```bash
boa-run --load-density 1.0 --coverage 0.85 --min-load 0.3
```

- **Names of its own.** The minimum load names the run's folder, its frontier caches
  (`cov0p85_minload0p3`) and its outputs, and the outputs' attributes record it as `min_load`.
- **Exact designs.** A minimum load turns `--exact-designs` on: every stored design is one the
  search dispatched at the sizes the cache keeps, and every stored battery size meets the
  coverage target.
- **Energy below hours.** The energy used, as a share of full-load energy, can fall well below
  the share of hours run. On the extract of BOA's 2024 weather for two Spanish blocks
  (`tests/data/`), at coverage 0.85 and cost year 2025, the cheapest design of every cell runs in 85 per cent of
  hours, but flat designs deliver about 0.90 of full-load energy, designs at a minimum load of
  0.3 use 0.75 to 0.78 of it and designs at 0.2 use 0.62 to 0.74.
- **No proof claimed.** BOA does not present the search or the containment certificate as
  proof of the cheapest design under a minimum load.
- **Never promoted.** The promoted file is a contract with the steel simulation for flat
  demand, so promotion refuses such a run. After a minimum-load run under the same label as a
  flat one, `boa-promote-lcoe --run` needs the flat run's full folder name, `<label>_<hash>`.

## Handing LCOE to the steel simulation

`boa` imports nothing from `steelo`; the dependency runs one way (steelo → boa). The steel
simulation reads exactly one variable off a run — `lcoe` — so a finished run is promoted into
one combined file per scenario:

```bash
boa-promote-lcoe --run cds-2024__china_test        # every scenario in a finished run
boa-run --load-density 1.0 --coverage 0.95 --promote-lcoe   # or inline, right after the query
```

Promotion stacks every year into a single `(year, lat, lon)` float32 variable and stores the
cost keys and status codes once (they are year-invariant, and promotion refuses to run if they
are not). Output: `lcoe-only/<run>_<hash>/optimal_lcoe_wy<year>_<rho>MWkm2_cov<c>_<first>_<last>.nc`,
carrying its own provenance (run name, input/cost sets, workbook sha256, boa version, git sha,
scenario settings) so it identifies what produced it without the run directory. Its layout is a
contract with the steel simulation: see [promoted-lcoe-file.md](promoted-lcoe-file.md).
