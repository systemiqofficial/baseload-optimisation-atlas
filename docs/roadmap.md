# Roadmap / open items

- CLI command to ingest pre-downloaded CDS capacity-factor data (today the extracted
  directories must be dropped into `data/cds/` by hand, see
  [cds-data-pipeline.md](cds-data-pipeline.md)).
- Record the CDS data version in the store metadata, and rebuild/add newly processed
  stores when the version differs for the same weather year.
- Multi-year weather-data runs (an input set currently holds exactly one weather year).
- Model: battery optimisation improvements.
- Save run log and config file.
- Output short status while running in terminal.
- Apply the capacity ceiling at query time (tracked as "Grid 2" — see
  [running-the-model.md](running-the-model.md)); every query currently reports the
  unconstrained optimum.
