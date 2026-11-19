"""
Build the boa-cost-data-core package: one BOA cost workbook per IEA WEO 2025 scenario (CPS, STEPS, NZE).

Every value comes from a pinned file in src/boa/config/cost_sources.toml, and every row names its
source as "<id>: <item ref>". Fetch the files first:

    boa-sources-fetch irena-rpgc-2024-data irena-rpgc-2024-report iea-weo-2025 natural-earth-50m-map-subunits
    python scripts/cost/build_core.py --out-dir <folder>

The build uses three kinds of input, and each kind has its own place:
- transcribed/*.csv: values typed from the PDF sources, in the layout of the source table. Compare them
  with the page that the header names.
- rules.toml: our own decisions, such as which WEO row a region follows.
- The IRENA data file and the Natural Earth file, read by this script. The "Inputs" sheet lists the IRENA
  values; the "Country mapping" sheet names the Natural Earth subregion of each code.

The derivation rules are the first paragraphs of the functions in METHOD. Each workbook has them in its
"Method" sheet, and each derived sheet shows the intermediate values next to the result.
"""

import argparse
import hashlib
import json
import re
import statistics
import sys
import tomllib
import unicodedata
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import openpyxl
import pandas as pd

from boa.cli.fetch_sources import file_sha256
from boa.config.cost_sources import Source, get_source, source_path
from boa.config.paths import default_root
from boa.geo.iso3_grid_builder import NE_TO_BOA

PACKAGE = "boa-cost-data-core"
YEARS = (2024, 2035, 2050)
BASE_YEAR = YEARS[0]
SCENARIOS = ("CPS", "STEPS", "NZE")

IRENA_DATA = "irena-rpgc-2024-data"
IRENA_REPORT = "irena-rpgc-2024-report"
WEO = "iea-weo-2025"
NATURAL_EARTH = "natural-earth-50m-map-subunits"
INPUTS = (IRENA_DATA, IRENA_REPORT, WEO, NATURAL_EARTH)

HERE = Path(__file__).resolve().parent
TRANSCRIBED = HERE / "transcribed"
RULES_PATH = HERE / "rules.toml"

# IRENA cost-table rows (Tables 2.1, 3.1). The four single-country rows take their countries out of their region.
COST_ROWS = (
    "Africa",
    "Central America and the Caribbean",
    "Eurasia",
    "Europe",
    "Oceania",
    "Other Asia",
    "Other North America",
    "Other South America",
    "Brazil",
    "China",
    "India",
    "United States",
)
MIDDLE_EAST = "Middle East"  # in Annex III, but IRENA publishes no cost row for it
REGIONS = (*COST_ROWS, MIDDLE_EAST)
TECHS = {
    "solar": ("Solar PV", "USD/kW", "Table 3.1"),
    "wind": ("Onshore wind", "USD/kW", "Table 2.1"),
    "battery": ("Battery", "USD/kWh", None),
}
# Natural Earth name fields that the IRENA names are matched against. ADMIN (the admin-0 country name)
# counts only where ADM0_A3 is the code: French Guiana has ADMIN "France" but ADM0_A3 "FRA".
NE_NAME_FIELDS = ("NAME", "NAME_LONG", "FORMAL_EN", "NAME_ALT", "NAME_SORT", "GEOUNIT", "SUBUNIT")
OPEN_OCEAN = "Seven seas (open ocean)"


# --- transcribed tables and rules -----------------------------------------------------------------


def _transcribed(name: str) -> pd.DataFrame:
    return pd.read_csv(TRANSCRIBED / name, comment="#", dtype=str, keep_default_na=False)


def _years(row: pd.Series) -> tuple[int, ...]:
    return tuple(int(row[str(year)]) for year in YEARS)


