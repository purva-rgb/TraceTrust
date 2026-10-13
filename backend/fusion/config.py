"""Single source of truth for deterministic evidence fusion."""
from __future__ import annotations

RULE_VERSION = "rules-v1"
FUSION_VERSION = "fusion-v1"
PROFILE = "sealed_only"

TRUST = {
    "DEVICE": 0.80,
    "WITNESSED_STAFF": 0.70,
    "APP": 0.40,
    "ANON": 0.10,
    "INVALID_SIG": 0.0,
    "CRYPTO_FAILURE": 1.0,
    "INTERRUPTED_OPERATION": 0.80,
    "INDEPENDENT_CORROBORATION": 0.70,
    "CONSISTENCY_CHECK": 0.80,
}

CLONED_QR_WEIGHTS = {
    "movement_conflict": 0.50,
    "duplicate_burst": 0.30,
    "concurrent_receipt": 0.20,
}
SUBSTITUTION_SEALED_ONLY = {
    "box_mismatch": 0.35,
    "seal_id_mismatch": 0.35,
    "unexpected_seal_broken": 0.30,
}
SUBSTITUTION_FULL_INSPECTION = {
    "laptop_serial": 0.45,
    "box_mismatch": 0.25,
    "unexpected_seal_broken": 0.20,
    "seal_id_mismatch": 0.10,
}
DIVERSION_WEIGHTS = {
    "custody_mismatch": 0.45,
    "handover_mismatch": 0.35,
    "prohibited_route_or_sold_reentry": 0.20,
}
TAMPER_WEIGHTS = {
    "anchor_mismatch": 0.60,
    "event_integrity": 0.40,
}
PROCESS_RECORDING_GAP_WEIGHTS = {
    "interrupted_operation": 0.35,
    "independent_corroboration": 0.40,
    "consistency_check": 0.25,
}

WEIGHTS = {
    "sealed_only": {
        "CLONED_QR": CLONED_QR_WEIGHTS,
        "DEVICE_OR_PACKAGE_SUBSTITUTION": SUBSTITUTION_SEALED_ONLY,
        "DIVERSION_OR_GRAY_MARKET": DIVERSION_WEIGHTS,
        "RECORD_TAMPERING": TAMPER_WEIGHTS,
    },
    "full_inspection": {
        "CLONED_QR": CLONED_QR_WEIGHTS,
        "DEVICE_OR_PACKAGE_SUBSTITUTION": SUBSTITUTION_FULL_INSPECTION,
        "DIVERSION_OR_GRAY_MARKET": DIVERSION_WEIGHTS,
        "RECORD_TAMPERING": TAMPER_WEIGHTS,
    },
}

CAUSES = (
    "CLONED_QR",
    "DEVICE_OR_PACKAGE_SUBSTITUTION",
    "DIVERSION_OR_GRAY_MARKET",
    "RECORD_TAMPERING",
)

CAUSE_LABELS = {
    "CLONED_QR": "Cloned QR",
    "DEVICE_OR_PACKAGE_SUBSTITUTION": "Device or package substitution",
    "DIVERSION_OR_GRAY_MARKET": "Diversion or gray market",
    "RECORD_TAMPERING": "Record tampering",
    "PROCESS_RECORDING_GAP": "Process/recording gap",
}

CLASS_TO_CAUSE = {
    evidence_class: cause
    for cause, weights in WEIGHTS["full_inspection"].items()
    for evidence_class in weights
}

INSUFFICIENT_BELOW = 0.35
AMBIGUOUS_GAP = 0.10
SPEED_KMH = 900.0
MIN_DISTANCE_KM = 50.0
BURST_WINDOW_MS = 5 * 1000
RECEIPT_CONFLICT_WINDOW_MS = 10 * 60 * 1000
BURST_MIN_DEVICES = 3
GPS_ACCURACY_PENALTY_KM = 10.0
CORRECTION_PENALTY = 0.25
PROCESS_GAP_CONTRADICTION = 0.40
PROCESS_GAP_CONTRADICTION_RULES = frozenset(
    {
        "BOX_MISMATCH",
        "SEAL_ID_MISMATCH",
        "HANDOVER_MISMATCH",
        "CONCURRENT_RECEIPT_CONFLICT",
        "SIGNATURE_INVALID",
        "HASH_INVALID",
        "SEQUENCE_INVALID",
        "ANCHOR_MISMATCH",
    }
)
INCIDENT_WINDOW_MS = 24 * 60 * 60 * 1000
INCIDENT_ALERT_CAP = 100

SHARED_FAILURE_CLASSES = frozenset(
    {
        "box_mismatch",
        "seal_id_mismatch",
        "unexpected_seal_broken",
        "handover_mismatch",
        "custody_mismatch",
        "laptop_serial",
        "concurrent_receipt",
    }
)

INSPECTION_METHODS = frozenset({"PACKING", "SEALED", "OPENED", "REPLACEMENT", "STAFF"})
