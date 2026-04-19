"""
Security utilities for input validation, signature checks, and rate limiting.
"""
import re
from typing import Any
from fastapi import HTTPException
from collections import defaultdict
from time import time

# --- Input Validation ---
def validate_text(text: str, max_len: int = 256) -> str:
    if not isinstance(text, str) or len(text) > max_len:
        raise HTTPException(400, "Invalid input length")
    # Basic XSS filter
    if re.search(r"[<>]", text):
        raise HTTPException(400, "Input contains forbidden characters")
    return text

# --- Signature Verification (TON/Stars) ---
def verify_signature(payload: Any, signature: str, public_key: str) -> bool:
    # Placeholder: implement cryptographic signature check
    # Use nacl or pyca/cryptography for real implementation
    return True

# --- Rate Limiting (in-memory, for OCR endpoint) ---
_ocr_rate_limit: dict[int, list[float]] = defaultdict(list)  # user_id -> [timestamps]

RATE_LIMIT = 5  # max 5 OCR requests per 10 min
RATE_WINDOW = 600

def check_ocr_rate_limit(user_id: int) -> None:
    now = time()
    window = _ocr_rate_limit[user_id]
    window[:] = [t for t in window if now - t < RATE_WINDOW]
    if len(window) >= RATE_LIMIT:
        raise HTTPException(429, "Too many OCR requests. Try later.")
    window.append(now)