_b4 = _transcribed("iea-weo-2025_table-b4.csv")
_WEO_TECH = {"Solar PV": "solar", "Wind onshore": "wind"}
WEO_TABLE = dict(zip(_b4["scenario"], _b4["table"]))
WEO_CAPEX: dict[str, dict[str, dict[str, tuple[int, ...]]]] = {}
for _, _r in _b4.iterrows():
    WEO_CAPEX.setdefault(_r["scenario"], {}).setdefault(_r["region"], {})[_WEO_TECH[_r["tech"]]] = _years(_r)
WEO_BATTERY = {r["scenario"]: _years(r) for _, r in _transcribed("iea-weo-2025_table-b5.csv").iterrows()}
ANNEX_III: dict[str, tuple[str, ...]] = {}
for _, _r in _transcribed("irena-rpgc-2024-report_annex-iii.csv").iterrows():
    ANNEX_III[_r["annex region"]] = (*ANNEX_III.get(_r["annex region"], ()), _r["country"])
TABLE_A1_DEFAULTS = tuple(float(v) for v in _transcribed("irena-rpgc-2024-report_table-a1.csv")["wacc"])

with RULES_PATH.open("rb") as _f:
    RULES = tomllib.load(_f)
WEO_REGION_OF: dict[str, str] = RULES["weo_row_of_region"]
OECD_REGIONS = set(RULES["oecd"]["regions"])
SINGLE_COUNTRY_ROWS: dict[str, str] = RULES["single_country_rows"]
SPLIT_REGIONS: dict[str, str] = RULES["split_regions"]
NAME_ALIASES: dict[str, str] = RULES["name_aliases"]
SUBREGION_REGIONS: dict[str, str] = RULES["subregion_regions"]
REGION_UN_REGIONS: dict[str, str] = RULES["region_un_regions"]
NO_REGION: str = RULES["no_region"]["name"]


def check_rules() -> None:
    """Raise ValueError if rules.toml or a transcribed table names a region or row that the build does not know."""
    errors = []
    region_rules = {
        "weo_row_of_region": set(WEO_REGION_OF),
        "oecd": OECD_REGIONS,
        "single_country_rows": set(SINGLE_COUNTRY_ROWS.values()),
        "split_regions": set(SPLIT_REGIONS.values()),
        "subregion_regions": set(SUBREGION_REGIONS.values()),
        "region_un_regions": set(REGION_UN_REGIONS.values()),
    }
    for table, names in region_rules.items():
        if unknown := sorted(names - set(REGIONS)):
            errors.append(f"rules.toml [{table}]: not an IRENA cost region: {unknown}")
    for scenario in SCENARIOS:
        if set(WEO_CAPEX.get(scenario, {})) != set(WEO_REGION_OF.values()):
            errors.append(f"Table B.4 {scenario}: the rows are not the rows of [weo_row_of_region]")
    if set(WEO_BATTERY) != set(SCENARIOS):
        errors.append("Table B.5: not one row per scenario")
    if unknown := sorted(set(ANNEX_III) - set(REGIONS) - set(SPLIT_REGIONS)):
        errors.append(f"Annex III: regions that are not cost regions and not split: {unknown}")
    if errors:
        raise ValueError("\n".join(errors))


# --- inputs -------------------------------------------------------------------------------------


def label(source_id: str, ref: str) -> str:
    """The workbook source label "<id>: <ref>". Raises KeyError if the registry has no such item."""
    return get_source(source_id).label(ref)


def input_path(root: Path, source: Source) -> Path:
    """The pinned file of ``source`` under ``root``, after a sha256 check."""
    path = source_path(root, source)
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing. Run: boa-sources-fetch {source.id}")
    if (digest := file_sha256(path)) != source.sha256:
        raise ValueError(
            f"{path}: sha256 {digest} is not the pinned {source.sha256}. Run: boa-sources-fetch {source.id}"
        )
    return path


