# Installation

This page shows how to install BOA, how to check the installation, and where BOA keeps its data.
After the installation, go to the [Quickstart](quickstart.md) for a first run.

## Requirements

- Python 3.13 or later.
- [uv](https://docs.astral.sh/uv/), to install the dependencies.
- An internet connection. The commands that prepare the data download it (see the
  [Quickstart](quickstart.md)).
- A Copernicus Climate Data Store (CDS) account, only if you download the raw weather data
  yourself with `boa-cds-download`. The Quickstart uses a re-published copy of the weather data and
  needs no account.

## Install BOA

```bash
git clone https://github.com/systemiqofficial/baseload-optimisation-atlas.git
cd baseload-optimisation-atlas
uv sync
```

`uv sync` makes a virtual environment in `.venv/` and installs BOA and its dependencies. It puts
these commands in the environment:

| Command | What it does |
|---|---|
| `boa-data-prepare` | Prepares the cost set and the static geographic data. |
| `boa-cds-prepare` | Builds the weather stores for one weather year. |
| `boa-cds-download` | Downloads the raw weather data from the CDS. |
| `boa-run` | Runs the model. It has the sub-commands `build-cache`, `query` and `point`. |
| `boa-promote-lcoe` | Combines the per-year files of a run into one promoted LCOE file. |
| `boa-lcoe` | Runs the preparation, `boa-run` and the promotion in one command. |

To use `boa-cds-download`, install the optional CDS client with the extra `cds`:

```bash
uv sync --extra cds
```

## Activate the environment

Activate the environment, so that the commands are on your path:

```bash
source .venv/bin/activate        # Linux and macOS
.venv\Scripts\activate           # Windows, cmd
.venv\Scripts\Activate.ps1       # Windows, PowerShell
```

The pages of this site show the commands without a prefix, as if the environment is active. If you
do not activate it, put `uv run` before each command, for example `uv run boa-run --help`.

## Check the installation

```bash
boa-run --help
```

The command prints the usage of `boa-run` and the list of its options. The sub-commands have their
own help, for example `boa-run point --help`.

## Use BOA in another project

To use BOA as a dependency of another Python project, add it as a git dependency:

```bash
uv add git+https://github.com/systemiqofficial/baseload-optimisation-atlas.git
```

## The data root

BOA keeps all its data in one folder, the **data root**. It is the folder in the environment
variable `BOA_DATA_ROOT`. When this variable is not set, it is `.boa` in your home folder.

| Folder | Content |
|---|---|
| `data/` | Geographic reference data, the raw weather data and the cost package |
| `inputs/<weather set>/` | A [weather set](glossary.md#weather-set): the weather stores of one weather year, and its frontier cache |
| `costs/<cost set>/` | The cost workbook of one cost set |
| `runs/<run>_<hash>/` | The per-year files and the provenance of one run |
| `lcoe-only/<run>_<hash>/` | The promoted LCOE files of one run |

The download of the re-published weather data of one year is about 6.6 GB.

A full run needs much more space. A run from 2025 to 2060 with five coverage targets needs about
60 GB under the data root for one weather year (the figure is from the README). The run of the
[Quickstart](quickstart.md) is much smaller: it has one investment year and one coverage target.

Choose a data root on a disk with enough free space, for example:

```bash
export BOA_DATA_ROOT=/data/boa           # Linux and macOS
$env:BOA_DATA_ROOT = "D:\boa"            # Windows PowerShell
```

[Running the model](running-the-model.md#select-the-weather-set-the-cost-set-and-the-run-label)
explains how to select the weather set, the cost set and the run label.
