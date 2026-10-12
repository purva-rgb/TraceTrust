"""Locked PROCESS_RECORDING_GAP scores. Do not retune against these."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.fusion.engine import analyze
from backend.fusion.scenarios import (
    corroboration_record,
    documentation_gap_record,
    interrupted_dispatch,
    interrupted_operation_record,
    staff_inspection,
)
from backend.fusion.score import support_line
from backend.transfers.schemas import ReceiptsIn


def _other_causes(result: dict) -> dict:
    return {key: value for key, value in result["by_cause"].items() if key != "PROCESS_RECORDING_GAP"}


def test_gap_only_is_zero_and_feeds_no_suspicious_cause() -> None:
    evaluation, result = analyze(records=interrupted_dispatch(interrupted=False, other_org=False))
    assert {item["rule_code"] for item in evaluation.alerts} == {"CUSTODY_DOCUMENTATION_GAP"}
    assert all(item["strength"] == 0 for item in evaluation.alerts)
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0)
    assert all(value == 0 for value in _other_causes(result).values())
    assert result["hypotheses"] == []
    assert "counterfeit" not in json.dumps(result).lower()
    assert "counterfeit" not in json.dumps(evaluation.alerts).lower()


def test_gap_plus_interrupted_operation_is_0_28() -> None:
    _evaluation, result = analyze(records=interrupted_dispatch(other_org=False))
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0.28)
    assert result["process_recording_gap"]["support_points"] == 28
    assert result["process_recording_gap"]["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert all(value == 0 for value in _other_causes(result).values())


def test_gap_plus_independent_other_org_is_0_28() -> None:
    _evaluation, result = analyze(records=interrupted_dispatch(interrupted=False, other_org=True))
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0.28)
    assert result["process_recording_gap"]["support_points"] == 28
    assert all(value == 0 for value in _other_causes(result).values())


def test_interrupted_and_independent_is_0_56() -> None:
    evaluation, result = analyze(records=interrupted_dispatch())
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0.56)
    assert result["process_recording_gap"]["support_points"] == 56
    assert result["process_recording_gap"]["requires_investigator_review"] is True
    assert (
        support_line("PROCESS_RECORDING_GAP", 0.56)
        == "Process/recording gap: 56/100 explanation support"
    )
    assert result["process_recording_gap"]["explanation"] == (
        "Process/recording gap: 56/100 explanation support. "
        "Documentation incomplete, investigator review required."
    )
    assert {item["rule_code"] for item in evaluation.alerts} >= {
        "CUSTODY_DOCUMENTATION_GAP",
        "INTERRUPTED_OPERATION",
        "INDEPENDENT_CORROBORATION",
    }
    assert all(value == 0 for value in _other_causes(result).values())
    assert "counterfeit" not in json.dumps(result).lower()


def test_both_plus_consistency_is_0_76() -> None:
    _evaluation, result = analyze(records=interrupted_dispatch(consistent=True))
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0.76)
    assert result["process_recording_gap"]["support_points"] == 76
    assert all(value == 0 for value in _other_causes(result).values())


def test_same_org_duplicates_are_not_independent() -> None:
    records = interrupted_dispatch(interrupted=True, other_org=False, extra_same_org=True)
    records.append(
        corroboration_record(org_id=1, evidence_id="cor-same-2", independent=True, client_trust=1)
    )
    evaluation, result = analyze(records=records)
    assert "INDEPENDENT_CORROBORATION" not in {item["rule_code"] for item in evaluation.alerts}
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0.28)


def test_both_plus_wrong_box_is_0_16_insufficient() -> None:
    _evaluation, result = analyze(
        records=interrupted_dispatch(),
        inspections=[staff_inspection(seal_ok=True)],
    )
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0.16)
    assert result["process_recording_gap"]["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert result["process_recording_gap"]["requires_investigator_review"] is False
    assert result["by_cause"]["DEVICE_OR_PACKAGE_SUBSTITUTION"] == pytest.approx(0.245)


def test_repeated_evidence_and_arrival_order_do_not_change_scores() -> None:
    base = interrupted_dispatch(consistent=True)
    _forward, forward = analyze(records=base)
    _reverse, reverse = analyze(records=list(reversed(base)))
    _dup, duplicate = analyze(records=base + base)
    assert forward["by_cause"] == reverse["by_cause"] == duplicate["by_cause"]
    assert forward["process_recording_gap"]["support_score"] == pytest.approx(0.76)
    assert reverse["hypotheses"] == forward["hypotheses"]


def test_client_flags_cannot_create_independence() -> None:
    records = [
        documentation_gap_record(),
        interrupted_operation_record(),
        corroboration_record(org_id=1, independent=True, client_trust=1.0),
    ]
    evaluation, result = analyze(records=records)
    assert "INDEPENDENT_CORROBORATION" not in {item["rule_code"] for item in evaluation.alerts}
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0.28)


def test_carrier_record_counts_as_independent() -> None:
    records = [
        documentation_gap_record(),
        corroboration_record(org_id=1, role="CARRIER", evidence_id="carrier-1"),
    ]
    evaluation, result = analyze(records=records)
    assert "INDEPENDENT_CORROBORATION" in {item["rule_code"] for item in evaluation.alerts}
    assert result["by_cause"]["PROCESS_RECORDING_GAP"] == pytest.approx(0.28)


def test_missing_required_receipt_field_is_422() -> None:
    with pytest.raises(ValidationError):
        ReceiptsIn(items=[{"product_uid": "prod-eval", "seal_id": "SEAL-1", "condition": "INTACT", "mode": "SEALED"}])
