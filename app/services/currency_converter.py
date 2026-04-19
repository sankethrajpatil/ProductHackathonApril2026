import logging
import os
from decimal import Decimal, ROUND_HALF_UP

import httpx

logger = logging.getLogger(__name__)

# In-memory cache: {("USD","EUR"): (rate, timestamp)}
_cache: dict[tuple[str, str], tuple[Decimal, float]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal | None:
    """Fetch the live exchange rate from_currency → to_currency.

    Uses ExchangeRate-API (free tier: 1500 req/month).
    Returns the rate as Decimal, or None on failure.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return Decimal("1")

    # --- Check cache -------------------------------------------------------
    import time
    cache_key = (from_currency, to_currency)
    if cache_key in _cache:
        rate, ts = _cache[cache_key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            logger.debug("Cache hit for %s→%s: %s", from_currency, to_currency, rate)
            return rate

    # --- Fetch from API ----------------------------------------------------
    api_key = os.getenv("EXCHANGE_RATE_API_KEY", "")
    if api_key:
        url = (
            f"https://v6.exchangerate-api.com/v6/{api_key}"
            f"/pair/{from_currency}/{to_currency}"
        )
    else:
        # Free fallback (no key required, lower limits)
        url = (
            f"https://open.er-api.com/v6/latest/{from_currency}"
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.error("Exchange rate API request failed: %s", exc)
        return None

    try:
        if api_key:
            # v6 pair endpoint: {"conversion_rate": 0.92}
            raw_rate = data["conversion_rate"]
        else:
            # open.er-api.com: {"rates": {"EUR": 0.92, ...}}
            raw_rate = data["rates"][to_currency]

        # Convert to Decimal via string to avoid float contamination
        rate = Decimal(str(raw_rate)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    except (KeyError, TypeError, ValueError) as exc:
        logger.error("Failed to parse exchange rate response: %s", exc)
        return None

    # --- Update cache ------------------------------------------------------
    _cache[cache_key] = (rate, time.time())
    logger.info("Exchange rate %s→%s = %s (cached)", from_currency, to_currency, rate)
    return rate


async def convert_amount(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
) -> tuple[Decimal, Decimal] | None:
    """Convert an amount from one currency to another.

    Returns (converted_amount, rate) on success, or None if the rate lookup fails.
    Both values are Decimal — no floats.
    """
    rate = await get_exchange_rate(from_currency, to_currency)
    if rate is None:
        return None

    converted = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return converted, rate
