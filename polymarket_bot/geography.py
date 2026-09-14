from __future__ import annotations

import re
from typing import Any


# Fail-closed snapshot from the official availability page (2026-09-14).
NO_NEW_ORDERS = {
    "AU", "BE", "BY", "BR", "BI", "CF", "CD", "CU", "DE", "ET", "FR",
    "GB", "IE", "IR", "IQ", "IT", "JP", "KP", "LB", "LY", "MM", "MT",
    "NI", "NL", "NZ", "PL", "RU", "SG", "SK", "SO", "SS", "SD", "SY",
    "TW", "TH", "UM", "US", "VE", "YE", "ZW",
}


def geographic_check(payload: Any) -> dict[str, Any]:
    """Require both a valid endpoint result and an allowed published region."""
    if not isinstance(payload, dict) or type(payload.get("blocked")) is not bool:
        return {"status": "unknown", "new_order_network_check": False,
                "reason": "invalid geoblock response"}
    country, region = payload.get("country"), payload.get("region")
    if not isinstance(country, str) or not re.fullmatch("[A-Z]{2}", country):
        return {"status": "unknown", "new_order_network_check": False,
                "reason": "missing country"}
    restricted_region = (
        (country == "CA" and region in {"AB", "BC", "ON", "QC"})
        or (country == "UA" and region in {"43", "14", "09"})
    )
    blocked = payload["blocked"] or country in NO_NEW_ORDERS or restricted_region
    return {
        "status": "blocked_or_close_only" if blocked else "network_check_passed",
        "country": country,
        "region": region,
        "new_order_network_check": not blocked,
        "note": "Network check is not user/account/legal eligibility.",
    }
