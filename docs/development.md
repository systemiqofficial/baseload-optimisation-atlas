# Project status and contributing

This page tells you the status of BOA and how to report a problem.

## Status

BOA is work in progress. The method, the output files and the commands can change between
versions. The [changelog](changelog.md) lists the changes. The
[known limitations](known-limitations.md) page lists what the results do not cover.

The project cannot support large outside contributions yet. Please do not start a large change,
for example a new module or a new model feature, without talking to the maintainers first.

## Report a problem

To report a problem, a wrong result or a question,
[open an issue](https://github.com/systemiqofficial/baseload-optimisation-atlas/issues) in the
GitHub repository. Include this information:

- The BOA version (`boa.__version__`).
- The command that you ran, with all options.
- The error message, or a description of the result that you did not expect.
- The `run.json` file in the run folder, or the attributes of the
  [promoted LCOE file](promoted-lcoe-file.md). The file `run.json` records the weather set, the
  cost set and the search settings. The promoted file records the weather set, the cost set and
  a hash of the search settings (`search_params_hash`). The maintainers use this information to
  reproduce the run.

Small fixes, for example a correction to a page of this site, are welcome as a pull request.

## Using BOA

If you use BOA in your work, please tell the maintainers in an issue. This helps the project to
decide what to build next.
