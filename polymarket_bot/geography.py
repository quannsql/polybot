from __future__ import annotations

import re
from typing import Any


# API restrictions, reviewed 2026-11-09:
# https://docs.polymarket.com/api-reference/geoblock
# NL/IE/JP/MT/KR are frontend-only restrictions in that document. The live
# endpoint must still explicitly return blocked=false; this is no override.
NO_NEW_ORDERS = {
    "AR", "AU", "BE", "BY", "BR", "BI", "CF", "CD", "CU", "DE", "ET", "FR",
    "GB", "IR", "IQ", "IT", "KP", "LB", "LY", "MM",
    "NI", "NZ", "PL", "RU", "SG", "SK", "SO", "SS", "SD", "SY",
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
    if country in {'CA', 'UA'} and (not isinstance(region, str) or not region):
        return {"status": "unknown", "new_order_network_check": False,
                "reason": "missing region for country with regional restrictions"}
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
