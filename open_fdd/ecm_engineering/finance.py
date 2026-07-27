def simple_payback(cost: float, annual_savings: float) -> float | None:
    return None if annual_savings <= 0 else cost / annual_savings

def npv(
    initial_cost: float,
    annual_savings: float,
    years: int = 15,
    discount_rate: float = 0.05,
    escalation: float = 0.0,
) -> float:
    total = -float(initial_cost)
    for year in range(1, years + 1):
        cash = annual_savings * (1 + escalation) ** (year - 1)
        total += cash / (1 + discount_rate) ** year
    return total
