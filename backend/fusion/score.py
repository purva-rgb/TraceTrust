"""Pure, order-independent evidence fusion."""
from __future__ import annotations

from backend.fusion.config import (
    AMBIGUOUS_GAP,
    CAUSE_LABELS,
    CAUSES,
    CORRECTION_PENALTY,
    FUSION_VERSION,
    INSUFFICIENT_BELOW,
    PROCESS_GAP_CONTRADICTION,
    PROCESS_GAP_CONTRADICTION_RULES,
    PROCESS_RECORDING_GAP_WEIGHTS,
    PROFILE,
    WEIGHTS,
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _alert_key(alert: dict) -> tuple:
    return (
        str(alert.get("evidence_class") or ""),
        str(alert.get("rule_code") or ""),
        str(alert.get("dedupe_key") or alert.get("id") or ""),
        int(alert.get("event_time_ms") or 0),
    )


def support_line(cause: str, score: float) -> str:
    points = int(round(score * 100))
    if cause == "PROCESS_RECORDING_GAP":
        return f"Process/recording gap: {points}/100 explanation support"
    return f"{CAUSE_LABELS.get(cause, cause)}: {points}/100 evidence support"


def _process_gap(alerts: list[dict], best: dict[str, float], support_ids: dict[str, list[str]], reasons: dict[str, list[str]]) -> dict:
    has_gap = any(alert.get("rule_code") == "CUSTODY_DOCUMENTATION_GAP" for alert in alerts)
    ids: list[str] = []
    cause_reasons: list[str] = []
    raw = 0.0
    if has_gap:
        for evidence_class, weight in PROCESS_RECORDING_GAP_WEIGHTS.items():
            raw += weight * best.get(evidence_class, 0.0)
            if best.get(evidence_class, 0.0) > 0:
                ids.extend(support_ids.get(evidence_class, []))
                cause_reasons.extend(reasons.get(evidence_class, []))
        if any(alert.get("rule_code") in PROCESS_GAP_CONTRADICTION_RULES for alert in alerts):
            raw -= PROCESS_GAP_CONTRADICTION
        for alert in alerts:
            if alert.get("rule_code") == "CUSTODY_DOCUMENTATION_GAP" and alert.get("reason"):
                cause_reasons.append(alert["reason"])
    score = round(_clamp(raw), 10)
    if score < INSUFFICIENT_BELOW:
        outcome = "INSUFFICIENT_EVIDENCE"
        requires_review = False
    else:
        outcome = "LEADING"
        requires_review = True
    return {
        "cause": "PROCESS_RECORDING_GAP",
        "label": CAUSE_LABELS["PROCESS_RECORDING_GAP"],
        "support_score": score,
        "support_points": int(round(score * 100)),
        "supporting_alert_ids": sorted(set(ids)),
        "reasons": sorted(set(cause_reasons)),
        "outcome": outcome,
        "requires_investigator_review": requires_review,
        "has_documentation_gap": has_gap,
        "explanation": (
            f"{support_line('PROCESS_RECORDING_GAP', score)}. "
            "Documentation incomplete"
            + (", investigator review required." if requires_review else ".")
        ),
    }


def fuse(
    alerts: list[dict],
    *,
    profile: str | None = None,
    missing_checks: list[str] | None = None,
    authorized_opening: bool = False,
    validated_corrections: list[str] | None = None,
) -> dict:
    chosen = profile or PROFILE
    weights = WEIGHTS[chosen]
    corrections = set(validated_corrections or [])
    ordered = sorted(alerts, key=_alert_key)
    best: dict[str, float] = {}
    support_ids: dict[str, list[str]] = {}
    reasons: dict[str, list[str]] = {}
    simulated = False
    for alert in ordered:
        if alert.get("is_simulated"):
            simulated = True
        evidence_class = alert.get("evidence_class")
        if not evidence_class:
            continue
        if authorized_opening and evidence_class == "unexpected_seal_broken":
            continue
        strength = float(alert.get("strength") or 0)
        if strength <= 0:
            continue
        value = float(alert.get("trust") or 0) * strength
        if value <= 0:
            continue
        previous = best.get(evidence_class, 0.0)
        if value > previous:
            best[evidence_class] = value
        alert_id = str(alert.get("id") or alert.get("dedupe_key"))
        support_ids.setdefault(evidence_class, [])
        if alert_id not in support_ids[evidence_class]:
            support_ids[evidence_class].append(alert_id)
        if alert.get("reason") and alert["reason"] not in reasons.setdefault(evidence_class, []):
            reasons[evidence_class].append(alert["reason"])
    by_cause: dict[str, float] = {}
    hypotheses = []
    for cause in CAUSES:
        raw = 0.0
        ids: list[str] = []
        cause_reasons: list[str] = []
        for evidence_class, weight in weights[cause].items():
            raw += weight * best.get(evidence_class, 0.0)
            if best.get(evidence_class, 0.0) > 0:
                ids.extend(support_ids.get(evidence_class, []))
                cause_reasons.extend(reasons.get(evidence_class, []))
        if cause in corrections:
            raw -= CORRECTION_PENALTY
        score = round(_clamp(raw), 10)
        by_cause[cause] = score
        hypotheses.append(
            {
                "cause": cause,
                "label": CAUSE_LABELS[cause],
                "support_score": score,
                "support_points": int(round(score * 100)),
                "supporting_alert_ids": sorted(set(ids)),
                "reasons": sorted(set(cause_reasons)),
            }
        )
    ranked = sorted(hypotheses, key=lambda item: (-item["support_score"], item["cause"]))
    highest = ranked[0]["support_score"] if ranked else 0.0
    second = ranked[1]["support_score"] if len(ranked) > 1 else 0.0
    if highest < INSUFFICIENT_BELOW:
        outcome = "INSUFFICIENT_EVIDENCE"
        requires_review = False
    elif highest - second < AMBIGUOUS_GAP:
        outcome = "AMBIGUOUS"
        requires_review = True
    else:
        outcome = "LEADING"
        requires_review = True
    process = _process_gap(ordered, best, support_ids, reasons)
    by_cause["PROCESS_RECORDING_GAP"] = process["support_score"]
    if process["support_score"] >= INSUFFICIENT_BELOW and highest >= INSUFFICIENT_BELOW:
        if abs(process["support_score"] - highest) < AMBIGUOUS_GAP:
            process["outcome"] = "AMBIGUOUS"
    positive = [item for item in ranked if item["support_score"] > 0]
    return {
        "fusion_version": FUSION_VERSION,
        "profile": chosen,
        "outcome": outcome,
        "hypotheses": positive,
        "by_cause": by_cause,
        "leading": positive[0] if positive else None,
        "runner_up": positive[1] if len(positive) > 1 else None,
        "missing_checks": sorted(set(missing_checks or [])),
        "requires_investigator_review": requires_review,
        "is_simulated": simulated,
        "process_recording_gap": process,
    }
