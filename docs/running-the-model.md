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
selected sets are incomplete. The full run never rebuilds an existing frontier cache; use
`build-cache --force` or `query --force` for targeted rebuilds. Frontier caches are
baseload-independent and year-independent: one cache per (coverage, weather year, search
parameters) serves every `--load-density` and every investment year, and is shared across
every land-availability layer set built on the same weather. `--load-density` is MW/km2, not
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
are not). Output: `lcoe-for-steel-iq/<run>/optimal_lcoe_<rho>MWkm2_cov<c>_<first>_<last>.nc`,
carrying its own provenance (run name, input/cost sets, workbook sha256, boa version, git sha,
scenario settings) so it identifies what produced it without the run directory.
