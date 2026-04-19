"""
OCR Service — integrates with Vision LLM or OCR API to extract receipt data.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any
import httpx
import os

class OCRConfidenceError(Exception):
    pass

class OCRService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("VISION_MODEL", "gpt-4o")

    async def extract_receipt(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Returns: dict with keys: total_amount (str), currency (str), description (str), confidence (float)
        Raises OCRConfidenceError if extraction is low confidence.
        """
        # Example: OpenAI Vision API (replace with Claude if needed)
        prompt = (
            "Extract the total amount, currency, and a short description from this receipt image. "
            "Return JSON: {total_amount, currency, description, confidence (0-1)}. "
            "If unsure, set confidence < 0.7."
        )
        headers = {"Authorization": f"Bearer {self.api_key}"}
        files = {"file": ("receipt.jpg", image_bytes, "image/jpeg")}
        data = {"model": self.model, "prompt": prompt}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/vision/analyze", headers=headers, data=data, files=files
            )
            resp.raise_for_status()
            result = resp.json()
        # Parse result
        try:
            out = result["choices"][0]["message"]["content"]
            parsed = self._parse_json(out)
            if float(parsed.get("confidence", 0)) < 0.7:
                raise OCRConfidenceError("Low confidence in OCR extraction")
            # Strict Decimal cast
            parsed["total_amount"] = str(Decimal(parsed["total_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            return parsed
        except Exception as e:
            raise OCRConfidenceError(f"Failed to extract: {e}")

    def _parse_json(self, text: str) -> dict:
        import json
        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError("No JSON found in LLM output")
        return json.loads(m.group(0))
