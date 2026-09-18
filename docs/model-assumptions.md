# Sources for model assumptions

References behind the numeric assumptions in `config/physical_parameters.py`. Tunable search
parameters (grid resolution, battery rungs, anchor tolerance) are a separate thing — see
`model/bisection.py`'s `SearchParams`, hashed into the frontier cache path so a changed value
forces a rebuild rather than silently reusing an incompatible store.

## Technology lifetimes (`LIFETIMES`)

- **Solar, 25 years** — IEA, *The world needs more diverse solar panel supply chains*, 2022, gives 25–30 years.
  https://www.iea.org/news/the-world-needs-more-diverse-solar-panel-supply-chains-to-ensure-a-secure-transition-to-net-zero-emissions
- **Wind, 25 years** — IRENA, *Leveraging Local Capacity for Onshore Wind*, Executive Summary, 2017, p. 20. Other sources give 20 years.
  https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2017/Jun/IRENA_Leveraging_for_Onshore_Wind_Executive_Summary_2017.pdf
- **Battery, 25 years** — aligned with solar/wind so no technology is reinstalled within the investment horizon.

## Deterioration rates (`YEARLY_DETERIORATION_RATES`)

Not read anywhere in the LCOE calculation today — kept as a sourced input for if/when a
deterioration term is wired in.

- **Battery, 1.5 %/year** — NREL, *Battery Lifespan*.
  https://www2.nrel.gov/transportation/battery-lifespan
