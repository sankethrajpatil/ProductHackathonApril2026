# Security & Compliance — SplitBot

## Financial Safety
- **NO FLOATS:** All monetary values use `decimal.Decimal`, stored as strings
- **Strict tenant isolation:** All queries scoped by `group_id`

## Input Validation
- All user input validated for length and forbidden characters
- XSS/injection protection on all endpoints

## Web3/Payments
- TON/Stars endpoints require cryptographic signature verification
- On-chain settlements are verified before recording

## Rate Limiting
- OCR endpoint is rate-limited per user (max 5 per 10 min)
- Anti-abuse logic for sensitive endpoints

## Secrets
- No hardcoded secrets; all credentials in `.env`
- GitHub Actions checks for hardcoded secrets on every push

## CI/CD
- Lint, type check, and test suite run on every push
- Deployment blocked if any check fails
