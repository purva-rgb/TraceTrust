"""Tuning set. These cases exercise boundaries and are separate from the locked evaluation scores."""
from __future__ import annotations

import pytest

from backend.db import connect
from backend.fusion.config import CORRECTION_PENALTY
from backend.fusion.engine import analyze
from backend.fusion.incidents import cluster_alerts
from backend.fusion.rules import make_alert
from backend.fusion.scenarios import registered_clone, scan, staff_inspection
from backend.fusion.service import persist_alerts


def test_short_hop_and_denied_gps_do_not_support_movement(db_path=None) -> None:
    del db_path
    near = registered_clone(2)
    near[0]["lat"], near[0]["lng"] = 19.0760, 72.8777
    near[1]["lat"], near[1]["lng"] = 19.20, 72.90
    evaluation, _result = analyze(scans=near)
    assert not any(item["rule_code"] == "IMPOSSIBLE_TRAVEL" for item in evaluation.alerts)

    denied = registered_clone(2)
    for item in denied:
        item["gps_status"] = "DENIED"
    evaluation, result = analyze(scans=denied)
    assert "gps" in result["missing_checks"]
    assert not any(item["rule_code"] == "IMPOSSIBLE_TRAVEL" for item in evaluation.alerts)


def test_invalid_signature_is_stored_out_of_location_rules() -> None:
    scans = registered_clone(2)
    scans[1]["signature_valid"] = False
    evaluation, result = analyze(scans=scans)
    assert not any(item["rule_code"] == "IMPOSSIBLE_TRAVEL" for item in evaluation.alerts)
    assert result["by_cause"]["CLONED_QR"] == 0


def test_accuracy_penalty_halves_location_trust() -> None:
    scans = registered_clone(2)
    scans[0]["accuracy_km"] = 20
    evaluation, result = analyze(scans=scans)
    travel = [item for item in evaluation.alerts if item["rule_code"] == "IMPOSSIBLE_TRAVEL"]
    assert travel
    assert travel[0]["trust"] == pytest.approx(0.40)
    assert result["by_cause"]["CLONED_QR"] == pytest.approx(0.20)


def test_authorized_opening_removes_broken_seal_support() -> None:
    evaluation, result = analyze(inspections=[staff_inspection(broken=True, opening_authorized=True, box_ok=True, seal_ok=True)])
    assert not any(item["rule_code"] == "UNEXPECTED_SEAL_BROKEN" for item in evaluation.alerts)
    assert result["by_cause"]["DEVICE_OR_PACKAGE_SUBSTITUTION"] == 0


def test_validated_correction_subtracts_configured_penalty() -> None:
    _evaluation, result = analyze(scans=registered_clone(3), validated_corrections=["CLONED_QR"])
    assert result["by_cause"]["CLONED_QR"] == pytest.approx(0.64 - CORRECTION_PENALTY)


def test_close_causes_are_ambiguous() -> None:
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
            "is_simulated": False,
        }
    ]
    _evaluation, result = analyze(scans=scans, inspections=[staff_inspection()], transfers=transfers)
    assert result["outcome"] == "AMBIGUOUS"
    assert result["requires_investigator_review"] is True
    assert result["by_cause"]["DEVICE_OR_PACKAGE_SUBSTITUTION"] == pytest.approx(0.49)
    assert result["by_cause"]["DIVERSION_OR_GRAY_MARKET"] == pytest.approx(0.56)


def test_full_inspection_counts_serial_sealed_profile_does_not() -> None:
    inspection = staff_inspection(box_ok=True, seal_ok=True, serial="MISMATCH")
    _evaluation, sealed = analyze(inspections=[inspection], profile="sealed_only")
    _evaluation, full = analyze(inspections=[inspection], profile="full_inspection")
    assert sealed["by_cause"]["DEVICE_OR_PACKAGE_SUBSTITUTION"] == 0
    assert full["by_cause"]["DEVICE_OR_PACKAGE_SUBSTITUTION"] == pytest.approx(0.315)
    assert any(item["rule_code"] == "SERIAL_MISMATCH" for item in _evaluation.alerts)


