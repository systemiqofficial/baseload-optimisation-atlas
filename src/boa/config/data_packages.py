"""
Published input data on steelo-data: the packages BOA downloads, pinned by version and sha256.

A published version is never overwritten, so changing a package means uploading a new
version and pinning it here.
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
COST_DATA_SHA256 = "b9f83cd19a56c20e3f4cbe1ae1812b6fefeb29eaafc47f17fcbdb49cf4cb7faa"
COST_DATA_WORKBOOK = f"boa-cost-data-v{COST_DATA_VERSION}.xlsx"
