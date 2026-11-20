# Model assumptions

This page gives every value in the module
[physical_parameters][boa.config.physical_parameters] with its unit and its source, and it tells
which of these values change the LCOE. It also gives the battery CAPEX correction, which is a
physical assumption of the cost model. The names in code text on this page are the names in that
module.

The values on this page are physical parameters. They are not search settings. The search
settings (grid resolution, battery rungs, anchor tolerance) are the fields of
[`SearchParams`][boa.model.bisection.SearchParams]. They are in the
[table of search settings](methodology.md#search-settings) on the Methodology page.

Where the code gives no source for a value, this page says "no source". Where the code says that
a value is a team estimate, this page says "team estimate". For the IEA, IRENA and NREL sources,
the code names only the organisation (and page 20 for IRENA). The titles, years and links on this
page are the references of this site for those sources.

## Which values change the LCOE

| Group | Values | Effect on the LCOE |
|---|---|---|
| Technology lifetimes | `LIFETIMES` | Yes. They set the investment horizon and the cost weights. |
| Battery CAPEX correction | `BATTERY_UNIT_CAPEX_SCALING_FACTOR` | Yes. It sets the battery cost. |
| Learning rates | `LEARNING_RATES` | No. The code does not read them. |
| Deterioration rates | `YEARLY_DETERIORATION_RATES` | No. The code does not read them. |
| Land-use densities and land availability | `CAPACITY_DENSITY_MW_PER_KM2`, `DENG_AVAILABILITY`, `ESA_CCI_TO_DENG_CLASS`, `LULC_CODES` | No. They set the capacity ceiling, which limits the capacity potential, not the design (see [Known limitations](known-limitations.md#capacity-ceiling-and-potential)). |
| Weather grid and regions | `ERA5_DATA_RESOLUTION`, `ERA5_DATA_YEAR`, `REGION_COORDS` | Yes, indirectly: they select the weather data and the pixels. |

The LCOE also uses the CAPEX, the OPEX and the cost of capital of the cost set. These are
inputs, not values in the module `physical_parameters`. See [Cost data](cost-data.md).

## Technology lifetimes

`LIFETIMES`, in years. A comment in the code says that each value must be a positive integer.
No code checks this.

| Technology | Value (years) | Source |
|---|---|---|
| Solar | 25 | IEA, *The world needs more diverse solar panel supply chains*, 2022. It gives 25 to 30 years. [Link](https://www.iea.org/news/the-world-needs-more-diverse-solar-panel-supply-chains-to-ensure-a-secure-transition-to-net-zero-emissions) |
| Wind | 25 | IRENA, *Leveraging Local Capacity for Onshore Wind*, Executive Summary, 2017, p. 20. Other sources give 20 years. [Link](https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2017/Jun/IRENA_Leveraging_for_Onshore_Wind_Executive_Summary_2017.pdf) |
| Battery | 25 | No outside source. The value is the same as for solar and wind, so that no technology is installed again within the investment horizon. |

The investment horizon is the largest of the three lifetimes: 25 years. The LCOE is the discounted
cost over the horizon divided by the discounted energy over the horizon. Each technology has a
CAPEX in year 0 and an OPEX in each year of its lifetime. Because all lifetimes are equal to the
horizon, the LCOE contains no replacement cost and no salvage value.

BOA records the lifetimes in the run manifest and uses them in the hash of the run directory
name. A changed lifetime gives a new run directory.

## Battery CAPEX correction

`BATTERY_UNIT_CAPEX_SCALING_FACTOR` = −0.15 (no unit).

**Source:** no source.

The factor makes the cost of one MWh of battery depend on the duration of the battery:

- The battery factor `b` is the battery energy capacity in hours of demand (installed MWh divided
  by the baseload demand in MW).
- The battery CAPEX per MWh is the CAPEX of the cost set multiplied by `(b / 4 h)^−0.15`.
- The cost set gives the battery CAPEX in USD/kWh. BOA converts it to USD/MWh. The correction is
  1 for a battery of 4 hours of demand. Thus BOA takes the battery CAPEX of the cost set as the
  price per MWh of a battery with a duration of 4 hours. The 4 hours are the constant
  `AVERAGE_IMPLIED_STORAGE`.
- The total battery cost is the battery CAPEX per MWh multiplied by the installed MWh. With
  `GAMMA = 1 + BATTERY_UNIT_CAPEX_SCALING_FACTOR = 0.85`, the total battery cost is proportional
  to `b^0.85`. If `b` doubles, the battery cost is 2^0.85, which is about 1.80 times, not 2 times.

| Battery duration `b` (hours of demand) | Factor on the CAPEX per MWh |
|---|---|
| 1 | 1.23 |
| 4 | 1.00 |
| 8 | 0.90 |
| 24 | 0.76 |

The correction depends only on the duration `b`, not on the size of the demand. A battery of the
same duration has the same cost per MWh for a demand of 1 MW and for a demand of 1 000 000 MW.
The correction has no lower limit and no upper limit on `b`. `GAMMA` appears in the cost formula
on the [Methodology](methodology.md#the-optimisation-problem) page.

## Learning rates

`LEARNING_RATES`, as fractions: solar 0.234, wind 0.146.

**Source:** no source in the code.

The model does not use these values. The CAPEX projections in the cost set already contain the
cost reduction over time, and BOA applies no learning curve.

## Deterioration rates

`YEARLY_DETERIORATION_RATES`, as fractions per year.

| Technology | Value (per year) | Source |
|---|---|---|
| Solar | 0.005 (0.5 %) | No source |
| Wind | 0.010 (1 %) | No source |
| Battery | 0.015 (1.5 %) | NREL, *Battery Lifespan*. [Link](https://www2.nrel.gov/transportation/battery-lifespan) |

The LCOE calculation does not read these values. The energy of a system is the same in each year
of the horizon, and the battery capacity does not decrease. See
[Known limitations](known-limitations.md).

## Capacity ceiling parameters

These values set the capacity ceiling of a pixel: the largest solar and wind capacity that the
land of the pixel can hold. The ceiling is the pixel area multiplied by the density and by the
land-availability fraction. The ceiling sets the capacity potential, not the design or the LCOE
(see [Known limitations](known-limitations.md#capacity-ceiling-and-potential)).

All densities and fractions come from one source, so they are consistent with each other:
Deng, Y.Y. et al. (2015), *Quantifying a realistic, worldwide wind and solar electricity supply*,
Global Environmental Change 31: 239–252,
[doi:10.1016/j.gloenvcha.2015.01.005](https://doi.org/10.1016/j.gloenvcha.2015.01.005). The source
registry `src/boa/config/sources.toml` pins the file with the id `deng-2015-realistic-wind-solar`
and the tag `capacity-ceiling`. `boa-sources-fetch --tag capacity-ceiling` downloads it.

The pixel area (`pixel_area` in `boa.cds.max_capacity`) is not the exact area of the grid cell on
a sphere. It is the square of the side length of 0.25° of arc on a sphere with a radius of
6371.0 km, multiplied by cos(latitude). The radius is the constant `EARTH_RADIUS_KM` (mean
radius, no source).

### Densities

`CAPACITY_DENSITY_MW_PER_KM2` gives the installed capacity for each km² of available land. The
option `--pv-density` or `--wind-density` of `boa-cds-prepare` replaces it for one build.

| Technology | Density (MW/km²) | Source |
|---|---|---|
| Solar PV | 50 | Deng (2015), footnote 2, p. 243: the top of the range of "typical power densities of solar farms (25–50 MW/km²)". The source does not say if the values are AC or DC. |
| Wind | 7 | Deng (2015), Section 2.2.2, p. 244: the power density `D`. |

### Land-availability fractions

`LULC_CODES` gives, for each technology, the available fraction for each land-cover class of the
ESA-CCI land-cover map. The fraction is the share of the class area that holds solar or wind
plants. It includes the competition with other uses of the land. The fraction has no unit. It
applies to each 300 m ESA-CCI pixel of that class. The value of a 0.25° cell is the mean of these
fractions over the ESA-CCI pixels of the cell
([lulc_fraction][boa.cds.availability.lulc_fraction]). A class that the table does not list has a
fraction of 0, so the ceiling is 0 there.

**Source:** Deng (2015), Table 2, p. 242. The table has three cases (Low, Medium, High) and gives
the High case separately for industrialised and developing countries. Neither the paper nor its
supplementary information gives a reason or a list of countries for this split. BOA uses the High
case for industrialised countries in all countries (`AVAILABILITY_CASE = "high"`). It is the top of
the range of 3 % to 10 % for wind that the paper states a basis for.

Deng uses the land classes of the USGS GLCC map. The table `ESA_CCI_TO_DENG_CLASS` gives each
ESA-CCI class a Deng class. This is a BOA decision, not part of the source: the GLCC map has no
"desert" class either, and BOA uses the bare-area classes for it.

| ESA-CCI classes (code) | Deng class | Solar PV | Wind |
|---|---|---|---|
| Cropland, rainfed (10, 11, 12), irrigated (20), cropland and natural-vegetation mosaics (30, 40) | Agriculture | 0.02 | 0.10 |
| Forest, all types (50, 60, 61, 62, 70, 71, 72, 80, 81, 82, 90) | Forest | 0 (excluded) | 0.02 |
| Tree and shrub, and herbaceous mosaics (100, 110) | Forest | 0 (excluded) | 0.02 |
| Shrubland (120, 121, 122), grassland (130) | Grassland | 0.03 | 0.10 |
| Lichens and mosses (140), sparse vegetation (150, 151, 152, 153) | Barren land | 0.03 | 0.10 |
| Bare areas (200, 201, 202) | Desert | 0.08 | 0.10 |
| Urban (190), wetland (160, 170, 180), water (210), snow and ice (220) | Excluded | 0 | 0 |

Deng excludes forest for solar, "including mixed land covers", so the tree mosaics (100, 110) have
no solar fraction. Deng excludes urban areas, water and ice for all technologies.

These fractions apply only when the build uses the land-cover layer (`--layers lulc`). A build
without layers uses only the pixel area and the density. The other layer (`cds_exclusion`)
multiplies the fraction by 0 in the pixels that the Copernicus exclusion mask excludes (see
[Known limitations](known-limitations.md#capacity-ceiling-and-potential)).

## Weather data parameters

| Name | Value | Unit | Source |
|---|---|---|---|
| `ERA5_DATA_RESOLUTION` | 0.25 | degrees (latitude and longitude) | No source in the code. It is the grid spacing of the ERA5 data that BOA uses. |
| `ERA5_DATA_YEAR` | 2024 | calendar year | No source. It is the default weather year of `boa-cds-prepare`, `boa-cds-download` and `boa-lcoe`. The option `--weather_year` of `boa-cds-prepare` selects another year. |

`boa-run` does not read `ERA5_DATA_YEAR`. Its default weather input is the separate constant
`DEFAULT_WEATHER_INPUT = "cds-2024"` in `boa.cli.run_simulation`. The option
`--weather-input cds-<year>` of `boa-run` runs another year.

### Regions

`REGION_COORDS` gives the rectangle of each region as `[north, west, south, east]`, in degrees.
BOA builds and prices the pixels of a region as one unit. No source: these are boundaries that the
team chose.

| Region | North | West | South | East |
|---|---|---|---|---|
| `ALASKA` | 72.0 | −170.0 | 42.0 | −110.25 |
| `CANADA` | 72.0 | −110.0 | 42.0 | −50.0 |
| `NORTH_AMERICA` | 41.75 | −128.0 | 8.0 | −50.0 |
| `SOUTH_AMERICA` | 7.75 | −85.0 | −58.0 | −33.0 |
| `EUROPE` | 72.0 | −25.0 | 35.0 | 62.0 |
| `NORTH_AFRICA` | 34.75 | −20.0 | 3.25 | 19.75 |
| `MIDDLE_EAST` | 34.75 | 20.0 | 3.25 | 62.0 |
| `SUB_SAHARAN_AFRICA` | 3.0 | 7.0 | −37.0 | 52.0 |
| `NORTH_ASIA_WEST` | 72.0 | 62.25 | 50.0 | 109.75 |
| `NORTH_ASIA_EAST` | 72.0 | 110.0 | 50.0 | 180.0 |
| `SOUTH_ASIA` | 49.75 | 62.25 | 5.25 | 94.75 |
| `EAST_ASIA` | 49.75 | 95.0 | 5.25 | 151.0 |
| `INDO_AUS` | 5.0 | 93.0 | −50.0 | 180.0 |
| `HAWAII` | 22.5 | −160.0 | 18.75 | −154.5 |
| `GALAPAGOS` | 0.25 | −92.0 | −1.5 | −89.5 |
| `MASCARENE` | −19.75 | 55.0 | −21.75 | 58.25 |
| `KERGUELEN` | −48.75 | 68.5 | −50.0 | 70.75 |

- The regions do not cover Antarctica (south of 60° S) or the high Arctic (north of 72° N). The
  southernmost region box reaches 58° S.
- Adjacent boxes are one grid cell (0.25 degrees) apart, so that no land cell is in two boxes.
- `HAWAII`, `GALAPAGOS`, `MASCARENE` and `KERGUELEN` are small boxes for islands that are in a
  longitude gap between two continental boxes.
- Some of the larger boxes are split into a west box and an east box. A region is stored only
  when all its points are done, so a smaller box limits the work that a crash can lose.
- A single-point run for a point outside all boxes uses the nearest box in the same hemisphere
  ([select_region][boa.geo.geospatial.select_region]). See the section "Region extent" on the
  page [Known limitations](known-limitations.md#region-extent).
