"""Backend-derived trust. Client-supplied trust is ignored."""
from __future__ import annotations

from backend.fusion.config import GPS_ACCURACY_PENALTY_KM, INSPECTION_METHODS, TRUST


def derive_trust(
    *,
    authenticated: bool = False,
    device_registered: bool = False,
    signature_valid: bool | None = None,
    inspection_method: str | None = None,
    accuracy_km: float | None = None,
    client_trust: float | None = None,
) -> dict:
    del client_trust
    if signature_valid is False:
        identity = location = inspection = TRUST["INVALID_SIG"]
        source = "INVALID_SIG"
        exclude_location = True
    elif device_registered and signature_valid is True:
        identity = location = inspection = TRUST["DEVICE"]
        source = "DEVICE"
        exclude_location = False
    elif authenticated and inspection_method in INSPECTION_METHODS:
        identity = location = inspection = TRUST["WITNESSED_STAFF"]
        source = "WITNESSED_STAFF"
        exclude_location = False
    elif authenticated:
        identity = location = inspection = TRUST["APP"]
        source = "APP"
        exclude_location = False
    else:
        identity = location = inspection = TRUST["ANON"]
        source = "ANON"
        exclude_location = False
    if accuracy_km is not None and float(accuracy_km) > GPS_ACCURACY_PENALTY_KM:
        location = location * 0.5
    return {
        "source": source,
        "identity_trust": identity,
        "location_trust": location,
        "inspection_trust": inspection,
        "exclude_location": exclude_location,
    }
