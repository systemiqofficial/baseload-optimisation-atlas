"""The core cost build (scripts/cost/build_core.py)."""

import importlib.util
import re
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from boa.config.cost_sources import get_source, load_registry, source_path
from boa.config.paths import default_root

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cost" / "build_core.py"
_spec = importlib.util.spec_from_file_location("build_core", SCRIPT)
build_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_core)


def _pinned_inputs_present() -> bool:
    root = default_root()
    return all(source_path(root, get_source(s)).is_file() for s in build_core.INPUTS)


needs_inputs = pytest.mark.skipif(not _pinned_inputs_present(), reason="pinned source files are not fetched")


# --- rules ----------------------------------------------------------------------------------------


def test_every_registry_item_the_build_names_exists():
    for source_id, ref in [
        *((build_core.WEO, table) for table in build_core.WEO_TABLE.values()),
        (build_core.WEO, "Table B.5"),
        *((build_core.IRENA_DATA, ref) for ref in ("Table 2.1", "Table 3.1", "Table S.1", "Table A3", "Table A4")),
        (build_core.IRENA_DATA, "Fig A1"),
        (build_core.IRENA_REPORT, "Annex III"),
        *((build_core.NATURAL_EARTH, ref) for ref in ("ISO_A3", "SUBREGION", "SOVEREIGNT")),
    ]:
        assert build_core.label(source_id, ref) == f"{source_id}: {ref}"


def test_the_registry_holds_exactly_the_build_inputs():
    assert tuple(load_registry()) == build_core.INPUTS


def test_weo_region_follows_its_own_row():
    change, path = build_core.weo_change("STEPS", "solar", "United States")
    assert change == pytest.approx((1.0, 660 / 1060, 530 / 1060))
    assert path == "United States change"


def test_other_region_follows_the_mean_change_of_the_four_rows():
    change, _ = build_core.weo_change("NZE", "wind", "Africa")
    rows = build_core.WEO_CAPEX["NZE"].values()
    expected_2050 = sum(r["wind"][2] / r["wind"][0] for r in rows) / 4
    assert change[0] == 1.0
    assert change[2] == pytest.approx(expected_2050)


def test_europe_follows_the_eu_row():
    assert build_core.WEO_REGION_OF["Europe"] == "European Union"


def _territory(subregion: str, region_un: str = "", sovereign: str = "Someland") -> dict:
    return {"subregion": subregion, "region_un": region_un, "sovereign": sovereign}


@pytest.mark.parametrize(
    "rec, region",
    [
        (_territory("South America"), "Other South America"),  # French Guiana
        (_territory("Northern America"), "Other North America"),  # Bermuda, Greenland
        (_territory("Caribbean"), "Central America and the Caribbean"),
        (_territory("Western Asia"), "Middle East"),  # Palestine
        (_territory("Eastern Asia", sovereign="Taiwan"), "Other Asia"),
        (_territory("Eastern Asia", sovereign="China"), "China"),  # Hong Kong
        (_territory("Seven seas (open ocean)", "Africa"), "Africa"),
        (_territory("Seven seas (open ocean)", "Americas"), "Other South America"),
    ],
)
def test_code_outside_annex_iii_takes_the_region_of_its_natural_earth_subregion(rec, region):
    assert build_core.subregion_region(rec)[0] == region


def test_every_subregion_rule_names_an_irena_cost_region():
    rules = [*build_core.SUBREGION_REGIONS.values(), *build_core.REGION_UN_REGIONS.values()]
    assert set(rules) <= set(build_core.REGIONS)


def test_unknown_subregion_is_an_error():
    with pytest.raises(KeyError):
        build_core.subregion_region(_territory("Atlantis"))


def test_a_name_of_two_codes_is_not_used_for_matching():
    country_list = pd.DataFrame({"code": ["AAA", "BBB"], "names": [["Aland", "Shared"], ["Borland", "Shared"]]})
    index = build_core.name_index(country_list)
    assert index == {"aland": "AAA", "borland": "BBB"}


def _fig_a1_book(rows: list[tuple]) -> openpyxl.Workbook:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Fig A1"
    sheet.append([None, "Country", "Onshore wind", "Solar PV"])
    for row in rows:
        sheet.append([None, *row])
    return book


