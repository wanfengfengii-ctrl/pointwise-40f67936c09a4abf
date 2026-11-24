from dataclasses import dataclass

from delivery.archive import IssueArchive
from delivery.evidence import build_packet_evidence
from delivery.plan import IssuePlan, validate_issue_plan
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
