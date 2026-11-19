"""
Build the boa-cost-data-core package: one BOA cost workbook per IEA WEO 2025 scenario (CPS, STEPS, NZE).

Every value comes from a pinned file in src/boa/config/cost_sources.toml, and every row names its
source as "<id>: <item ref>". Fetch the files first:

    boa-sources-fetch irena-rpgc-2024-data irena-rpgc-2024-report iea-weo-2025 steel-iq-master-input-3-0-0
    python scripts/cost/build_core.py --out-dir <folder>

Method:
- CAPEX 2024: IRENA Tables 3.1 (solar PV) and 2.1 (onshore wind) per IRENA cost region. The Middle East
  has no IRENA row and takes the global weighted average (Table S.1).
- CAPEX 2035 and 2050: the 2024 value times the WEO 2025 Table B.4 change from 2024 of the same scenario.
  United States, Europe, China and India follow their own WEO row (Europe follows the European Union).
  All other regions follow the mean change of these four rows.
- Battery CAPEX: WEO 2025 Table B.5 (global) in every region.
- The workbook has the year columns 2024, 2035 and 2050 only. BOA interpolates linearly between them
  and holds the 2050 value for later years.
- OPEX: IRENA O&M (Tables A3, A4) divided by the region's 2024 CAPEX. No core source gives battery
  O&M, so the battery row is a placeholder (--battery-opex) and its source says so.
- Cost of capital: IRENA Fig A1, the mean of onshore wind and solar PV. A country with no own Fig A1
  value (Fig A1 shows the Annex I default) takes the median of the own values in its IRENA cost region.
- Countries: the ISO-3 codes of the steel-iq master input Country mapping, put into IRENA cost regions
  by IRENA Annex III.
"""

import argparse
import hashlib
import json
import re
import statistics
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd

from boa.cli.fetch_sources import file_sha256
from boa.config.cost_sources import Source, get_source, source_path
from boa.config.paths import default_root

PACKAGE = "boa-cost-data-core"
YEARS = (2024, 2035, 2050)
BASE_YEAR = YEARS[0]
SCENARIOS = ("CPS", "STEPS", "NZE")

IRENA_DATA = "irena-rpgc-2024-data"
IRENA_REPORT = "irena-rpgc-2024-report"
WEO = "iea-weo-2025"
COUNTRY_LIST = "steel-iq-master-input-3-0-0"
INPUTS = (IRENA_DATA, IRENA_REPORT, WEO, COUNTRY_LIST)

# IEA WEO 2025 Annex B, capital costs in year-2024 USD/kW for 2024, 2035, 2050 (Tables B.4a-c, pp. 454-456).
WEO_TABLE = {"CPS": "Table B.4a", "STEPS": "Table B.4b", "NZE": "Table B.4c"}
WEO_CAPEX = {
    "CPS": {
        "United States": {"solar": (1060, 680, 570), "wind": (1570, 1510, 1470)},
        "European Union": {"solar": (760, 480, 410), "wind": (1620, 1540, 1510)},
        "China": {"solar": (590, 360, 290), "wind": (860, 810, 790)},
        "India": {"solar": (530, 320, 260), "wind": (1110, 1050, 1020)},
    },
    "STEPS": {
        "United States": {"solar": (1060, 660, 530), "wind": (1570, 1510, 1460)},
        "European Union": {"solar": (760, 470, 390), "wind": (1620, 1540, 1510)},
        "China": {"solar": (590, 350, 280), "wind": (860, 800, 790)},
        "India": {"solar": (530, 310, 250), "wind": (1110, 1040, 1010)},
    },
    "NZE": {
        "United States": {"solar": (1060, 590, 480), "wind": (1570, 1450, 1400)},
        "European Union": {"solar": (760, 440, 370), "wind": (1620, 1510, 1460)},
        "China": {"solar": (590, 320, 260), "wind": (860, 780, 750)},
        "India": {"solar": (530, 290, 220), "wind": (1110, 1020, 970)},
    },
}
# IEA WEO 2025 Table B.5 (p. 457): utility-scale stationary batteries, year-2024 USD/kWh, global.
WEO_BATTERY = {"CPS": (150, 100, 90), "STEPS": (150, 100, 90), "NZE": (150, 100, 80)}
# The IRENA cost region that follows each WEO row. All other regions follow the mean of the four rows.
WEO_REGION_OF = {
    "United States": "United States",
    "Europe": "European Union",
    "China": "China",
    "India": "India",
}

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
OECD_REGIONS = {"Europe", "Other North America", "Oceania", "United States"}
TECHS = {
    "solar": ("Solar PV", "USD/kW", "Table 3.1"),
    "wind": ("Onshore wind", "USD/kW", "Table 2.1"),
    "battery": ("Battery", "USD/kWh", None),
}

