"""Run rules and fusion together."""
from __future__ import annotations

from backend.fusion.rules import Evaluation, evaluate
from backend.fusion.score import fuse


def analyze(
    *,
    scans: list[dict] | None = None,
    inspections: list[dict] | None = None,
    transfers: list[dict] | None = None,
    digital: list[dict] | None = None,
    records: list[dict] | None = None,
    profile: str | None = None,
    validated_corrections: list[str] | None = None,
) -> tuple[Evaluation, dict]:
    evaluation = evaluate(
        scans=scans,
        inspections=inspections,
        transfers=transfers,
        digital=digital,
        records=records,
    )
    result = fuse(
        evaluation.alerts,
        profile=profile,
        missing_checks=evaluation.missing_checks,
        authorized_opening=evaluation.authorized_opening,
        validated_corrections=validated_corrections,
    )
    return evaluation, result