def _fix_text(name: object) -> str:
    """The name with UTF-8 text that was decoded as cp1252 ("CÃ´te d'Ivoire") repaired."""
    name = str(name).replace("’", "'")
    if "Ã" in name:
        try:
            return name.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def norm(name: object) -> str:
    """Lower-case, accent-free name without brackets or punctuation, aliased to the country list's spelling."""
    text = unicodedata.normalize("NFKD", _fix_text(name)).encode("ascii", "ignore").decode().casefold()
    text = re.sub(r"\(the\)|\bthe\b", " ", text.replace("&", " and "))
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return NAME_ALIASES.get(text, text)


def _num(cell: object) -> float:
    """A number from an IRENA cell, which can be text with thin or non-breaking spaces ('1 093')."""
    if isinstance(cell, (int, float)):
        return float(cell)
    return float(re.sub(r"[\s  ]", "", str(cell)))


def _table(book: openpyxl.Workbook, sheet: str) -> list[list]:
    """The sheet's non-empty rows with empty cells dropped."""
    rows = ([c for c in row if c is not None] for row in book[sheet].iter_rows(values_only=True))
    return [row for row in rows if row]


def _row(table: list[list], label_text: str) -> list:
    """The cells after ``label_text`` in the first row that starts with it."""
    for row in table:
        if str(row[0]).strip().startswith(label_text):
            return row[1:]
    raise KeyError(f"No row starting with {label_text!r}")


def read_country_list(path: Path) -> pd.DataFrame:
    """
    Countries: one row for each ISO-3 code of the Natural Earth 1:50m map subunits, by the rule of the BOA
    ISO-3 grid (ISO_A3, else ADM0_A3, remapped by NE_TO_BOA). A code takes its names, SUBREGION and
    SOVEREIGNT from its own subunits (ISO_A3 equal to the code) if it has any. A code with no own
    subunits takes its country name from ADMIN, not from one of its subunits.
    """
    ne = gpd.read_file(path, ignore_geometry=True)
    iso3 = ne["ISO_A3"].astype(str)
    ne["code"] = iso3.where(iso3 != "-99", ne["ADM0_A3"].astype(str)).replace(NE_TO_BOA)
    ne["own"] = ne["ISO_A3"].astype(str) == ne["code"]
    ne = ne[ne["code"].str.len() == 3]
    rows = []
    for code, group in ne.groupby("code", sort=True):
        own = group[group["own"]]
        home = own if not own.empty else group
        names = {str(v) for field in NE_NAME_FIELDS for v in home[field].dropna() if str(v).strip()}
        admin = group.loc[group["ADM0_A3"].astype(str).replace(NE_TO_BOA) == code, "ADMIN"].dropna()
        names |= set(admin)
        first = home.iloc[0]
        # Without own subunits, NAME_LONG is the name of a part (USA "Alaska", GBR "Wales").
        country = first["NAME_LONG"] if not own.empty or admin.empty else admin.iloc[0]
        rows.append(
            {
                "code": code,
                "country": country,
                "names": sorted(names),
                "subregion": first["SUBREGION"],
                "region_un": first["REGION_UN"],
                "sovereign": first["SOVEREIGNT"],
            }
        )
    return pd.DataFrame(rows)


# --- countries ----------------------------------------------------------------------------------


def name_index(country_list: pd.DataFrame) -> dict[str, str]:
    """Normalised name -> ISO-3 code, for every name that belongs to one code only."""
    codes_of: dict[str, set[str]] = {}
    for code, names in zip(country_list["code"], country_list["names"]):
        for name in names:
            codes_of.setdefault(norm(name), set()).add(code)
    return {name: next(iter(codes)) for name, codes in codes_of.items() if len(codes) == 1}


