# User Flow — SplitBot

## 1. Group Setup
- Add SplitBot to Telegram group
- Run `/start` to register group
- Bot passively tracks users as they join/send messages

## 2. Adding Expenses
- User sends message (e.g., "paid 1200 INR for dinner with @alice and @bob")
- NLP parser extracts amount, currency, participants, description
- If message contains a photo/document (receipt), OCR is triggered
- If OCR/NLP is uncertain, bot asks for confirmation via inline keyboard
- Expense is saved (amount as Decimal, group_id scoped)

## 3. Viewing Balances
- `/balance` — shows user's net balance
- `/balances` — shows all group balances
- `/history` — shows recent expenses
- TMA dashboard (webapp) shows all balances/settlements

## 4. Settling Debts
- `/settle` — computes minimal settlement plan
- User can settle on-chain (TON) via dashboard (wallet connect, send, verify)
- On-chain settlements are verified and recorded

## 5. Premium Features
- `/premium` — shows features, buy button (Telegram Stars)
- Payment auto-approves, user upgraded

## 6. Analytics
- `/analytics <question>` — ask financial questions ("How much did we spend on food this month?")
- LLM answers based on secure, read-only aggregation

## 7. Security
- All input validated
- Rate limiting on OCR
- All money as Decimal
- No raw LLM DB access