# IRENA (2025) report, Annex III "Regional groupings" (p. 215). Asia, North America and South America are
# split into the single-country cost rows and "Other ..." below.
ANNEX_III = {
    "Asia": (
        "Afghanistan, Bangladesh, Bhutan, Brunei Darussalam, Cambodia, China, Democratic People's Republic of Korea, "
        "India, Indonesia, Japan, Kazakhstan, Kyrgyzstan, Lao People's Democratic Republic, Malaysia, Maldives, "
        "Mongolia, Myanmar, Nepal, Pakistan, Philippines, Republic of Korea, Singapore, Sri Lanka, Tajikistan, "
        "Thailand, Timor-Leste, Turkmenistan, Uzbekistan, Viet Nam"
    ),
    "Africa": (
        "Algeria, Angola, Benin, Botswana, Burkina Faso, Burundi, Cabo Verde, Cameroon, Central African Republic, "
        "Chad, Comoros, Congo, Cote d'Ivoire, Democratic Republic of the Congo, Djibouti, Egypt, Equatorial Guinea, "
        "Eritrea, Ethiopia, Eswatini, Gabon, Gambia, Ghana, Guinea, Guinea-Bissau, Kenya, Lesotho, Liberia, Libya, "
        "Madagascar, Malawi, Mali, Mauritania, Mauritius, Morocco, Mozambique, Namibia, Niger, Nigeria, Rwanda, "
        "Sao Tome and Principe, Senegal, Seychelles, Sierra Leone, Somalia, South Africa, South Sudan, Sudan, Togo, "
        "Tunisia, Uganda, United Republic of Tanzania, Zambia, Zimbabwe"
    ),
    "Central America and the Caribbean": (
        "Antigua and Barbuda, Bahamas, Barbados, Belize, Costa Rica, Cuba, Dominica, Dominican Republic, El Salvador, "
        "Grenada, Guatemala, Haiti, Honduras, Jamaica, Nicaragua, Panama, Saint Kitts and Nevis, Saint Lucia, "
        "Saint Vincent and the Grenadines, Trinidad and Tobago"
    ),
    "Eurasia": "Armenia, Azerbaijan, Georgia, Russian Federation, Turkiye",
    "Europe": (
        "Albania, Andorra, Austria, Belarus, Belgium, Bosnia and Herzegovina, Bulgaria, Croatia, Cyprus, "
        "Czech Republic, Denmark, Estonia, Finland, France, Germany, Greece, Hungary, Iceland, Ireland, Italy, "
        "Latvia, Liechtenstein, Lithuania, Luxembourg, Malta, Monaco, Montenegro, Netherlands, Norway, Poland, "
        "Portugal, Republic of Moldova, Romania, San Marino, Serbia, Slovakia, Slovenia, Spain, Sweden, "
        "Switzerland, Ukraine, United Kingdom"
    ),
    "Middle East": (
        "Bahrain, Islamic Republic of Iran, Iraq, Israel, Jordan, Kuwait, Lebanon, Oman, Qatar, Saudi Arabia, "
        "Syrian Arab Republic, United Arab Emirates, Yemen"
    ),
    "North America": "Canada, Mexico, United States",
    "South America": (
        "Argentina, Plurinational State of Bolivia, Brazil, Chile, Colombia, Ecuador, Guyana, Paraguay, Peru, "
        "Suriname, Uruguay, Bolivarian Republic of Venezuela"
    ),
    "Oceania": (
        "Australia, Fiji, Kiribati, Marshall Islands, Federated States of Micronesia, Nauru, New Zealand, Palau, "
        "Papua New Guinea, Samoa, Solomon Islands, Tonga, Tuvalu, Vanuatu"
    ),
}
SINGLE_COUNTRY_ROWS = {"CHN": "China", "IND": "India", "BRA": "Brazil", "USA": "United States"}
SPLIT_REGIONS = {"Asia": "Other Asia", "North America": "Other North America", "South America": "Other South America"}

