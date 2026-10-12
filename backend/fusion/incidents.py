"""Group alerts into product episodes. Investigator status is never rewritten."""
from __future__ import annotations

from backend.fusion.config import INCIDENT_ALERT_CAP, INCIDENT_WINDOW_MS, SHARED_FAILURE_CLASSES


def _sort_key(alert: dict) -> tuple:
    return (int(alert.get("event_time_ms") or 0), str(alert.get("dedupe_key") or ""))


def _find(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _union(parent: list[int], left: int, right: int) -> None:
    root_left, root_right = _find(parent, left), _find(parent, right)
    if root_left == root_right:
        return
    if root_left < root_right:
        parent[root_right] = root_left
    else:
        parent[root_left] = root_right


def _split(alerts: list[dict]) -> list[list[dict]]:
    ordered = sorted(alerts, key=_sort_key)
    groups: list[list[dict]] = []
    current: list[dict] = []
    start = 0
    for alert in ordered:
        when = int(alert.get("event_time_ms") or 0)
        if not current:
            current = [alert]
            start = when
            continue
        if when - start > INCIDENT_WINDOW_MS or len(current) >= INCIDENT_ALERT_CAP:
            groups.append(current)
            current = [alert]
            start = when
        else:
            current.append(alert)
    if current:
        groups.append(current)
    return groups


def cluster_alerts(alerts: list[dict]) -> list[list[dict]]:
    ordered = sorted(alerts, key=_sort_key)
    parent = list(range(len(ordered)))
    for index, left in enumerate(ordered):
        for follow in range(index + 1, len(ordered)):
            right = ordered[follow]
            gap = abs(int(left.get("event_time_ms") or 0) - int(right.get("event_time_ms") or 0))
            if gap > INCIDENT_WINDOW_MS:
                continue
            same_product = left.get("product_uid") and left.get("product_uid") == right.get("product_uid")
            shipment = left.get("shipment_uid")
            shared_failure = (
                shipment
                and shipment == right.get("shipment_uid")
                and left.get("product_uid") != right.get("product_uid")
                and left.get("evidence_class") == right.get("evidence_class")
                and left.get("evidence_class") in SHARED_FAILURE_CLASSES
            )
            if same_product or shared_failure:
                _union(parent, index, follow)
    buckets: dict[int, list[dict]] = {}
    for index, alert in enumerate(ordered):
        buckets.setdefault(_find(parent, index), []).append(alert)
    groups: list[list[dict]] = []
    for key in sorted(buckets):
        groups.extend(_split(buckets[key]))
    groups.sort(key=lambda group: _sort_key(group[0]))
    return groups


def primary_product(group: list[dict]) -> str:
    return min(str(alert.get("product_uid") or "") for alert in group)