def test_clusters_cap_time_and_shared_shipment_only() -> None:
    burst = [
        make_alert(
            rule_code="HANDOVER_MISMATCH",
            evidence_class="handover_mismatch",
            product_uid="prod-a",
            evidence_ids=[str(index)],
            trust=0.7,
            reason="receipt mismatch",
            is_simulated=False,
            event_time_ms=index * 1000,
        )
        for index in range(101)
    ]
    groups = cluster_alerts(burst)
    assert [len(group) for group in groups] == [100, 1]

    early = make_alert(
        rule_code="BOX_MISMATCH",
        evidence_class="box_mismatch",
        product_uid="prod-a",
        evidence_ids=["early"],
        trust=0.7,
        reason="box",
        is_simulated=False,
        event_time_ms=0,
    )
    late = make_alert(
        rule_code="BOX_MISMATCH",
        evidence_class="box_mismatch",
        product_uid="prod-a",
        evidence_ids=["late"],
        trust=0.7,
        reason="box",
        is_simulated=False,
        event_time_ms=25 * 60 * 60 * 1000,
    )
    assert len(cluster_alerts([early, late])) == 2

    shared_a = make_alert(
        rule_code="BOX_MISMATCH",
        evidence_class="box_mismatch",
        product_uid="prod-a",
        evidence_ids=["a"],
        trust=0.7,
        reason="box",
        is_simulated=False,
        event_time_ms=0,
        shipment_uid="ship-1",
    )
    shared_b = make_alert(
        rule_code="BOX_MISMATCH",
        evidence_class="box_mismatch",
        product_uid="prod-b",
        evidence_ids=["b"],
        trust=0.7,
        reason="box",
        is_simulated=False,
        event_time_ms=1000,
        shipment_uid="ship-1",
    )
    other = make_alert(
        rule_code="HANDOVER_MISMATCH",
        evidence_class="handover_mismatch",
        product_uid="prod-c",
        evidence_ids=["c"],
        trust=0.7,
        reason="handover",
        is_simulated=False,
        event_time_ms=1000,
        shipment_uid="ship-1",
    )
    assert len(cluster_alerts([shared_a, shared_b])) == 1
    assert len(cluster_alerts([shared_a, other])) == 2


def test_duplicate_persist_and_late_revision_keep_investigator_status(db_path) -> None:
    conn = connect(db_path)
    try:
        decisions = conn.execute("SELECT COUNT(*) AS n FROM investigator_decisions").fetchone()["n"]
        legacy = conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"]
        first = make_alert(
            rule_code="BOX_MISMATCH",
            evidence_class="box_mismatch",
            product_uid="prod-revision",
            evidence_ids=["box-1"],
            trust=0.7,
            reason="Observed box serial does not match the registered package",
            is_simulated=True,
            event_time_ms=1_000,
        )
        persist_alerts(conn, [first])
        conn.commit()
        persist_alerts(conn, [first])
        conn.commit()
        row = conn.execute("SELECT * FROM fusion_incidents WHERE product_uid='prod-revision'").fetchone()
        assert row["status"] == "OPEN"
        assert row["revision"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM rule_alerts WHERE product_uid='prod-revision'").fetchone()["n"] == 1

        second = make_alert(
            rule_code="SEAL_ID_MISMATCH",
            evidence_class="seal_id_mismatch",
            product_uid="prod-revision",
            evidence_ids=["seal-1"],
            trust=0.7,
            reason="Observed seal ID does not match the registered seal",
            is_simulated=True,
            event_time_ms=2_000,
        )
        persist_alerts(conn, [second])
        conn.commit()
        conn.execute("UPDATE fusion_incidents SET status='DISMISSED' WHERE product_uid='prod-revision'")
        conn.commit()
        third = make_alert(
            rule_code="HANDOVER_MISMATCH",
            evidence_class="handover_mismatch",
            product_uid="prod-revision",
            evidence_ids=["hand-1"],
            trust=0.7,
            reason="Receipt does not match the signed manifest",
            is_simulated=True,
            event_time_ms=3_000,
        )
        persist_alerts(conn, [third])
        conn.commit()
        row = conn.execute("SELECT * FROM fusion_incidents WHERE product_uid='prod-revision'").fetchone()
        assert row["status"] == "DISMISSED"
        assert row["revision"] == 3
        revisions = conn.execute(
            "SELECT revision FROM fusion_incident_revisions WHERE incident_id=? ORDER BY revision",
            (row["id"],),
        ).fetchall()
        assert [item["revision"] for item in revisions] == [1, 2, 3]
        assert conn.execute("SELECT COUNT(*) AS n FROM investigator_decisions").fetchone()["n"] == decisions
        assert conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"] == legacy
    finally:
        conn.close()
