from __future__ import annotations

import math
from typing import Any

EARTH_KM = 6371.0
DEFAULT_RADIUS_KM = 50.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlon1, rlat2, rlon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    chord = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(min(1.0, chord)))


def location_check(
    gps: dict[str, Any] | None,
    warehouse_lat: float | None,
    warehouse_lng: float | None,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> str:
    if (
        not gps
        or gps.get("gps_status") != "CAPTURED"
        or gps.get("gps_lat_e7") is None
        or gps.get("gps_lng_e7") is None
        or warehouse_lat is None
        or warehouse_lng is None
    ):
        return "UNAVAILABLE"
    distance = haversine_km(
        gps["gps_lat_e7"] / 10_000_000,
        gps["gps_lng_e7"] / 10_000_000,
        float(warehouse_lat),
        float(warehouse_lng),
    )
    return "WITHIN_RADIUS" if distance <= radius_km else "OUTSIDE_RADIUS"
