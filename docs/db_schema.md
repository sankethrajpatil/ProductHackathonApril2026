# Database Schema — SplitBot

All collections are scoped by `group_id` for strict tenant isolation.

---

## groups
- `group_id` (int, PK)
- `title` (str)
- `default_currency` (str)
- `settings` (dict)

## users
- `group_id` (int, FK)
- `user_id` (int, PK)
- `username` (str)
- `first_name` (str)
- `wallet_address` (str, optional)
- `premium_status` (bool)
- `premium_since` (datetime)
- `premium_payment` (dict)

## expenses
- `group_id` (int, FK)
- `expense_id` (ObjectId, PK)
- `payer_id` (int)
- `participants` (list[int])
- `amount` (str, Decimal as string)
- `currency` (str)
- `description` (str)
- `created_at` (datetime)
- `is_settlement` (bool)
- `blockchain` (dict, optional)
    - `network` (str)
    - `tx_hash` (str)
    - `amount_ton` (str)
    - `verified` (bool)
    - `verified_at` (datetime)

## settlements
- `group_id` (int, FK)
- `settlement_id` (ObjectId, PK)
- `from_user_id` (int)
- `to_user_id` (int)
- `amount` (str, Decimal as string)
- `currency` (str)
- `created_at` (datetime)
- `blockchain` (dict, optional)

---

## Indexes
- All queries include `group_id` as first filter
- Compound: `{ group_id: 1, created_at: -1 }` on `expenses`
- Unique: `{ group_id: 1, user_id: 1 }` on `users`
- Sparse unique: `{ blockchain.tx_hash: 1 }` on `expenses`
