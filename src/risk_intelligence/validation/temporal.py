from datetime import date


def information_is_available(
    information_date: date,
    forecast_cutoff: date,
) -> bool:

    return information_date <= forecast_cutoff


def assert_information_available(
    information_date: date,
    forecast_cutoff: date,
) -> None:

    if information_date > forecast_cutoff:

        raise ValueError(
            "Temporal leakage detected."
        )