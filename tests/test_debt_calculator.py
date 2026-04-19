from decimal import Decimal
from app.services.debt_calculator import compute_settlements

# Characterization tests for greedy debt simplification

def test_simple_triangle():
    # Alice owes Bob, Bob owes Carol, Carol owes Alice
    balances = [
        {"user_id": 1, "net_balance": Decimal("10.00")},
        {"user_id": 2, "net_balance": Decimal("-5.00")},
        {"user_id": 3, "net_balance": Decimal("-5.00")},
    ]
    settlements = compute_settlements(balances)
    total = sum(Decimal(s["amount"]) for s in settlements)
    assert total == Decimal("10.00")
    # No pennies lost
    assert all(Decimal(s["amount"]).as_tuple().exponent >= -2 for s in settlements)

def test_no_rounding_errors():
    balances = [
        {"user_id": 1, "net_balance": Decimal("0.01")},
        {"user_id": 2, "net_balance": Decimal("-0.01")},
    ]
    settlements = compute_settlements(balances)
    assert settlements[0]["amount"] == "0.01"

def test_large_group():
    balances = [
        {"user_id": i, "net_balance": Decimal("1.00") if i % 2 == 0 else Decimal("-1.00")}
        for i in range(10)
    ]
    settlements = compute_settlements(balances)
    # All debts settled
    assert sum(Decimal(s["amount"]) for s in settlements) == Decimal("5.00")