def test_wacc_own_value_is_the_mean_and_a_default_takes_the_regional_median():
    book = _fig_a1_book(
        [
            ("Aland", 0.04, 0.06),
            ("Borland", 0.08, 0.08),
            ("Corland", 0.10, 0.12),
            ("Dorland", 0.075, 0.075),  # Annex I default, not an own value
        ]
    )
    regions = {"Aland": "Europe", "Borland": "Europe", "Corland": "Europe", "Dorland": "Europe", "Eland": "Europe"}
    mapping = pd.DataFrame(
        {"country": list(regions), "code": [n[:3].upper() for n in regions], "irena region": list(regions.values())}
    )
    index = {build_core.norm(name): name[:3].upper() for name in regions}
    with pytest.raises(ValueError, match="No own Fig A1 value"):
        build_core.build_wacc(book, mapping, index)

    # Give every other cost region one own value, so the check for empty regions passes.
    others = [r for r in build_core.REGIONS if r != "Europe"]
    book = _fig_a1_book(
        [
            ("Aland", 0.04, 0.06),
            ("Borland", 0.08, 0.08),
            ("Corland", 0.10, 0.12),
            ("Dorland", 0.075, 0.075),
            *((f"Filler {i}", 0.09, 0.09) for i in range(len(others))),
        ]
    )
    fillers = pd.DataFrame(
        {"country": [f"Filler {i}" for i in range(len(others))], "code": [f"F{i:02d}" for i in range(len(others))]}
    ).assign(**{"irena region": others})
    mapping = pd.concat([mapping, fillers], ignore_index=True)
    index |= {build_core.norm(f"Filler {i}"): f"F{i:02d}" for i in range(len(others))}
    wacc = build_core.build_wacc(book, mapping, index).set_index("code")
    assert wacc.loc["ALA", "cost of capital"] == pytest.approx(0.05)
    assert "mean of onshore wind and solar PV" in wacc.loc["ALA", "source"]
    # Dorland (default) and Eland (no Fig A1 row) take the median of 0.05, 0.08, 0.11.
    for code in ("DOR", "ELA"):
        assert wacc.loc[code, "cost of capital"] == pytest.approx(0.08)
        assert "median of the 3 own values in Europe" in wacc.loc[code, "source"]


def test_input_with_a_wrong_sha256_is_refused(tmp_path):
    source = get_source(build_core.IRENA_DATA)
    path = source_path(tmp_path, source)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not the pinned file")
    with pytest.raises(ValueError, match="is not the pinned"):
        build_core.input_path(tmp_path, source)


def test_missing_input_names_the_fetch_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="boa-sources-fetch irena-rpgc-2024-data"):
        build_core.input_path(tmp_path, get_source(build_core.IRENA_DATA))


# --- against the pinned files ---------------------------------------------------------------------


def _labels(text: str, registry: dict) -> list[str]:
    """The "<id>: <ref>" labels in a source cell. Fails if a label names an id or ref the registry lacks."""
    found = []
    for match in re.finditer(r"([a-z][a-z0-9]*(?:-[a-z0-9]+)+): ", text):
        source = registry[match.group(1)]
        rest = text[match.end() :]
        refs = [ref for ref in source.refs if rest.startswith(ref)]
        assert refs, f"{text!r}: no table of {source.id} at {rest!r}"
        found.append(source.label(max(refs, key=len)))
    return found


@needs_inputs
def test_build_writes_workbooks_that_boa_reads_and_every_row_names_a_registry_item(tmp_path):
    from boa.inputs.costs import process_global_baseload_simulation_costs

    workbooks = build_core.build(default_root(), tmp_path / "out", "0.0", 0.02)
    assert set(workbooks) == set(build_core.SCENARIOS)
    registry = load_registry()
    for path in workbooks.values():
        for sheet in ("RES CAPEX projections", "RES OPEX", "Cost of capital", "Country mapping"):
            df = pd.read_excel(path, sheet_name=sheet)
            for text in df["source"]:
                if text.startswith("none:"):
                    continue
                assert _labels(text, registry), (sheet, text)
    capex = pd.read_excel(workbooks["STEPS"], sheet_name="RES CAPEX projections")
    assert [c for c in capex.columns if isinstance(c, int)] == list(build_core.YEARS)
    ds, _ = process_global_baseload_simulation_costs(2030, workbooks["STEPS"], tmp_path / "cache")
    assert float(ds["Capex battery"].sel(iso3="DEU").isel(year=0)) == pytest.approx((150 - 50 * 6 / 11) * 1000)
    assert ds["Cost of capital"].notnull().all()


@needs_inputs
def test_weo_constants_equal_the_pinned_pdf():
    pypdf = pytest.importorskip("pypdf")
    pdf = pypdf.PdfReader(source_path(default_root(), get_source(build_core.WEO)))
    page_of = {"Table B.4a": 453, "Table B.4b": 454, "Table B.4c": 455}  # 0-based page indexes
    for scenario, table in build_core.WEO_TABLE.items():
        text = pdf.pages[page_of[table]].extract_text()
        assert table in text
        blocks = re.split(r"\n(United States|European Union|China|India)\s*\n", text)
        found = dict(zip(blocks[1::2], blocks[2::2]))
        for region, techs in build_core.WEO_CAPEX[scenario].items():
            for tech, line_label in (("solar", "Solar PV"), ("wind", "Wind onshore")):
                line = next(ln for ln in found[region].splitlines() if ln.startswith(line_label))
                cells = re.split(r"\s{2,}", line[len(line_label) :].strip())
                assert tuple(int(c.replace(" ", "")) for c in cells[:3]) == techs[tech], (scenario, region, tech)
    text = pdf.pages[456].extract_text()
    numbers = [int(n) for n in re.search(r"batteries \(USD/kWh\)([\d ]+)", text).group(1).split()]
    cps, steps, nze = tuple(numbers[:3]), (numbers[0], *numbers[3:5]), (numbers[0], *numbers[5:7])
    assert {"CPS": cps, "STEPS": steps, "NZE": nze} == build_core.WEO_BATTERY
