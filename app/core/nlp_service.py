import json
import logging
import os
from typing import TypedDict

import httpx

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a structured-data extraction agent. Your sole job is to read a single \
chat message and return a JSON object describing the expense.

Rules:
- "amount" MUST be a string with two decimal places (e.g. "34.00"), NEVER a number.
- "currency" is an ISO 4217 code, uppercase. Default to "USD" if ambiguous.
- "split_type" is "everyone" or "specific".
- "participants" lists @usernames (without @) only when split_type is "specific".
- If the message is NOT an expense, set is_expense to false and all other fields to null.
- Return ONLY the raw JSON object. No markdown, no commentary.

Output schema:
{"is_expense": bool, "amount": str|null, "currency": str|null, "description": str|null, "split_type": str|null, "participants": list|null}
"""


class ParsedExpense(TypedDict):
    is_expense: bool
    amount: str | None
    currency: str | None
    description: str | None
    split_type: str | None
    participants: list[str] | None


async def parse_expense(text: str) -> ParsedExpense | None:
    """Send a message to the LLM and extract structured expense data.

    Returns the parsed dict on success, or None if the LLM call fails or
    the message is not an expense.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY is not set")
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("OpenAI API request failed: %s", exc)
        return None

    try:
        body = resp.json()
        content: str = body["choices"][0]["message"]["content"]
        # Strip markdown fences if the model wraps them anyway
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        parsed: ParsedExpense = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.error("Failed to parse LLM response: %s", exc)
        return None

    if not parsed.get("is_expense"):
        return None

    # Validate required fields are present
    if not parsed.get("amount") or not parsed.get("currency"):
        logger.warning("LLM returned expense without amount/currency: %s", parsed)
        return None

    return parsed
