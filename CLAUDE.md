# CLAUDE.md — Project Context for SplitBot (Telegram Expense Tracker)

## Project Overview

SplitBot is a Telegram bot that sits in group chats, tracks shared expenses via natural language messages (e.g., "spent 34usd with everyone for dinner"), and calculates simplified debts between participants using a greedy settlement algorithm.

---

## Tech Stack

| Layer              | Technology                | Notes                                                      |
| ------------------ | ------------------------- | ---------------------------------------------------------- |
| Language           | **Python 3.10+**          | Use modern syntax: `match`, `type` unions, `str | None`.   |
| Telegram Framework | **aiogram 3.x**           | Async-first. Use routers, filters, and middleware.          |
| Database Driver    | **motor 3.x**             | Async MongoDB driver. Always use with `await`.              |
| Database           | **MongoDB 7+**            | Single database, shared-schema model (see DB rules below). |
| LLM Integration    | **OpenAI API** (or Anthropic) | For natural-language expense extraction. See `nlp_parser` agent. |
| Testing            | **pytest + pytest-asyncio**| All async handlers/services must have async test coverage.  |
| Linting            | **ruff**                  | Single tool for linting and formatting.                     |

---

## Critical Financial Rule — NO FLOATS

> **All monetary values MUST use `decimal.Decimal`. Using `float` for money is a bannable offense in this codebase.**

Binary floating-point (`float`) introduces compounding rounding errors that are unacceptable in financial calculations. Every module that touches money must follow these rules:

1. **Storage:** Monetary values are stored in MongoDB as **strings** (e.g., `"34.50"`), never as BSON `double`.
2. **Deserialization:** When reading from the database, immediately convert to `Decimal`: `Decimal(doc["amount"])`.
3. **Serialization:** When writing to the database, convert to string: `str(amount)`.
4. **LLM Output:** The NLP parser returns amounts as strings. Convert to `Decimal` at the service boundary, never inside the parser itself.
5. **Arithmetic:** Use `Decimal` for all splits, balances, and settlement calculations. Set context precision as needed:
   ```python
   from decimal import Decimal, ROUND_HALF_UP

   amount = Decimal("34.00")
   split = (amount / Decimal("3")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
   ```
6. **Validation:** A pre-commit check or linting rule should flag any literal `float(...)` cast or bare floating-point arithmetic on monetary fields.

---

## Database Rules

### Single Database, Shared Schema

All data lives in **one MongoDB database** (`splitbot`). Collections use a shared schema with strict tenant isolation via `group_id`.

#### Collections

| Collection   | Tenant Key  | Purpose                                              |
| ------------ | ----------- | ---------------------------------------------------- |
| `groups`     | `group_id`  | Group metadata, settings, default currency.          |
| `users`      | `group_id`  | Known participants per group (built passively).      |
| `expenses`   | `group_id`  | Individual expense records with split details.       |
| `settlements`| `group_id`  | Computed settlement instructions (debt simplification). |

#### Indexing Requirements

- Every query **must** include `group_id` as the first filter field.
- Create compound indexes: `{ group_id: 1, created_at: -1 }` on `expenses`.
- Create unique index: `{ group_id: 1, user_id: 1 }` on `users`.

#### Isolation Enforcement

```python
# CORRECT — always scope by group
await db.expenses.find({"group_id": group_id, "settled": False}).to_list(None)

# WRONG — never query without group_id
await db.expenses.find({"settled": False}).to_list(None)  # BUG: leaks across groups
```

---

## Telegram Interaction Rules

### User Discovery — Passive Listening Pattern

The Telegram Bot API **does not** provide an endpoint to list all members of a group chat (privacy restriction). The bot must build its user database incrementally:

1. **`new_chat_participant` / `chat_member` events:** Register users when they join the group.
2. **Active message senders:** On every incoming message, upsert the sender into the `users` collection for that `group_id`.
3. **Mentioned users in expenses:** When someone says "split with @alice and @bob", register those users if not already known.
4. **Never assume a full member list.** All UI that references "everyone" must resolve to "all known users in this group" with a disclaimer if the list might be incomplete.

### Bot Command Conventions

| Command        | Description                                      |
| -------------- | ------------------------------------------------ |
| `/start`       | Register the bot in a group; welcome message.    |
| `/balance`     | Show current balances for the calling user.       |
| `/balances`    | Show all outstanding balances in the group.       |
| `/settle`      | Compute and display simplified settlement plan.   |
| `/history`     | Show recent expenses.                             |
| `/help`        | Usage instructions.                               |

### Natural Language Handling

Any non-command message in a group where the bot is active should be passed to the NLP parser agent to attempt expense extraction. If the parser returns high confidence, confirm with the user via an inline keyboard before recording.

---

## Project Structure (Target)

```
.
├── CLAUDE.md                       # This file
├── .claude/
│   ├── skills/
│   │   └── debt_algorithm/
│   │       └── SKILL.md            # Greedy debt simplification algorithm
│   └── agents/
│       └── nlp_parser.md           # LLM subagent for expense extraction
├── bot/
│   ├── __init__.py
│   ├── main.py                     # Entrypoint: polling / webhook setup
│   ├── config.py                   # Settings via pydantic-settings
│   ├── handlers/                   # aiogram routers
│   │   ├── commands.py
│   │   └── messages.py
│   ├── services/                   # Business logic
│   │   ├── expense_service.py
│   │   ├── balance_service.py
│   │   └── settlement_service.py   # Implements SKILL.md algorithm
│   ├── models/                     # Pydantic models / DB schemas
│   │   ├── expense.py
│   │   ├── user.py
│   │   └── group.py
│   ├── db/                         # motor connection & repository layer
│   │   ├── connection.py
│   │   └── repositories.py
│   └── nlp/                        # LLM integration
│       └── parser.py               # Implements nlp_parser agent spec
├── tests/
│   ├── conftest.py
│   ├── test_settlement.py
│   ├── test_parser.py
│   └── test_handlers.py
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Development Commands

```bash
# Install dependencies (use a virtual environment)
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
.venv\Scripts\activate             # Windows
pip install -e ".[dev]"

# Run the bot locally (polling mode)
python -m bot.main

# Run tests
pytest tests/ -v --asyncio-mode=auto

# Run tests with coverage
pytest tests/ -v --asyncio-mode=auto --cov=bot --cov-report=term-missing

# Lint and format
ruff check .
ruff format .

# Lint and auto-fix
ruff check . --fix

# Type checking (optional but recommended)
mypy bot/ --strict
```

---

## Environment Variables

| Variable              | Required | Description                          |
| --------------------- | -------- | ------------------------------------ |
| `TELEGRAM_BOT_TOKEN`  | Yes      | Bot token from @BotFather.           |
| `MONGODB_URI`         | Yes      | MongoDB connection string.           |
| `MONGODB_DB_NAME`     | No       | Defaults to `splitbot`.              |
| `OPENAI_API_KEY`      | Yes      | API key for LLM expense extraction.  |
| `LOG_LEVEL`           | No       | Defaults to `INFO`.                  |

---

## Code Style & Conventions

- **Async everywhere.** No blocking I/O in the event loop. Use `motor` for DB, `aiohttp`/`httpx` for HTTP.
- **Type hints required** on all function signatures.
- **Pydantic models** for all data crossing boundaries (API responses, DB documents, LLM outputs).
- **No bare `except`.** Always catch specific exceptions.
- **Logging over print.** Use `structlog` or stdlib `logging`.
- **Secrets in `.env` only.** Never commit tokens or keys.
