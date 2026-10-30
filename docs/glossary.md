# Glossary

This page gives the meaning of each technical term that the pages of this site use. Each term
has one definition, and all pages use the term with this meaning.

| Term | Meaning |
|---|---|
| Anchor | A set of cost coefficients for one cost key and one investment year. When BOA builds the frontier cache, it uses the anchors to select the patches. Thus the anchors decide which designs the frontier cache contains. The stored dispatch results contain no cost. |
| Baseload demand | A constant electricity demand: the same power in each hour of the year. |
| Battery factor | The energy capacity of the battery divided by the demand, in hours of demand. |
| CAPEX | Capital expenditure: the cost to install one unit of a technology in an investment year. The cost set gives it for each technology, cost key and year. |
| Capacity ceiling | The largest solar and wind capacity that the available land of a pixel can hold. BOA can calculate it, but it does not apply it when it selects a design. Each output file records `capacity_ceiling_applied = 0`. |
| Capacity factor | The power that 1 MW of installed solar or wind capacity gives in one hour, as a fraction of 1 MW. |
| Coarse grid | A grid of 25 × 25 pairs of solar and wind factors over the search box of a pixel. On this grid, BOA calculates only a lower limit of the smallest battery that meets the coverage target. It uses these limits to select the patches. |
| Containment check | A check that BOA does for each result: is a lower limit of the LCOE in each coarse-grid cell outside the patches at or above the result? The output files do not record the result of this check. |
| Cost coefficients | The four numbers `a_s`, `a_w`, `a_b` and `d0` that BOA calculates from the costs of one cost key in one investment year. With them, the LCOE of a design is a short formula (see [Overview](overview.md)). |
| Cost key | The country (ISO 3166-1 alpha-3 code, for example `DEU`) or the province (for example `CHN:CN-GS`) whose costs BOA uses for a pixel. When the cost set has no costs for the province, BOA uses the costs of the country. When it has no costs for the country, BOA uses the mean costs of all cost keys in the cost set. |
| Cost of capital | The discount rate that BOA applies to the costs and to the delivered energy. The cost set gives one value for each country. A province uses the value of its country. A country with no value in the cost set uses the highest value of all countries in it. |
| Cost set | One set of cost data: CAPEX for each technology, cost key and year, and OPEX and cost of capital for each cost key. |
| Coverage | The fraction of the hours of the weather year in which the system supplies the full demand. |
| Coverage target | The lowest coverage that a design must have. A fraction larger than 0 and smaller than 1. |
| Curtailment | Surplus solar and wind energy that the battery cannot take, because it is full. This energy is lost. |
| Design | One system, given as three numbers: the solar factor, the wind factor and the battery factor. |
| Dispatch | The hour-by-hour simulation of generation, battery charge and supplied demand for one design. |
| Frontier | The set of designs in which the battery is the smallest battery that meets the coverage target, for the solar and wind factors of the design. BOA calculates the frontier only in the patches. |
| Frontier cache | The stored results of the search for the pixels of one region: the patch designs with their coverage and served fraction, the coarse-grid limits, and a status code for each pixel. One cache is for one weather year, region, coverage target and set of search settings. It contains no cost. |
| Investment horizon | The number of years over which BOA calculates the LCOE: the longest technology lifetime. |
| Investment year | The year in which the system is built. It sets the CAPEX that BOA uses. |
| LCOE | Levelised cost of electricity: the discounted cost of the system divided by the discounted energy that the system delivers to the demand, in USD per MWh. |
| Load density | The demand for each km² of pixel area, in MW/km². The pixel area is the full area of the grid cell, land and water. Multiplied by the pixel area, the load density gives the demand of the pixel. |
| OPEX | Operating expenditure: the yearly operating cost of a technology. The cost set gives it as a fraction of the CAPEX. |
| Overscale factor | The solar factor or the wind factor: installed capacity divided by the demand. |
| Patch | A fine grid of solar and wind factors around a low-cost cell of the coarse grid. At each point of a patch, BOA finds the smallest battery that meets the coverage target. Only the patch designs go into the frontier cache. |
| Per-year file | The GLOBAL NetCDF file with the results of all modelled pixels for one investment year. |
| Pixel | One cell of the ERA5 weather grid, 0.25 degrees in latitude and in longitude. BOA models a pixel when the ERA5 land-sea mask is more than 0.5 (land). |
| Promoted LCOE file | One NetCDF file with the LCOE and the status of all investment years of a run. See [The promoted LCOE file](promoted-lcoe-file.md). |
| Region | A rectangle of latitude and longitude that BOA builds and prices as one unit. Together, the regions cover most land between about 58° S and 72° N. |
| Search box | The range of solar and wind factors that the search examines for one pixel. BOA sets it from the mean capacity factors of the pixel. |
| Search settings | The parameters of the search (`SearchParams`): grid sizes, tolerances, the search box and the battery limit. They are not physical parameters. A change to one of them makes a different frontier cache. |
| Served fraction | The fraction of the annual demand energy that the system supplies. |
| Status code | A number for each pixel that tells whether BOA found a result, and if not, why. The [Overview](overview.md) gives the meaning of the codes. |
| Weather year | The calendar year of the hourly capacity factors that BOA uses. |
