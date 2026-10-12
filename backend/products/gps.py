from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.crypto.canonical import GPS_STATUSES, normalize_gps

LAT_MIN, LAT_MAX = -90.0, 90.0
LNG_MIN, LNG_MAX = -180.0, 180.0
LAT_E7_MAX = 900_000_000
LNG_E7_MAX = 1_800_000_000


class GpsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gps_status: Literal["CAPTURED", "DENIED", "UNAVAILABLE", "NOT_REQUESTED"] = "NOT_REQUESTED"
    latitude: float | None = None
    longitude: float | None = None
    gps_lat_e7: int | None = None
    gps_lng_e7: int | None = None
    gps_accuracy_cm: int | None = Field(default=None, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "GpsIn":
        if self.latitude is not None:
            if self.latitude != self.latitude or abs(self.latitude) == float("inf"):
                raise ValueError("invalid latitude")
            if not (LAT_MIN <= self.latitude <= LAT_MAX):
                raise ValueError("invalid latitude")
        if self.longitude is not None:
            if self.longitude != self.longitude or abs(self.longitude) == float("inf"):
                raise ValueError("invalid longitude")
            if not (LNG_MIN <= self.longitude <= LNG_MAX):
                raise ValueError("invalid longitude")
        if self.gps_lat_e7 is not None and not (-LAT_E7_MAX <= self.gps_lat_e7 <= LAT_E7_MAX):
            raise ValueError("invalid latitude")
        if self.gps_lng_e7 is not None and not (-LNG_E7_MAX <= self.gps_lng_e7 <= LNG_E7_MAX):
            raise ValueError("invalid longitude")
        if self.gps_status == "CAPTURED":
            has_decimal = self.latitude is not None and self.longitude is not None
            has_e7 = self.gps_lat_e7 is not None and self.gps_lng_e7 is not None
            if not has_decimal and not has_e7:
                raise ValueError("CAPTURED GPS requires latitude and longitude")
        return self


def gps_to_canonical(gps: GpsIn | None) -> dict[str, Any]:
    if gps is None:
        return normalize_gps({"gps_status": "NOT_REQUESTED"})
    lat_e7 = gps.gps_lat_e7
    lng_e7 = gps.gps_lng_e7
    if gps.latitude is not None:
        lat_e7 = round(gps.latitude * 10_000_000)
    if gps.longitude is not None:
        lng_e7 = round(gps.longitude * 10_000_000)
    if gps.gps_status not in GPS_STATUSES:
        raise ValueError("invalid gps_status")
    return normalize_gps(
        {
            "gps_status": gps.gps_status,
            "gps_source": "CLIENT_REPORTED",
            "gps_lat_e7": lat_e7,
            "gps_lng_e7": lng_e7,
            "gps_accuracy_cm": gps.gps_accuracy_cm,
        }
    )