# IRENA spells some countries differently from the country list; keys and values are normalised names.
NAME_ALIASES = {
    "viet nam": "vietnam",
    "democratic people's republic of korea": "north korea",
    "republic of korea": "south korea",
    "lao people's democratic republic": "laos",
    "russian federation": "russia",
    "united republic of tanzania": "tanzania",
    "congo": "republic of the congo",
    "bolivarian republic of venezuela": "venezuela",
    "plurinational state of bolivia": "bolivia",
    "islamic republic of iran": "iran",
    "syrian arab republic": "syria",
    "republic of moldova": "moldova",
    "federated states of micronesia": "micronesia",
    "turkiye": "turkey",
    "cabo verde": "cape verde",
    "czech republic": "czechia",
    "united states": "united states of america",
    "congo rep": "republic of the congo",
    "bolivia plurinational state of": "bolivia",
    "iran islamic republic of": "iran",
    "venezuela bolivarian republic of": "venezuela",
}

# Territories that Annex III does not list take the IRENA cost region of their country-list region.
CROSSWALK = {
    "Central America": "Central America and the Caribbean",
    "East Africa": "Africa",
    "North Africa": "Africa",
    "Southern Africa": "Africa",
    "West Africa": "Africa",
    "China": "China",
    "EU + Schengen": "Europe",
    "Other Europe": "Europe",
    "India": "Other Asia",
    "Middle East": MIDDLE_EAST,
    "North America": "Other North America",
    "Oceania": "Oceania",
    "Russia + CIS": "Eurasia",
    "South + East Asia": "Other Asia",
    "South America": "Other South America",
}
# The country-list region of these territories is wrong, so they take their geographic IRENA cost region.
TERRITORY_REGIONS = {
    "GLP": "Central America and the Caribbean",  # Guadeloupe
    "MYT": "Africa",  # Mayotte
    "GRL": "Other North America",  # Greenland
    "HKG": "China",  # Hong Kong
}

# Fig A1 shows the Annex I default (5% OECD and China, 7.5% elsewhere) for a country without its own value.
ANNEX_I_DEFAULTS = (0.05, 0.075)


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
    return float(re.sub(r"[\s  ]", "", str(cell)))


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
    The steel-iq master input Country mapping, with the column names the build uses.

    Rows with no region (Antarctica and uninhabited islands) are dropped, as in boa-cost-data v0.1.
    """
    df = pd.read_excel(path, sheet_name="Country mapping")
    df = df.rename(
        columns={
            "Country": "country",
            "ISO 3-letter code": "code",
            "irena_name": "irena name",
            "irena_region": "irena region",
        }
    )
    return df.dropna(subset=["code", "irena region"])[["country", "code", "irena name", "irena region"]]


# --- countries ----------------------------------------------------------------------------------


def build_mapping(country_list: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Put every country of the list into an IRENA cost region (Annex III, else the list's own region).

    Returns the mapping and the normalised-name -> ISO-3 index, which the WACC lookup uses again.
    """
    index: dict[str, str] = {}
    for col in ("country", "irena name"):
        for code, name in zip(country_list["code"], country_list[col]):
            index.setdefault(norm(name), code)
    region_of: dict[str, str] = {}
    unmatched = []
    for annex_region, names in ANNEX_III.items():
        for name in names.split(", "):
            code = index.get(norm(name))
            if code is None:
                unmatched.append(name)
                continue
            region_of[code] = SINGLE_COUNTRY_ROWS.get(code, SPLIT_REGIONS.get(annex_region, annex_region))
    if unmatched:
        raise ValueError(f"Annex III names with no country-list match: {unmatched}")
    annex = label(IRENA_REPORT, "Annex III")
    rows = []
    for rec in country_list.to_dict("records"):
        code = rec["code"]
        if code in region_of:
            region, src = region_of[code], annex
        elif code in TERRITORY_REGIONS:
            region, src = TERRITORY_REGIONS[code], f"not in {annex}; geographic region"
        else:
            region = CROSSWALK[rec["irena region"]]
            src = f"not in {annex}; region {rec['irena region']!r} of {label(COUNTRY_LIST, 'Country mapping')}"
        rows.append(
            {
                "country": _fix_text(rec["country"]),
                "code": code,
                "irena name": _fix_text(rec["irena name"]),
                "irena region": region,
                "source": src,
            }
        )
    return pd.DataFrame(rows), index


