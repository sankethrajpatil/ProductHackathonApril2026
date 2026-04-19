"""
Conversational Analytics Agent — secure, read-only Q&A over group expenses.
"""
from typing import Any, Dict
from decimal import Decimal
from app.core.database import get_db
import os
import httpx

class AnalyticsAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("ANALYTICS_MODEL", "gpt-4o")

    async def answer(self, group_id: int, query: str) -> str:
        """
        Handles user analytics questions by running predefined aggregations and passing results to LLM.
        """
        data = await self._aggregate_data(group_id)
        prompt = (
            f"Given this group expense data: {data}\n"
            f"Answer the user's question: '{query}'.\n"
            "Respond conversationally, but do not hallucinate numbers."
        )
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 256,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def _aggregate_data(self, group_id: int) -> Dict[str, Any]:
        db = get_db()
        # Only allow predefined, read-only aggregations
        pipeline = [
            {"$match": {"group_id": group_id}},
            {"$group": {
                "_id": "$category",  # Assume category field exists
                "total": {"$sum": {"$toDecimal": "$amount"}},
                "count": {"$sum": 1},
            }},
        ]
        expenses = await db.expenses.aggregate(pipeline).to_list(None)
        return expenses
