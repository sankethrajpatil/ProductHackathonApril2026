# SplitBot — Telegram Group Expense Tracker

SplitBot is a next-generation Telegram bot for group expense tracking, powered by AI, Web3, and enterprise-grade security. It supports natural language expense entry, OCR receipt scanning, on-chain settlements (TON), Telegram Stars monetization, and conversational analytics.

---

## Features

### 1. **Natural Language Expense Tracking**
- Add expenses in plain language (e.g., "spent 34usd with everyone for dinner").
- NLP parser extracts amount, currency, participants, and description.
- Supports multi-currency and automatic currency conversion.

### 2. **Greedy Debt Simplification**
- Computes minimal settlement instructions using a mathematically sound greedy algorithm.
- No pennies lost: all calculations use `decimal.Decimal` (never float).
- Transparent group balances and settlement suggestions.

### 3. **Web3/TON Blockchain Settlement**
- Seamless TON Connect wallet integration in the TMA dashboard.
- Settle debts on-chain with one click; bot verifies TON transactions via Toncenter API.
- All on-chain settlements are recorded and visible in group history.

### 4. **Telegram Stars Monetization**
- Premium features unlockable via Telegram Stars (XTR) in-app payments.
- `/premium` command shows features and buy button; payment auto-approves and upgrades user.

### 5. **Receipt OCR (AI Vision)**
- Upload a photo or PDF of a physical receipt; bot extracts total, currency, and description using Vision LLM OCR (Claude 3.5 or GPT-4o).
- User is prompted for confirmation if extraction is uncertain.
- Strict financial rules: all amounts cast to `decimal.Decimal` before saving.
- Rate-limited to prevent abuse.

### 6. **Conversational Financial Analytics**
- Ask questions like "How much did we spend on food this month?" or "What's our biggest expense?" using `/analytics` command.
- Secure, read-only aggregation: LLM never executes raw DB queries.
- Natural language answers based on group data.

### 7. **Enterprise Security & Compliance**
- Strict input validation (XSS/injection protection) on all endpoints.
- TON/Stars endpoints require cryptographic signature verification.
- Rate limiting and anti-abuse for OCR and sensitive endpoints.
- No hardcoded secrets; all credentials via `.env`.

### 8. **CI/CD & Automated Testing**
- GitHub Actions workflow: runs tests, lint, type checks, and secrets scan on every push.
- Comprehensive test suite for debt simplification and financial logic.

---

## Getting Started

1. **Clone & Install**
	```bash
	git clone https://github.com/sankethrajpatil/ProductHackathonApril2026.git
	cd ProductHackathonApril2026
	python -m venv .venv
	source .venv/bin/activate  # or .venv\Scripts\activate on Windows
	pip install -e ".[dev]"
	```

2. **Configure Environment**
	- Copy `.env.example` to `.env` and fill in your credentials (Telegram Bot Token, MongoDB URI, OpenAI API Key, etc).

3. **Run Locally**
	```bash
	python -m app.main
	# or for Vercel serverless:
	vercel dev
	```

4. **Run Tests & Lint**
	```bash
	pytest tests/ --asyncio-mode=auto
	ruff check .
	mypy bot/ --strict
	```

5. **Set Telegram Webhook for Vercel**
	```bash
	python scripts/set_webhook.py
	```
	- Uses `BOT_TOKEN` and optional `TELEGRAM_WEBHOOK_SECRET` from environment.
	- Webhook endpoint is fixed to:
	  `https://splitbot-lilac.vercel.app/api/webhook`

---

## Project Structure

```
app/
  handlers/           # aiogram routers (commands, OCR, analytics, etc)
  services/           # Business logic (NLP, OCR, blockchain, etc)
  core/               # DB, analytics agent, security, middlewares
  models/             # Pydantic models
  db/                 # MongoDB connection
webapp/               # Telegram Mini App frontend (TMA dashboard)
api/                  # Vercel serverless endpoints
.github/workflows/    # CI/CD pipeline
```

---

## Security & Financial Rules
- **NO FLOATS for money.** All monetary values use `decimal.Decimal` and are stored as strings in MongoDB.
- **Strict tenant isolation:** All queries are scoped by `group_id`.
- **No raw LLM DB access:** Analytics agent only exposes predefined, read-only aggregations.
- **Input validation:** All user input is sanitized and validated.

---

## License
MIT