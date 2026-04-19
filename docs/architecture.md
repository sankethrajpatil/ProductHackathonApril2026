# SplitBot Architecture Overview

SplitBot is a modular, async-first Telegram bot and TMA dashboard for group expense management, built for extensibility, security, and AI-powered automation.

---

## High-Level Architecture

- **Telegram Bot (aiogram 3.x):** Handles group chat commands, NLP, OCR, settlements, and analytics.
- **TMA Dashboard (webapp/):** Telegram Mini App for group balances, settlements, and TON Connect wallet integration.
- **Serverless API (api/):** Vercel endpoints for Stars, TON, and dashboard data.
- **MongoDB (motor):** Single DB, strict tenant isolation by `group_id`.
- **AI Services:** OpenAI/Claude for NLP, OCR, and analytics.

### Main Components
- `app/handlers/` — aiogram routers (commands, OCR, analytics, settlements, etc)
- `app/services/` — Business logic (NLP, OCR, blockchain, expense, balance)
- `app/core/` — DB, analytics agent, security, middlewares
- `webapp/` — TMA frontend (HTML/JS, TON Connect)
- `api/` — Vercel serverless endpoints

---

## Data Flow

1. **User sends message/receipt in group →**
2. **aiogram handler parses (NLP/OCR) →**
3. **Expense logic (Decimal, validation) →**
4. **MongoDB (group_id scoped) →**
5. **Balances/settlements recomputed →**
6. **TMA dashboard fetches via API →**
7. **Web3/TON/Stars handled via API + blockchain service**

---

## Security
- All money: `decimal.Decimal`, stored as string
- All queries: `group_id` isolation
- Input validation: XSS/injection protection
- TON/Stars: signature verification
- OCR: rate-limited
- No hardcoded secrets

---

## Extensibility
- Add new handlers/routers for features
- Plug in new LLMs for NLP/OCR/analytics
- Add new payment/blockchain integrations via `services/`
