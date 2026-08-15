def funded_ratio(assets: float, liabilities: float) -> float:
    if liabilities <= 0:
        raise ValueError("Liabilities must be positive.")

    return assets / liabilities


def funding_change(current_ratio: float, next_ratio: float) -> float:
    return next_ratio - current_ratio


def material_deterioration(delta: float, threshold: float) -> int:
    if threshold <= 0:
        raise ValueError("Threshold must be positive.")

    return int(delta <= -threshold)