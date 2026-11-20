"""The capacity-ceiling parameters: Deng et al. (2015), "high" case, and their registry entries."""

import pytest

from boa.config import physical_parameters as pp
from boa.config.sources import get_source, sources_with_tag

URBAN, WETLAND, WATER, ICE, NO_DATA = 190, (160, 170, 180), 210, 220, 0


def _resolve(label: str) -> None:
    source_id, ref = label.split(": ", 1)
    get_source(source_id).label(ref)  # raises KeyError for an unknown id or table


def test_every_capacity_value_names_a_registered_table():
    for label in (*pp.CAPACITY_DENSITY_SOURCE.values(), pp.AVAILABILITY_SOURCE):
        _resolve(label)


def test_the_capacity_ceiling_tag_holds_exactly_deng():
    assert list(sources_with_tag("capacity-ceiling")) == [pp.DENG_2015]


def test_densities_are_deng_values():
    assert pp.CAPACITY_DENSITY_MW_PER_KM2 == {"pv": 50.0, "wind": 7.0}


@pytest.mark.parametrize(
    "tech, code, expected",
    [
        # Deng Table 2, High case, industrialised countries.
        ("pv", 10, 0.02),  # cropland -> agriculture
        ("pv", 130, 0.03),  # grassland
        ("pv", 150, 0.03),  # sparse vegetation -> barren
        ("pv", 200, 0.08),  # bare areas -> desert
        ("wind", 10, 0.10),
        ("wind", 60, 0.02),  # tree cover -> forest
        ("wind", 100, 0.02),  # tree mosaic -> forest
        ("wind", 122, 0.10),  # shrubland -> grassland
        ("wind", 200, 0.10),
    ],
)
def test_land_cover_fractions_are_deng_high(tech, code, expected):
    assert pp.LULC_CODES[tech][code] == pytest.approx(expected)


def test_classes_deng_excludes_are_unlisted():
    for tech in ("pv", "wind"):
        for code in (URBAN, *WETLAND, WATER, ICE, NO_DATA):
            assert code not in pp.LULC_CODES[tech], (tech, code)
    # Deng excludes forest for solar, "including mixed land covers".
    for code in (50, 60, 90, 100, 110):
        assert code not in pp.LULC_CODES["pv"], code


def test_every_fraction_is_a_share():
    for codes in pp.LULC_CODES.values():
        assert all(0.0 < f <= 1.0 for f in codes.values())
