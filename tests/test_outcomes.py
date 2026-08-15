import pytest

from risk_intelligence.features.outcomes import (
    funded_ratio,
    funding_change,
    material_deterioration,
)


def test_funded_ratio():

    assert funded_ratio(80, 100) == pytest.approx(0.8)


def test_bad_liability():

    with pytest.raises(ValueError):

        funded_ratio(80, 0)


def test_funding_change():

    assert funding_change(0.90, 0.82) == pytest.approx(-0.08)


def test_material_deterioration():

    assert material_deterioration(-0.08, 0.05) == 1