def subregion_region(rec: dict) -> tuple[str, str]:
    """The IRENA cost region of a code that Annex III does not list, and the rule that gave it."""
    ne = f"{label(NATURAL_EARTH, 'SUBREGION')} {rec['subregion']!r}"
    if rec["sovereign"] == "China":
        return "China", f"{label(NATURAL_EARTH, 'SOVEREIGNT')} 'China'"
    if rec["subregion"] == OPEN_OCEAN:
        return REGION_UN_REGIONS[rec["region_un"]], f"{ne}, REGION_UN {rec['region_un']!r}"
    return SUBREGION_REGIONS[rec["subregion"]], ne


def build_mapping(country_list: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Regions: a country in IRENA Annex III takes its Annex III region, or its single-country row (China,
    India, Brazil, United States), or the "Other ..." row of a split region. Any other code takes its
    region from its Natural Earth SUBREGION; a territory of China takes China, and a code in "Seven seas
    (open ocean)" uses its REGION_UN. Antarctica has no cost row.

    Returns the mapping and the normalised-name -> ISO-3 index, which the WACC lookup uses again.
    """
    index = name_index(country_list)
    region_of: dict[str, str] = {}
    unmatched = []
    for annex_region, names in ANNEX_III.items():
        for name in names:
            code = index.get(norm(name))
            if code is None:
                unmatched.append(name)
                continue
            region_of[code] = SINGLE_COUNTRY_ROWS.get(code, SPLIT_REGIONS.get(annex_region, annex_region))
    if unmatched:
        raise ValueError(f"Annex III names with no single Natural Earth match: {unmatched}")
    annex = label(IRENA_REPORT, "Annex III")
    rows = []
    for rec in country_list.to_dict("records"):
        if NO_REGION in (rec["subregion"], rec["region_un"]):
            print(f"{rec['code']} ({rec['country']}): Antarctic, no cost row")
            continue
        if rec["code"] in region_of:
            region, src = region_of[rec["code"]], annex
        else:
            region, rule = subregion_region(rec)
            src = f"not in {annex}; {rule}"
        rows.append({"country": rec["country"], "code": rec["code"], "irena region": region, "source": src})
    return pd.DataFrame(rows), index


# --- CAPEX --------------------------------------------------------------------------------------


def irena_capex(book: openpyxl.Workbook) -> dict[str, dict[str, float]]:
    """
    CAPEX 2024: IRENA Tables 3.1 (solar PV) and 2.1 (onshore wind), the 2024 weighted average of each
    cost row. The Middle East has no IRENA cost row and takes the global weighted average (Table S.1).
    """
    glob = _table(book, "Table S.1")
    out = {}
    for tech, sheet, glob_label in (("solar", "Table 3.1", "Solar PV"), ("wind", "Table 2.1", "Onshore wind")):
        table = _table(book, sheet)
        # Each row is [5th, average, 95th] for 2010, then for 2024: the 2024 average is the 5th cell.
        out[tech] = {region: _num(_row(table, region)[4]) for region in COST_ROWS}
        out[tech][MIDDLE_EAST] = _num(_row(glob, glob_label)[1])
    return out


def weo_change(scenario: str, tech: str, region: str) -> tuple[tuple[float, ...], str]:
    """
    CAPEX 2035 and 2050: the 2024 value times the change from 2024 in WEO 2025 Table B.4 of the same
    scenario. United States, Europe (EU row), China and India follow their own row; every other region
    follows the mean change of the four rows.

    Returns the change for YEARS and the path's description.
    """
    rows = WEO_CAPEX[scenario]
    if (weo_region := WEO_REGION_OF.get(region)) is not None:
        values = rows[weo_region][tech]
        return tuple(v / values[0] for v in values), f"{weo_region} change"
    changes = [tuple(v / r[tech][0] for v in r[tech]) for r in rows.values()]
    return tuple(statistics.fmean(c[i] for c in changes) for i in range(len(YEARS))), "mean change of its 4 regions"


def battery_capex(scenario: str) -> tuple[int, ...]:
    """Battery CAPEX: WEO 2025 Table B.5 (global) of the scenario, in every region."""
    return WEO_BATTERY[scenario]


def build_capex(book: openpyxl.Workbook, scenario: str) -> pd.DataFrame:
    """CAPEX rows for YEARS, with the WEO change factors that give 2035 and 2050 from 2024."""
    base = irena_capex(book)
    weo = label(WEO, WEO_TABLE[scenario])
    rows = []
    for tech, (tech_label, unit, irena_table) in TECHS.items():
        for region in REGIONS:
            row = {"irena region": region, "tech": tech_label, "unit": f"2024 {unit}"}
            if tech == "battery":
                values = battery_capex(scenario)
                row |= {year: float(value) for year, value in zip(YEARS, values)}
                row["source"] = f"{label(WEO, 'Table B.5')} (global)"
            else:
                change, path = weo_change(scenario, tech, region)
                values = tuple(base[tech][region] * c for c in change)
                level = label(IRENA_DATA, "Table S.1" if region == MIDDLE_EAST else irena_table)
                row |= {year: round(value, 2) for year, value in zip(YEARS, values)}
                row |= {f"change {year}": round(c, 6) for year, c in zip(YEARS[1:], change[1:])}
                row["source"] = f"2024: {level}; 2035, 2050: x {weo} {path}"
            rows.append(row)
    columns = ["irena region", "tech", "unit", *YEARS, *(f"change {y}" for y in YEARS[1:]), "source"]
    return pd.DataFrame(rows, columns=columns)


# --- OPEX ---------------------------------------------------------------------------------------


def irena_om(book: openpyxl.Workbook) -> dict[str, float]:
    """IRENA O&M assumptions (USD/kW/year): onshore wind by country (Table A3), solar PV 2024 (Table A4)."""
    wind = {
        str(r[0]).strip(): float(r[1])
        for r in _table(book, "Table A3")
        if len(r) == 2 and isinstance(r[1], (int, float))
    }
    solar_oecd, solar_non_oecd = next(r[1:] for r in _table(book, "Table A4") if len(r) == 3 and str(r[0]) == "2024")
    out = {f"wind_{key}": wind[key] for key in ("Brazil", "China", "India", "United States")}
    out |= {"wind_oecd": wind["Other OECD"], "wind_non_oecd": wind["Other non-OECD"]}
    return out | {"solar_oecd": _num(solar_oecd), "solar_non_oecd": _num(solar_non_oecd)}


# Where each irena_om key comes from: (table, row in the table).
OM_ROWS = {
    "wind_Brazil": ("Table A3", "Brazil"),
    "wind_China": ("Table A3", "China"),
    "wind_India": ("Table A3", "India"),
    "wind_United States": ("Table A3", "United States"),
    "wind_oecd": ("Table A3", "Other OECD"),
    "wind_non_oecd": ("Table A3", "Other non-OECD"),
    "solar_oecd": ("Table A4", "2024 OECD"),
    "solar_non_oecd": ("Table A4", "2024 non-OECD"),
}


def build_opex(book: openpyxl.Workbook, battery_opex: float) -> pd.DataFrame:
    """
    OPEX: IRENA O&M (Table A3 onshore wind, Table A4 solar PV, USD/kW/year) divided by the region's 2024
    CAPEX. OECD regions take the OECD O&M and the others the non-OECD O&M; Brazil, China, India and the
    United States take their own wind O&M. No core source gives battery O&M: the battery row is a placeholder.
    """
    om = irena_om(book)
    base = irena_capex(book)

    def row(region: str, tech: str, key: str, table: str, level: str, capex_ref: str, note: str = "") -> dict:
        capex = base[level][region]
        return {
            "region": region,
            "tech": tech,
            "unit": "fraction of capex per year",
            "opex": round(om[key] / capex, 5),
            "O&M USD/kW/year": om[key],
            "CAPEX 2024 USD/kW": capex,
            "source": f"{label(IRENA_DATA, table)}{note} {om[key]:g} USD/kW/year / {label(IRENA_DATA, capex_ref)}",
        }

    # BOA needs a World row per technology for a country with no regional row. Every mapped country
    # has a regional row, so these are fallbacks only: non-OECD O&M over the global CAPEX.
    rows = [
        row(MIDDLE_EAST, "Solar PV", "solar_non_oecd", "Table A4", "solar", "Table S.1", " non-OECD"),
        row(MIDDLE_EAST, "Onshore wind", "wind_non_oecd", "Table A3", "wind", "Table S.1", " non-OECD"),
    ]
    for r in rows:
        r["region"] = "World"
    rows.append(
        {
            "region": "World",
            "tech": "Battery",
            "unit": "fraction of capex per year",
            "opex": battery_opex,
            "source": "none: placeholder, no core source gives battery O&M",
        }
    )
    for region in REGIONS:
        oecd = "oecd" if region in OECD_REGIONS else "non_oecd"
        wind_key = f"wind_{region}" if f"wind_{region}" in om else f"wind_{oecd}"
        for tech, key, table, level in (
            ("Solar PV", f"solar_{oecd}", "Table A4", "solar"),
            ("Onshore wind", wind_key, "Table A3", "wind"),
        ):
            capex_ref = "Table S.1" if region == MIDDLE_EAST else TECHS[level][2]
            rows.append(row(region, tech, key, table, level, capex_ref))
    columns = ["region", "tech", "unit", "opex", "O&M USD/kW/year", "CAPEX 2024 USD/kW", "source"]
    return pd.DataFrame(rows, columns=columns)


# --- cost of capital ----------------------------------------------------------------------------


def fig_a1_rows(book: openpyxl.Workbook) -> list[tuple[str, float, float]]:
    """(country as IRENA names it, onshore wind, solar PV) real after-tax WACC, in sheet order."""
    return [
        (str(row[0]), float(row[1]), float(row[2]))
        for row in _table(book, "Fig A1")
        if len(row) >= 3 and isinstance(row[1], (int, float)) and isinstance(row[2], (int, float))
    ]


def fig_a1(book: openpyxl.Workbook) -> dict[str, tuple[float, float]]:
    """(onshore wind, solar PV) real after-tax WACC per normalised country name."""
    return {norm(name): (wind, solar) for name, wind, solar in fig_a1_rows(book)}


def is_default(wind: float, solar: float) -> bool:
    """
    True if Fig A1 shows the Table A1 default, not a country's own value.

    A default raised by the Box A.2 minimum WACC floor is specific to its country, so it counts as an own value.
    """
    return wind == solar and any(abs(wind - d) < 1e-12 for d in TABLE_A1_DEFAULTS)


def build_wacc(book: openpyxl.Workbook, mapping: pd.DataFrame, index: dict[str, str]) -> pd.DataFrame:
    """
    Cost of capital: IRENA Fig A1, the mean of the country's onshore wind and solar PV values. A country
    with no own value (Fig A1 shows the Table A1 default, or has no row for it) takes the median of the own
    values in its IRENA cost region. A default raised by the Box A.2 minimum WACC floor counts as an own value.
    """
    own: dict[str, tuple[float, float]] = {}
    for name, (wind, solar) in fig_a1(book).items():
        if name in index and not is_default(wind, solar):
            own[index[name]] = (wind, solar)
    region_of = dict(zip(mapping["code"], mapping["irena region"]))
    by_region: dict[str, list[float]] = {}
    for code, (wind, solar) in own.items():
        by_region.setdefault(region_of[code], []).append((wind + solar) / 2)
    if empty := sorted(set(REGIONS) - set(by_region)):
        raise ValueError(f"No own Fig A1 value in the cost regions {empty}")
    fig = label(IRENA_DATA, "Fig A1")
    rows = []
    for rec in mapping.to_dict("records"):
        row = {"country": rec["country"], "code": rec["code"], "tech": "Renewables"}
        if rec["code"] in own:
            wind, solar = own[rec["code"]]
            row |= {"cost of capital": round((wind + solar) / 2, 5), "Fig A1 onshore wind": wind}
            row |= {"Fig A1 solar PV": solar, "source": f"{fig}, mean of onshore wind and solar PV"}
        else:
            values = by_region[rec["irena region"]]
            row |= {"cost of capital": round(statistics.median(values), 5), "own values in region": len(values)}
            annex = label(IRENA_REPORT, "Annex III")
            row["source"] = f"{fig}, median of the {len(values)} own values in {rec['irena region']} ({annex})"
        rows.append(row)
    columns = [
        "country",
        "code",
        "tech",
        "cost of capital",
        "Fig A1 onshore wind",
        "Fig A1 solar PV",
        "own values in region",
        "source",
    ]
    return pd.DataFrame(rows, columns=columns)


# --- output -------------------------------------------------------------------------------------

YEARS_RULE = (
    "Years: the workbooks have the year columns 2024, 2035 and 2050 only. BOA interpolates linearly "
    "between them and holds the 2050 value for later years."
)
# The derivation, in the order of the Method sheet. A function's rule is the first paragraph of its docstring.
METHOD: tuple[str | Callable, ...] = (
    YEARS_RULE,
    irena_capex,
    weo_change,
    battery_capex,
    build_opex,
    build_wacc,
    read_country_list,
    build_mapping,
)


def rule_text(item: str | Callable) -> tuple[str, str]:
    """(topic, rule) of one METHOD item: the text before and after the first colon of its rule paragraph."""
    text = item if isinstance(item, str) else " ".join(item.__doc__.strip().split("\n\n")[0].split())
    topic, rule = text.split(": ", 1)
    return topic, rule[:1].upper() + rule[1:]


def method_sheet() -> pd.DataFrame:
    return pd.DataFrame([rule_text(item) for item in METHOD], columns=["topic", "rule"])


def inputs_sheet(book: openpyxl.Workbook, scenario: str, mapping: pd.DataFrame, index: dict[str, str]) -> pd.DataFrame:
    """Every source value the workbook uses, as the source gives it: compare these with the source files."""
    rows = []

    def add(source: str, item: str, tech: str, value: float, unit: str, year: object = "", note: str = "") -> None:
        rows.append({"source": source, "item": item, "tech": tech, "year": year, "value": value, "unit": unit})
        rows[-1]["note"] = note

    capex = irena_capex(book)
    for tech in ("solar", "wind"):
        tech_label, unit, table = TECHS[tech]
        for region in COST_ROWS:
            add(label(IRENA_DATA, table), region, tech_label, capex[tech][region], unit, BASE_YEAR)
        add(label(IRENA_DATA, "Table S.1"), "Global", tech_label, capex[tech][MIDDLE_EAST], unit, BASE_YEAR)
    for key, value in irena_om(book).items():
        table, item = OM_ROWS[key]
        tech = "Onshore wind" if key.startswith("wind") else "Solar PV"
        add(label(IRENA_DATA, table), item, tech, value, "USD/kW/year")
    weo_table = WEO_TABLE[scenario]
    for region, techs in WEO_CAPEX[scenario].items():
        for tech, values in techs.items():
            for year, value in zip(YEARS, values):
                add(label(WEO, weo_table), region, TECHS[tech][0], value, "USD(2024)/kW", year, "transcribed")
    for year, value in zip(YEARS, WEO_BATTERY[scenario]):
        add(label(WEO, "Table B.5"), f"Global, {scenario}", "Battery", value, "USD(2024)/kWh", year, "transcribed")
    for group, value in zip(("OECD and China", "Rest of the world"), TABLE_A1_DEFAULTS):
        add(label(IRENA_REPORT, "Table A1"), group, "Renewables", value, "real WACC", "", "transcribed")
    for name, wind, solar in fig_a1_rows(book):
        code = index.get(norm(name))
        if code is None:
            note = "no ISO-3 code of the country list"
        elif is_default(wind, solar):
            note = f"{code}, Table A1 default, not used"
        else:
            note = code
        add(label(IRENA_DATA, "Fig A1"), name, "Onshore wind", wind, "real WACC", BASE_YEAR, note)
        add(label(IRENA_DATA, "Fig A1"), name, "Solar PV", solar, "real WACC", BASE_YEAR, note)
    return pd.DataFrame(rows)


def sources_sheet(scenario: str) -> pd.DataFrame:
    items = [("Package", PACKAGE), ("Scenario", f"IEA WEO 2025 {scenario}"), ("Currency", "2024 USD, real")]
    for source_id in INPUTS:
        source = get_source(source_id)
        items.append((source_id, f"{source.citation} {source.url} (sha256 {source.sha256}; {source.licence})"))
    return pd.DataFrame(items, columns=["item", "value"])


def write_workbook(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    with pd.ExcelWriter(path) as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)


def package_json(version: str, workbooks: dict[str, Path], battery_opex: float) -> dict:
    """The package record: inputs with their sha256, method and each workbook's sha256."""
    return {
        "package": PACKAGE,
        "version": version,
        "packaged_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "usage": "boa-data-prepare --input-file <workbook>",
        "attribution": [get_source(source_id).citation for source_id in INPUTS],
        "licences": {source_id: get_source(source_id).licence for source_id in INPUTS},
        "inputs": {
            source_id: {"url": get_source(source_id).url, "sha256": get_source(source_id).sha256}
            for source_id in INPUTS
        },
        "method": dict(rule_text(item) for item in METHOD) | {"Battery OPEX": f"{battery_opex:g} placeholder"},
        "workbooks": {
            scenario.lower(): {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for scenario, path in workbooks.items()
        },
    }


def build(root: Path, out_dir: Path, version: str, battery_opex: float) -> dict[str, Path]:
    """Write the three workbooks, the package JSON and the zip into ``out_dir``; return the workbooks."""
    check_rules()
    paths = {source_id: input_path(root, get_source(source_id)) for source_id in INPUTS}
    book = openpyxl.load_workbook(paths[IRENA_DATA], read_only=True, data_only=True)
    mapping, index = build_mapping(read_country_list(paths[NATURAL_EARTH]))
    wacc = build_wacc(book, mapping, index)
    opex = build_opex(book, battery_opex)
    out_dir.mkdir(parents=True, exist_ok=True)
    workbooks = {}
    for scenario in SCENARIOS:
        path = out_dir / f"{PACKAGE}-{scenario.lower()}-v{version}.xlsx"
        sheets = {
            "RES CAPEX projections": build_capex(book, scenario),
            "RES OPEX": opex,
            "Cost of capital": wacc,
            "Country mapping": mapping,
            "Inputs": inputs_sheet(book, scenario, mapping, index),
            "Method": method_sheet(),
            "Sources": sources_sheet(scenario),
        }
        write_workbook(path, sheets)
        workbooks[scenario] = path
    meta = out_dir / f"{PACKAGE}.json"
    meta.write_text(json.dumps(package_json(version, workbooks, battery_opex), indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(out_dir / f"{PACKAGE}-v{version}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for path in [*workbooks.values(), meta]:
            zf.write(path, path.name)
    return workbooks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, required=True, help="Folder for the workbooks, JSON and zip")
    parser.add_argument("--root", type=Path, help="Data root that holds sources/ (default: the BOA data root)")
    parser.add_argument("--version", default="0.1", help="Package version")
    parser.add_argument("--battery-opex", type=float, default=0.02, help="Battery O&M placeholder, fraction of CAPEX")
    args = parser.parse_args(argv)
    try:
        workbooks = build(args.root or default_root(), args.out_dir, args.version, args.battery_opex)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in workbooks.values():
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
