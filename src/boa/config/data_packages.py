"""
Published input data on steelo-data: the zips BOA downloads, each pinned by its sha256.

The core and cost data are versioned; the capacity factors have one zip per weather year. A
published zip is never overwritten, so a change means uploading a new one and pinning it here.
"""

STEELO_DATA_URL = "https://steelo-data.s3.eu-north-1.amazonaws.com/boa-standalone-input-data"

# Static geo inputs (Natural Earth shapefiles, ERA5 land-sea mask), unzipped into <root>/data/
# by boa-data-prepare. Built by scripts/package_core.sh.
CORE_DATA_VERSION = "0.1"
CORE_DATA_URL = f"{STEELO_DATA_URL}/boa-core-data-v{CORE_DATA_VERSION}.zip"
CORE_DATA_SHA256 = "eb236ce9f2231a0fc413ccb78d07cab789a0a1835da3b6ad1083ddff66a94b59"
# The package's provenance JSON; its "version" records which package is installed.
CORE_DATA_MARKER = "boa-core-data.json"

# The default cost workbook plus its boa-cost-data.json, used by boa-data-prepare when
# --input-file is not given. Built by scripts/package_cost.sh.
COST_DATA_VERSION = "0.1"
COST_DATA_URL = f"{STEELO_DATA_URL}/boa-cost-data-v{COST_DATA_VERSION}.zip"
COST_DATA_SHA256 = "d80f64f2ae8f9af41cdeff38671848ee0161e9211eb20c2a11d64e615b378fe2"
COST_DATA_WORKBOOK = f"boa-cost-data-v{COST_DATA_VERSION}.xlsx"

# Capacity factors re-published per weather year, so a published year needs no CDS account.
# Downloading with your own CDS account is preferred; these are the fallback behind
# boa-cds-prepare --use-republished. Each zip holds the year's two extracted CDS folders plus a
# provenance JSON carrying the Copernicus attribution. Built by scripts/package_year.sh.
PUBLISHED_CF_SHA256 = {
    2020: "b58cb1c97d6f0d52c96a1647b284ba26de05d17070588d3cb4d1648cf7804c28",
    2021: "5ba1d9d58fe878a33807b4ce9c39e55e6dc491e3bcbe422d162cedc2c1e46ce2",
    2022: "12519ecefff143e169a82207e76ecde6ada100d33e1bf83c9e1e67430f40af16",
    2023: "546e8edabdd00ccc29016542299c9b2f0751fefee555595b2989333f17ef5216",
    2024: "ea0ff1eddba1948604a2ce2a3efa59f248b7f6d3703fb07442c49cfce330e6dd",
    2025: "c7a563830ac1482cf89df7bc11d513848b7207345f1cd252b2f7fa48d331d8a5",
}


def published_cf_url(year: int) -> str:
    """URL of one year's re-published capacity-factor zip."""
    return f"{STEELO_DATA_URL}/cds-capacity-factors-{year}.zip"
