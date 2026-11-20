"""
Exogenous, real-world inputs: technology lifetimes, degradation and cost-scaling factors,
land-cover densities, weather/geography constants. Every value here is either cited to a
source or explicitly flagged as a team ballpark -- none of it is a search-tuning knob.

Tunable algorithm parameters (search box sizing, grid resolution, battery rungs, anchor
tolerance) live in `boa.model.bisection.SearchParams` instead, not here -- that dataclass is
hashed into the frontier cache path, so it is the single place a change there is guaranteed
to force a rebuild rather than silently reuse an incompatible store.
"""

# ===== Baseload power simulation parameters =====
# Lifetime of technologies in years (note: years must be a positive integer)
LIFETIMES = {
    "solar": 25,  # IEA: 25-30 years (see README.md)
    "wind": 25,  # IRENA, p.20; other sources say 20 years (see README.md)
    "battery": 25,  # Aligned with solar/wind so no tech reinstalls within the investment horizon
}

# Learning rates for solar and wind technologies
# NOTE: currently unused in the model (already included in the input data in capex projections)
LEARNING_RATES = {
    "solar": 0.234,
    "wind": 0.146,
}

# Scaling factor for batteries: Used in the transformed capex scaling factor equation to account for modules with
# several units being installed at once being cheaper than many single units
BATTERY_UNIT_CAPEX_SCALING_FACTOR = -0.15

# Deterioration rate of the energy systems over their lifetime. Not read anywhere in the LCOE
# calculation today -- lcoe_coefficients and calculate_lcoe_of_re_installation_vectorised
# (cost_calculations.py) have no deterioration term, live or dead. Kept as a sourced input
# for if/when that term gets wired in, rather than re-deriving the numbers from scratch.
YEARLY_DETERIORATION_RATES = {
    "solar": 0.005,  # 0.5%/year
    "wind": 0.01,  # 1%/year
    "battery": 0.015,  # 1.5%/year; batteries degrade faster (NREL, see README.md)
}

# ===== Capacity-ceiling parameters (boa_cds max-capacity) =====
# ceiling(tech) = pixel_area x CAPACITY_DENSITY_MW_PER_KM2[tech] x availability(tech), where
# availability is the ESA-CCI land-cover fraction (LULC_CODES) times the CDS exclusion mask.
#
# Every value comes from one paper, so the densities and the land-cover factors are consistent
# with each other: Deng et al. (2015), registered as DENG_2015 in boa/config/sources.toml.
DENG_2015 = "deng-2015-realistic-wind-solar"

# MW per km2 of available land. Overridden per run via --pv-density / --wind-density.
# pv: the top of Deng's "typical power densities of solar farms (25-50 MW/km2)", which matches
# the "high" availability case below. wind: Deng's density D.
CAPACITY_DENSITY_MW_PER_KM2 = {"pv": 50.0, "wind": 7.0}
CAPACITY_DENSITY_SOURCE = {"pv": f"{DENG_2015}: Footnote 2", "wind": f"{DENG_2015}: Section 2.2.2"}

# Deng Table 2 has the cases Low, Medium and High, and splits High into industrialised and
# developing countries. Neither the paper nor its supplementary information gives a reason
# or a country list for that split, so BOA applies the High/industrialised column to every
# country and calls it "high". It is the top of the range the paper states a basis for
# (3-10 % for wind on land).
AVAILABILITY_CASE = "high"
AVAILABILITY_SOURCE = f"{DENG_2015}: Table 2"
DENG_AVAILABILITY = {
    "pv": {"agriculture": 0.02, "grassland": 0.03, "barren": 0.03, "desert": 0.08},
    "wind": {"forest": 0.02, "agriculture": 0.10, "grassland": 0.10, "barren": 0.10, "desert": 0.10},
}

# ESA-CCI LCCS class -> Deng land class. A BOA judgement, not part of Deng: Deng uses the USGS
# GLCC map, whose legend has no "desert" class either. Unlisted classes get 0 for both
# technologies, as Deng excludes them: urban (190), wetland (160-180), water (210), snow and
# ice (220), no data (0). Forest and the tree mosaics (100, 110) have no PV entry, because Deng
# excludes forest for PV "including mixed land covers".
ESA_CCI_TO_DENG_CLASS = {
    **dict.fromkeys((10, 11, 12, 20, 30, 40), "agriculture"),  # cropland and cropland mosaics
    **dict.fromkeys((50, 60, 61, 62, 70, 71, 72, 80, 81, 82, 90), "forest"),  # tree cover
    **dict.fromkeys((100, 110), "forest"),  # tree/shrub and herbaceous mosaics
    **dict.fromkeys((120, 121, 122, 130), "grassland"),  # shrubland and grassland
    **dict.fromkeys((140, 150, 151, 152, 153), "barren"),  # lichens and mosses, sparse vegetation
    **dict.fromkeys((200, 201, 202), "desert"),  # bare areas
}

# ESA-CCI LCCS class -> available fraction, per technology. Unlisted classes get 0.
LULC_CODES = {
    tech: {code: factors[cls] for code, cls in ESA_CCI_TO_DENG_CLASS.items() if cls in factors}
    for tech, factors in DENG_AVAILABILITY.items()
}

# ===== Copernicus data parameters =====
# ERA5 weather data constants
ERA5_DATA_RESOLUTION = 0.25  # degrees
ERA5_DATA_YEAR = 2024
# Coordinates; [max_lat, min_lon, min_lat, max_lon] = [north, west, south, east]
#
# Deliberately excludes Antarctica (lat < -60) and the high Arctic (lat > 72, the ceiling
# every region caps out at) -- no plant siting candidate there. Adjacent boxes are offset by
# one grid cell (ERA5_DATA_RESOLUTION) rather than touching exactly, so no land cell is
# double-built/double-queried. HAWAII, GALAPAGOS, MASCARENE and KERGUELEN are small dedicated
# boxes for inhabited islands that fall in the longitude gap between two continental boxes --
# cheaper than stretching a continental box across an ocean to reach them. The four largest
# boxes are each split into a point-balanced west/east pair on a real geographic line, since
# build-cache only persists a region once every one of its points has finished (no incremental
# write within a region) -- a smaller box bounds how much work a mid-build crash can lose.
REGION_COORDS = {
    "INDO_AUS": [5.0, 93.0, -50.0, 180.0],
    "SUB_SAHARAN_AFRICA": [3.0, 7.0, -37.0, 52.0],
    "ALASKA": [72.0, -170.0, 42.0, -110.25],
    "CANADA": [72.0, -110.0, 42.0, -50.0],
    "NORTH_AMERICA": [41.75, -128.0, 8.0, -50.0],
    "SOUTH_AMERICA": [7.75, -85.0, -58.0, -33.0],
    "NORTH_AFRICA": [34.75, -20.0, 3.25, 19.75],
    "MIDDLE_EAST": [34.75, 20.0, 3.25, 62.0],
    "EUROPE": [72.0, -25.0, 35.0, 62.0],
    "NORTH_ASIA_WEST": [72.0, 62.25, 50.0, 109.75],
    "NORTH_ASIA_EAST": [72.0, 110.0, 50.0, 180.0],
    "SOUTH_ASIA": [49.75, 62.25, 5.25, 94.75],
    "EAST_ASIA": [49.75, 95.0, 5.25, 151.0],
    "HAWAII": [22.5, -160.0, 18.75, -154.5],
    "GALAPAGOS": [0.25, -92.0, -1.5, -89.5],
    "MASCARENE": [-19.75, 55.0, -21.75, 58.25],
    "KERGUELEN": [-48.75, 68.5, -50.0, 70.75],
}