# --- CAPEX --------------------------------------------------------------------------------------


def irena_capex(book: openpyxl.Workbook) -> dict[str, dict[str, float]]:
    """2024 weighted-average total installed cost (USD/kW) per tech and region; Middle East = global (Table S.1)."""
    glob = _table(book, "Table S.1")
    out = {}
    for tech, sheet, glob_label in (("solar", "Table 3.1", "Solar PV"), ("wind", "Table 2.1", "Onshore wind")):
        table = _table(book, sheet)
        # Each row is [5th, average, 95th] for 2010, then for 2024: the 2024 average is the 5th cell.
        out[tech] = {region: _num(_row(table, region)[4]) for region in COST_ROWS}
        out[tech][MIDDLE_EAST] = _num(_row(glob, glob_label)[1])
    return out


def weo_change(scenario: str, tech: str, region: str) -> tuple[tuple[float, ...], str]:
    """CAPEX relative to 2024 for YEARS from WEO Table B.4, and the path's description."""
    rows = WEO_CAPEX[scenario]
    if (weo_region := WEO_REGION_OF.get(region)) is not None:
        values = rows[weo_region][tech]
        return tuple(v / values[0] for v in values), f"{weo_region} change"
    changes = [tuple(v / r[tech][0] for v in r[tech]) for r in rows.values()]
    return tuple(statistics.fmean(c[i] for c in changes) for i in range(len(YEARS))), "mean change of its 4 regions"


def build_capex(book: openpyxl.Workbook, scenario: str) -> pd.DataFrame:
    """CAPEX rows for YEARS: IRENA 2024 level times the WEO 2025 change; battery from WEO Table B.5."""
    base = irena_capex(book)
    weo = label(WEO, WEO_TABLE[scenario])
    rows = []
    for tech, (tech_label, unit, irena_table) in TECHS.items():
        for region in REGIONS:
            if tech == "battery":
                values = WEO_BATTERY[scenario]
                src = f"{label(WEO, 'Table B.5')} (global)"
            else:
                change, path = weo_change(scenario, tech, region)
                values = tuple(base[tech][region] * c for c in change)
                level = label(IRENA_DATA, "Table S.1" if region == MIDDLE_EAST else irena_table)
                src = f"2024: {level}; 2035, 2050: x {weo} {path}"
            row = {"irena region": region, "tech": tech_label, "unit": f"2024 {unit}", "source": src}
            row.update({year: round(value, 2) for year, value in zip(YEARS, values)})
            rows.append(row)
    return pd.DataFrame(rows)


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


def build_opex(book: openpyxl.Workbook, battery_opex: float) -> pd.DataFrame:
    """OPEX as a fraction of CAPEX per year: IRENA's O&M (USD/kW/year) over the region's 2024 CAPEX."""
    om = irena_om(book)
    base = irena_capex(book)
    world = [
        # BOA needs a World row per technology for a country with no regional row. Every mapped country
        # has a regional row, so these are fallbacks only: non-OECD O&M over the global CAPEX.
        {
            "region": "World",
            "tech": tech,
            "unit": "fraction of capex per year",
            "opex": round(om[key] / base[level][MIDDLE_EAST], 5),
            "source": f"{label(IRENA_DATA, table)} non-OECD {om[key]:g} USD/kW/year / {label(IRENA_DATA, 'Table S.1')}",
        }
        for tech, key, table, level in (
            ("Solar PV", "solar_non_oecd", "Table A4", "solar"),
            ("Onshore wind", "wind_non_oecd", "Table A3", "wind"),
        )
    ]
    rows = world + [
        {
            "region": "World",
            "tech": "Battery",
            "unit": "fraction of capex per year",
            "opex": battery_opex,
            "source": "none: placeholder, no core source gives battery O&M",
        }
    ]
    for region in REGIONS:
        oecd = region in OECD_REGIONS
        for tech, key, table, level in (
            ("Solar PV", "solar_oecd" if oecd else "solar_non_oecd", "Table A4", "solar"),
            (
                "Onshore wind",
                f"wind_{region}" if f"wind_{region}" in om else f"wind_{'oecd' if oecd else 'non_oecd'}",
                "Table A3",
                "wind",
            ),
        ):
            capex_ref = "Table S.1" if region == MIDDLE_EAST else TECHS[level][2]
            rows.append(
                {
                    "region": region,
                    "tech": tech,
                    "unit": "fraction of capex per year",
                    "opex": round(om[key] / base[level][region], 5),
                    "source": f"{label(IRENA_DATA, table)} {om[key]:g} USD/kW/year / {label(IRENA_DATA, capex_ref)}",
                }
            )
    return pd.DataFrame(rows)


