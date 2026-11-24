from dataclasses import dataclass

from delivery.archive import IssueArchive
from delivery.evidence import build_packet_evidence, build_set_payloads
from delivery.plan import IssuePlan, validate_issue_plan
from field.components import check_local_relations
from field.inspection import InspectionStore


@dataclass(frozen=True)
class IssuedPacket:
    issue_id: int
    raw: bytes


def issue(
    inspections: InspectionStore, archive: IssueArchive, freeze_id: int, plan: IssuePlan,
) -> IssuedPacket:
    if inspections.connection is not archive.connection:
        raise ValueError('inspection and archive must use the same station connection')
    verified = validate_issue_plan(inspections, freeze_id, plan)
    evidence = build_packet_evidence(verified)
    issue_id, raw = archive.store_packet(freeze_id, evidence.to_payload())
    return IssuedPacket(issue_id, raw)


def issue_set(
    inspections: InspectionStore, archive: IssueArchive, freeze_id: int,
    plans: tuple[IssuePlan, ...],
) -> tuple[int, tuple[IssuedPacket, ...]]:
    plans = tuple(plans)
    if not 1 <= len(plans) <= 3:
        raise ValueError('a set requires one to three issue plans')
    if inspections.connection is not archive.connection:
        raise ValueError('inspection and archive must use the same station connection')
    validated = tuple(validate_issue_plan(inspections, freeze_id, plan) for plan in plans)
    for plan in validated:
        components = check_local_relations(plan.scope.face_ids, plan.scope.relations)
        if any(component.relation_conflict for component in components):
            raise ValueError(f'sheet {plan.scope.sheet} has contradictory relative directions')
    anchor_names = set()
    seam_positions = set()
    for plan in validated:
        for anchor in plan.anchors:
            if anchor.name in anchor_names:
                raise ValueError(f'duplicate anchor {anchor.name} in set')
            anchor_names.add(anchor.name)
        for seam in plan.seams:
            position = (seam.seam, seam.end)
            if position in seam_positions:
                raise ValueError(f'duplicate seam end {position} in set')
            seam_positions.add(position)
    set_id, stored = archive.store_set_packets(freeze_id, build_set_payloads(validated))
    return set_id, tuple(IssuedPacket(issue_id, raw) for issue_id, raw in stored)
