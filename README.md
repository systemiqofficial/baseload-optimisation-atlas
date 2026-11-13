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
[bisection-search methodology](https://systemiqofficial.github.io/baseload-optimisation-atlas/methodology/)
is coming shortly.

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

BOA needs Python 3.13 or later and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # add --extra cds to download weather data with your own CDS account
source .venv/bin/activate    # Windows PowerShell: .venv\Scripts\Activate.ps1
```

Without an activated environment, put `uv run` before each command. See
[Installation](https://systemiqofficial.github.io/baseload-optimisation-atlas/installation/).

## Quickstart

One command prepares the data, runs all regions and writes the LCOE files for the steel
simulation. It needs no CDS account:

```bash
boa-lcoe --coverage 0.85
```

A full run from 2025 to 2060 takes about 75 minutes for each coverage. The
[Quickstart](https://systemiqofficial.github.io/baseload-optimisation-atlas/quickstart/) shows each
step one by one, starting with one location.

## Documentation

The documentation is at
**[systemiqofficial.github.io/baseload-optimisation-atlas](https://systemiqofficial.github.io/baseload-optimisation-atlas/)**.

- [Running the model](https://systemiqofficial.github.io/baseload-optimisation-atlas/running-the-model/):
  `boa-run`, `boa-lcoe` and their options, and the output files.
- [Exporting results](https://systemiqofficial.github.io/baseload-optimisation-atlas/promoted-lcoe-file/):
  the LCOE file that the steel simulation reads.
- [Overview](https://systemiqofficial.github.io/baseload-optimisation-atlas/overview/) and
  [Search algorithm](https://systemiqofficial.github.io/baseload-optimisation-atlas/methodology/):
  how BOA finds the cheapest system.
- [Known limitations](https://systemiqofficial.github.io/baseload-optimisation-atlas/known-limitations/):
  what the results do not include, and the status codes.
- [CHANGELOG.md](CHANGELOG.md): changes by version.