# --- cost of capital ----------------------------------------------------------------------------


def fig_a1(book: openpyxl.Workbook) -> dict[str, tuple[float, float]]:
    """(onshore wind, solar PV) real after-tax WACC per normalised country name."""
    out = {}
    for row in _table(book, "Fig A1"):
        if len(row) >= 3 and isinstance(row[1], (int, float)) and isinstance(row[2], (int, float)):
            out[norm(row[0])] = (float(row[1]), float(row[2]))
    return out


def is_default(wind: float, solar: float) -> bool:
    """True if Fig A1 shows the Annex I default, not a country's own value."""
    return wind == solar and any(abs(wind - d) < 1e-12 for d in ANNEX_I_DEFAULTS)


def build_wacc(book: openpyxl.Workbook, mapping: pd.DataFrame, index: dict[str, str]) -> pd.DataFrame:
    """One Renewables WACC per country: own Fig A1 value, else the median of own values in its cost region."""
    own: dict[str, float] = {}
    for name, (wind, solar) in fig_a1(book).items():
        if name in index and not is_default(wind, solar):
            own[index[name]] = (wind + solar) / 2
    region_of = dict(zip(mapping["code"], mapping["irena region"]))
    by_region: dict[str, list[float]] = {}
    for code, value in own.items():
        by_region.setdefault(region_of[code], []).append(value)
    if empty := sorted(set(REGIONS) - set(by_region)):
        raise ValueError(f"No own Fig A1 value in the cost regions {empty}")
    fig = label(IRENA_DATA, "Fig A1")
    rows = []
    for rec in mapping.to_dict("records"):
        if rec["code"] in own:
            value, src = own[rec["code"]], f"{fig}, mean of onshore wind and solar PV"
        else:
            values = by_region[rec["irena region"]]
            value = statistics.median(values)
            src = f"{fig}, median of the {len(values)} own values in {rec['irena region']} ({label(IRENA_REPORT, 'Annex III')})"
        rows.append(
            {
                "country": rec["country"],
                "code": rec["code"],
                "tech": "Renewables",
                "cost of capital": round(value, 5),
                "source": src,
            }
        )
    return pd.DataFrame(rows)


# --- output -------------------------------------------------------------------------------------


def sources_sheet(scenario: str) -> pd.DataFrame:
    items = [("Package", PACKAGE), ("Scenario", f"IEA WEO 2025 {scenario}"), ("Currency", "2024 USD, real")]
    items += [("Years", "2024, 2035, 2050; BOA interpolates linearly between them and holds 2050 after it")]
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
        "method": {
            "years": "2024, 2035, 2050; BOA interpolates linearly between them",
            "capex": "IRENA Tables 3.1, 2.1 (Middle East: S.1) x IEA WEO 2025 Tables B.4a-c change from 2024; "
            "United States, Europe (EU row), China, India own row, other regions the mean change of the four",
            "battery_capex": "IEA WEO 2025 Table B.5, global, every region",
            "opex": f"IRENA Tables A3, A4 O&M over the region's 2024 CAPEX; battery {battery_opex:g} placeholder",
            "cost_of_capital": "IRENA Fig A1 mean of onshore wind and solar PV; a country without an own value "
            "takes the median of the own values in its IRENA cost region",
            "regions": "IRENA Annex III; territories outside Annex III take their country-list or geographic region",
        },
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
    paths = {source_id: input_path(root, get_source(source_id)) for source_id in INPUTS}
    book = openpyxl.load_workbook(paths[IRENA_DATA], read_only=True, data_only=True)
    mapping, index = build_mapping(read_country_list(paths[COUNTRY_LIST]))
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
