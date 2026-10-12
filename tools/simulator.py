"""Print the demo evidence scenarios. Scores come from the fusion rules, not a learned model."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.fusion.engine import analyze
from backend.fusion.scenarios import (
    MUMBAI,
    PUNE,
    anonymous_clone,
    interrupted_dispatch,
    registered_clone,
    scan,
    staff_inspection,
)
from backend.fusion.score import support_line


def _show(title: str, result: dict) -> None:
    print(f"\n{title}")
    process = result.get("process_recording_gap") or {}
    if process.get("has_documentation_gap"):
        print(f"  {process.get('explanation') or support_line('PROCESS_RECORDING_GAP', process['support_score'])}")
    if result["outcome"] == "INSUFFICIENT_EVIDENCE" and result["hypotheses"]:
        print("  Insufficient evidence")
    elif result["outcome"] == "INSUFFICIENT_EVIDENCE" and not process.get("has_documentation_gap"):
        print("  Insufficient evidence")
    for item in result["hypotheses"]:
        print(f"  {support_line(item['cause'], item['support_score'])}")
        for reason in item["reasons"]:
            print(f"    - {reason}")
    if result["missing_checks"]:
        print("  missing checks:", ", ".join(result["missing_checks"]))
    if result["requires_investigator_review"]:
        print("  requires investigator review")
    if result["is_simulated"]:
        print("  simulated")


def main() -> None:
    _evaluation, clone = analyze(scans=registered_clone(3))
    _show("Clone: 3 registered devices (Mumbai, London, New York) within 10 min", clone)

    flood = anonymous_clone() + [
        scan(f"flood-{index}", lat=19.07, lng=72.87, event_time_ms=index * 1000, device_registered=False, client_trust=1)
        for index in range(30)
    ]
    _show("Anonymous flood, including the same three cities", analyze(scans=flood)[1])

    movement = [
        scan("pune", lat=PUNE[0], lng=PUNE[1], event_time_ms=0, device_id="dev-pune", device_registered=True, signature_valid=True),
        scan(
            "mumbai",
            lat=MUMBAI[0],
            lng=MUMBAI[1],
            event_time_ms=4 * 60 * 60 * 1000,
            device_id="dev-mumbai",
            device_registered=True,
            signature_valid=True,
        ),
    ]
    _show("Normal movement: Pune to Mumbai over 4 hours", analyze(scans=movement)[1])

    _show("Wrong box and wrong seal, witnessed staff", analyze(inspections=[staff_inspection()])[1])
    _show("Wrong box, wrong seal, and broken seal", analyze(inspections=[staff_inspection(broken=True)])[1])
    _show("Interrupted dispatch: receipt recorded, confirmed handover missing", analyze(records=interrupted_dispatch())[1])


if __name__ == "__main__":
    main()
