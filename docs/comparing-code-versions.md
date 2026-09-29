# Comparing two versions of BOA's code

Runs with different `--run` labels already write to separate folders under one data root, so
comparing scenarios, cost sets or weather years needs nothing extra. A separate data root is only
needed when comparing two versions of BOA's own code, e.g. a feature branch against `main`.

## Why a shared root is not enough

The frontier cache (`inputs/cds-<year>/cache_frontiers/`) is shared by every run on the same
weather year. When a run reads a stored frontier, it checks only the search settings
(`SearchParams`), the coverage and the weather year. The store records the git SHA that built it
(`code_git_sha`), but nothing checks it. So if a code change alters the physics without changing
the search settings, the second version reuses the first version's cache, and the comparison
shows no difference. The per-year cost cache (`costs/<set>/cache_costs/`) has the same gap for
changes to the cost processing that don't bump `COST_CACHE_VERSION`.

## Before you start

Your usual root (`$MAIN`, normally `~/.boa`) holds everything both versions read, so prepare it
first, from the baseline version's checkout:

```bash
boa-data-prepare                                              # core + cost packages, iso3 grid, costs/default/
boa-data-prepare --input-file my_costs.xlsx --scenario <name> # each further cost set
boa-cds-prepare --weather_year 2024                           # each weather year -> inputs/cds-2024/
```

## One root per version

Each version needs its own checkout, its own environment and its own data root. Keep your usual
checkout for one version and add a worktree for the other:

```bash
git worktree add --detach ../boa-<arm> <branch-or-commit>
cd ../boa-<arm> && uv sync
```

Give the baseline a root of its own too, rather than running it against `$MAIN`: `$MAIN`'s
frontier cache may have been built by other code, and nothing would notice. The large inputs are
symlinked from `$MAIN` rather than copied, because `boa-run` only reads them:

```bash
MAIN=~/.boa                        # your usual data root
ARM=~/.boa-compare-<topic>-<arm>   # one per code version

mkdir -p "$ARM/inputs/cds-2024" "$ARM/costs/<cost-set>"
ln -s "$MAIN/data" "$ARM/data"                                           # raw CDS, core package, iso3 grid
ln -s "$MAIN/inputs/cds-2024/cds-zarr" "$ARM/inputs/cds-2024/cds-zarr"   # profile and max-capacity stores
cp "$MAIN/costs/<cost-set>/boa_cost_data.xlsx" "$ARM/costs/<cost-set>/"  # the workbook only, not its cache
```

Repeat the `cds-zarr` link for each weather year and the `cp` for each cost set you compare on.
To add a cost set later, prepare it in `$MAIN` and copy its workbook across. Don't run
`boa-data-prepare` against an arm whose `data/` is the shared link: it writes into `data/` (the
core and cost packages, the iso3 grid) whenever the arm's version pins or builds them differently.

Then run each version from its own checkout against its own root, and drop `--dry-run` once
the preflight passes:

```bash
cd <checkout-of-this-version>
BOA_DATA_ROOT="$ARM" uv run boa-run --load-density 1.0 --coverage 0.85 --cost-input <cost-set> --workers <n> --dry-run
```

| In `$ARM` | Shared or own |
|---|---|
| `data/` | shared (symlink), read-only during a run |
| `inputs/cds-<year>/cds-zarr/` | shared (symlink), read-only during a run |
| `inputs/cds-<year>/cache_frontiers/` | own, built by this version |
| `costs/<cost-set>/boa_cost_data.xlsx` | own copy |
| `costs/<cost-set>/cache_costs/` | own, built by this version on its first run |
| `runs/`, `lcoe-for-steel-iq/` | own |

## Running both at once

The two versions only share read-only inputs, so they can run at the same time. `--workers` sets
each run's threads, and its default, `fast`, takes all but two cores for each run, so split the
cores between the runs instead: on a 14-core machine, `--workers 6` each. At the default search
settings, each run needs up to about 5.5 GB of memory, and each arm's frontier cache takes about
0.7 GB per coverage and weather year.

## If the versions lay out `data/` differently

The shared `data/` link assumes both versions read the same paths under it. If one version moves
or renames something there, give the arm on the other layout a real `data/` folder holding a link
to each item at the path that version expects.

## If the change is to data preparation

The recipe above assumes the versions differ only in the model (`boa/model`, `boa/inputs`). If
the change touches data preparation (`boa/cds`, `boa/geo`), don't symlink `data/` or
`cds-zarr/`: `boa-cds-prepare` writes into both (the `data/cds/global_zarr/` intermediate and the
installed stores) and would overwrite your usual root. Link only the raw inputs and let each root
build the rest:

```bash
mkdir -p "$ARM/data/cds" "$ARM/inputs/cds-2024" "$ARM/costs/<cost-set>"
ln -s "$MAIN"/data/cds/cds_*_2024 "$ARM/data/cds/"  # raw CDS capacity factors
ln -s "$MAIN/data/boa-core-data" "$ARM/data/"       # shapefiles, land-sea mask
cp "$MAIN/data/iso3_grid.nc" "$ARM/data/"
cp "$MAIN/costs/<cost-set>/boa_cost_data.xlsx" "$ARM/costs/<cost-set>/"
BOA_DATA_ROOT="$ARM" uv run boa-cds-prepare --weather_year 2024
```

- **Disk space:** each such root needs about 12 GB for the `global_zarr` intermediate (you can
  delete it after prepare) and about 11 GB for the stores.
- **Grid-builder changes:** if the change is to the iso3 grid builder, rebuild the grid in that
  root with `boa-data-prepare` instead of copying it.
- **`--layers`:** also link `data/lulc/` and `data/cds/cds_masks_ic6hh135_0_25_degree/`.

## Comparing the results

With `--promote-lcoe`, each arm writes one file per scenario to `lcoe-for-steel-iq/<run>_<hash>/`.
Its `run_git_sha` attribute confirms which code produced it:

```python
import xarray as xr

a = xr.open_dataset("<root-a>/lcoe-for-steel-iq/<run>_<hash>/<file>.nc")
b = xr.open_dataset("<root-b>/lcoe-for-steel-iq/<run>_<hash>/<file>.nc")
print("code:", a.attrs["run_git_sha"], "vs", b.attrs["run_git_sha"])
diff = abs(b["lcoe"] - a["lcoe"])
print(f"identical: {a['lcoe'].equals(b['lcoe'])}; max |Δ| {float(diff.max()):.3g} USD/MWh; "
      f"{int((diff > 0).sum())} pixel-years differ; "
      f"{int((a['lcoe'].isnull() != b['lcoe'].isnull()).sum())} switch between NaN and a value")
```

## Cleaning up

Remove an arm with `rm -rf "$ARM"` and its checkout with `git worktree remove ../boa-<arm>`.
Removing the arm deletes the symlinks, not the shared data they point to. Never delete through a
link with a trailing slash (`rm -rf "$ARM/data/"`): it follows the link and deletes the shared
data itself.
