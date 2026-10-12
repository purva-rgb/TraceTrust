"""Evaluation set. These expected scores are fixed; do not retune them."""
from __future__ import annotations

import json

import pytest

from backend.fusion.engine import analyze
from backend.fusion.scenarios import anonymous_clone, registered_clone, scan, staff_inspection
from backend.fusion.score import support_line


def _words(result: dict) -> str:
    return json.dumps(result).lower()


def test_registered_clone_three_devices_is_0_64() -> None:
    evaluation, result = analyze(scans=registered_clone(3))
    assert result["by_cause"]["CLONED_QR"] == pytest.approx(0.64)
    assert result["outcome"] == "LEADING"
    assert support_line("CLONED_QR", result["by_cause"]["CLONED_QR"]) == "Cloned QR: 64/100 evidence support"
    assert {item["rule_code"] for item in evaluation.alerts} >= {"IMPOSSIBLE_TRAVEL", "DUPLICATE_BURST"}
    assert "probability" not in _words(result)
    assert "counterfeit" not in _words(result)
    assert "SCAN_AFTER_SOLD" not in {item["rule_code"] for item in evaluation.alerts}


def test_two_registered_devices_is_0_40() -> None:
    _evaluation, result = analyze(scans=registered_clone(2))
    assert result["by_cause"]["CLONED_QR"] == pytest.approx(0.40)
    assert result["outcome"] == "LEADING"


def test_anonymous_clone_is_insufficient() -> None:
    evaluation, result = analyze(scans=anonymous_clone(client_trust=1))
    assert result["by_cause"]["CLONED_QR"] == pytest.approx(0.05)
    assert result["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert result["requires_investigator_review"] is False
    assert max(item["trust"] for item in evaluation.alerts) == pytest.approx(0.10)
    assert "DUPLICATE_BURST" not in {item["rule_code"] for item in evaluation.alerts}


def test_staff_box_and_seal_then_broken() -> None:
    _evaluation, sealed = analyze(inspections=[staff_inspection()])
    assert sealed["by_cause"]["DEVICE_OR_PACKAGE_SUBSTITUTION"] == pytest.approx(0.49)
    _evaluation, broken = analyze(inspections=[staff_inspection(broken=True)])
    assert broken["by_cause"]["DEVICE_OR_PACKAGE_SUBSTITUTION"] == pytest.approx(0.70)
    assert "SERIAL_MISMATCH" not in {item["rule_code"] for item in _evaluation.alerts}
    assert "laptop_serial" in broken["missing_checks"]


def test_handover_and_custody_is_0_56() -> None:
    scans = [
        scan(
            "staff-scan",
            scanner_org_id=9,
            custodian_org_id=3,
            authenticated=True,
            inspection_method="SEALED",
            gps_status="NOT_REQUESTED",
            lat=None,
            lng=None,
        )
    ]
    transfers = [
        {
            "kind": "handover_mismatch",
            "evidence_id": "handover-1",
            "product_uid": "prod-eval",
            "event_time_ms": 0,
            "authenticated": True,
            "inspection_method": "SEALED",
            "is_simulated": True,
        }
    ]
    _evaluation, result = analyze(scans=scans, transfers=transfers)
    assert result["by_cause"]["DIVERSION_OR_GRAY_MARKET"] == pytest.approx(0.56)


def test_anchor_then_signature() -> None:
    anchor = {"product_uid": "prod-eval", "kind": "anchor", "confirmed": True, "evidence_id": "anchor-1", "event_time_ms": 0}
    signature = {"product_uid": "prod-eval", "kind": "signature", "evidence_id": "sig-1", "event_time_ms": 0}
    _evaluation, anchor_only = analyze(digital=[anchor])
    assert anchor_only["by_cause"]["RECORD_TAMPERING"] == pytest.approx(0.60)
    _evaluation, both = analyze(digital=[anchor, signature])
    assert both["by_cause"]["RECORD_TAMPERING"] == pytest.approx(1.0)


def test_normal_movement_postsale_and_expected_recipient_have_no_alerts() -> None:
    from backend.fusion.scenarios import MUMBAI, PUNE

    movement = [
        scan("a", lat=PUNE[0], lng=PUNE[1], event_time_ms=0, device_id="d1", device_registered=True, signature_valid=True),
        scan(
            "b",
            lat=MUMBAI[0],
            lng=MUMBAI[1],
            event_time_ms=4 * 60 * 60 * 1000,
            device_id="d2",
            device_registered=True,
            signature_valid=True,
        ),
    ]
    post_sale = [scan("buyer", lat=MUMBAI[0], lng=MUMBAI[1], lifecycle_state="SOLD")]
    recipient = [
        scan(
            "receipt",
            scanner_org_id=5,
            custodian_org_id=1,
            expected_recipient_org_id=5,
            authenticated=True,
            inspection_method="SEALED",
            gps_status="NOT_REQUESTED",
            lat=None,
            lng=None,
        )
    ]
    for scans in (movement, post_sale, recipient):
        evaluation, result = analyze(scans=scans)
        assert evaluation.alerts == []
        assert result["by_cause"]["CLONED_QR"] == 0
        assert "SCAN_AFTER_SOLD" not in {item["rule_code"] for item in evaluation.alerts}


def test_duplicate_inputs_and_anonymous_flood_do_not_change_score() -> None:
    _first, quiet = analyze(scans=anonymous_clone())
    flood = anonymous_clone() + [
        scan(f"flood-{index}", lat=float(index), lng=float(index), event_time_ms=index * 1000, client_trust=1)
        for index in range(40)
    ]
    _second, noisy = analyze(scans=flood)
    assert quiet["by_cause"] == noisy["by_cause"]
    assert quiet["by_cause"]["CLONED_QR"] == pytest.approx(0.05)
    again = analyze(scans=registered_clone(3))[1]
    repeat = analyze(scans=list(reversed(registered_clone(3))))[1]
    assert again["by_cause"] == repeat["by_cause"]


def test_chain_down_creates_no_tamper_alert() -> None:
    evaluation, result = analyze(
        digital=[{"product_uid": "prod-eval", "kind": "unverifiable", "evidence_id": "chain-1", "event_time_ms": 0}]
    )
    assert evaluation.alerts == []
    assert result["by_cause"]["RECORD_TAMPERING"] == 0
    assert "chain" in result["missing_checks"]


def test_arrival_order_does_not_change_results() -> None:
    scans = registered_clone(3)
    _forward, forward = analyze(scans=scans, inspections=[staff_inspection()])
    _reverse, reverse = analyze(scans=list(reversed(scans)), inspections=[staff_inspection()])
    assert forward["by_cause"] == reverse["by_cause"]
    assert forward["hypotheses"] == reverse["hypotheses"]
    assert forward["outcome"] == reverse["outcome"]
