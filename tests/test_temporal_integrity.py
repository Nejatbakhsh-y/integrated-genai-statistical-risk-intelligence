from datetime import date

import pytest

from risk_intelligence.validation.temporal import (
    assert_information_available,
)


def test_historical_information():

    assert_information_available(
        date(2022, 2, 1),
        date(2022, 12, 31),
    )


def test_future_information_rejected():

    with pytest.raises(ValueError):

        assert_information_available(
            date(2023, 1, 1),
            date(2022, 12, 31),
        )