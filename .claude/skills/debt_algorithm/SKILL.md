# SKILL.md — Greedy Debt Simplification Algorithm

## Purpose

Given a set of expenses among participants in a group chat, compute the **minimum number of transactions** needed to settle all debts. This is the core financial engine of SplitBot.

---

## Algorithm: Greedy Settlement

### Overview

The greedy algorithm reduces an arbitrary web of debts to at most $n - 1$ transactions (where $n$ is the number of participants with non-zero balances). It works by repeatedly settling the largest creditor against the largest debtor.

### Definitions

- **Net balance** $b_i$: The total amount owed *to* user $i$ minus the total amount user $i$ owes. A positive $b_i$ means user $i$ is a **creditor**; a negative $b_i$ means user $i$ is a **debtor**.
- $v_{max}$: The user with the maximum positive balance (largest creditor).
- $v_{min}$: The user with the maximum negative balance (largest debtor, i.e., most negative $b_i$).

### Invariant

$$\sum_{i=1}^{n} b_i = 0$$

The sum of all net balances is always zero (every dollar owed by someone is owed *to* someone).

### Steps

```
1. For each user i, compute net balance:
       b_i = Σ(amounts owed TO i) − Σ(amounts i OWES)

2. Remove all users where b_i = 0 (already settled).

3. While any non-zero balances remain:
   a. Find v_max = argmax(b_i)          # largest creditor
   b. Find v_min = argmin(b_i)          # largest debtor (most negative)
   c. settlement = min(b[v_max], abs(b[v_min]))
   d. Record transaction: v_min pays v_max the settlement amount
   e. b[v_max] -= settlement
   f. b[v_min] += settlement
   g. If b[v_max] == 0, remove v_max from active set
   h. If b[v_min] == 0, remove v_min from active set

4. Return list of settlement transactions.
```

### Worked Example

**Expenses:**
| Payer  | Description | Amount | Split Among       |
| ------ | ----------- | ------ | ------------------ |
| Alice  | Dinner      | $60    | Alice, Bob, Carol  |
| Bob    | Taxi        | $30    | Alice, Bob, Carol  |

**Step 1 — Compute net balances:**

Alice paid $60, her share of dinner is $20, her share of taxi is $10 → she is owed $60 − $20 − $10 = **+$30**

Bob paid $30, his share of dinner is $20, his share of taxi is $10 → he is owed $30 − $20 − $10 = **$0**

Carol paid $0, her share of dinner is $20, her share of taxi is $10 → she owes $0 − $20 − $10 = **−$30**

**Step 2 — Remove zeros:** Bob is removed. Active: `{Alice: +30, Carol: -30}`

**Step 3 — Settle:**

| Iteration | $v_{max}$ | $v_{min}$ | Settlement | Transaction           |
| --------- | --------- | --------- | ---------- | --------------------- |
| 1         | Alice (+30) | Carol (−30) | $30      | Carol → Alice: $30    |

**Result:** One transaction: Carol pays Alice $30. Done.

---

## Implementation Rules

### MUST use `decimal.Decimal`

All balance computations, comparisons, and settlement amounts **must** use `Decimal`. Reference the financial rule in `CLAUDE.md`.

```python
from decimal import Decimal, ROUND_HALF_UP

def compute_settlements(balances: dict[int, Decimal]) -> list[dict]:
    """
    balances: {user_id: net_balance} where sum(values) == 0
    Returns: list of {"from": user_id, "to": user_id, "amount": Decimal}
    """
    # Work on a mutable copy; filter zeros
    b = {uid: bal for uid, bal in balances.items() if bal != Decimal("0")}
    settlements = []

    while b:
        v_max = max(b, key=b.get)
        v_min = min(b, key=b.get)
        settlement = min(b[v_max], abs(b[v_min]))

        settlements.append({
            "from": v_min,
            "to": v_max,
            "amount": settlement,
        })

        b[v_max] -= settlement
        b[v_min] += settlement

        # Remove settled users
        b = {uid: bal for uid, bal in b.items() if bal != Decimal("0")}

    return settlements
```

### Edge Cases

| Case                          | Handling                                                                 |
| ----------------------------- | ------------------------------------------------------------------------ |
| Single participant            | No debts. Return empty list.                                             |
| All participants paid equally | All net balances are zero. Return empty list.                            |
| Uneven split with remainder   | Use `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`. Assign remainder cent to the payer. |
| "Everyone" keyword            | Resolve to all known users in the group (see Telegram rules in `CLAUDE.md`). |

### Complexity

- **Time:** $O(n^2)$ in the worst case (each iteration removes at least one user).
- **Space:** $O(n)$ for the balance map and output list.
- For typical group chat sizes ($n < 50$), this is instantaneous.

### Testing Requirements

- Test with 2, 3, 5, and 10+ participants.
- Verify the invariant: sum of all settlement amounts flowing out of debtors equals sum flowing into creditors.
- Verify that the final balance of every user is exactly `Decimal("0")`.
- Test remainder-cent distribution on uneven splits (e.g., $10 split 3 ways).
