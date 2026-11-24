from dataclasses import dataclass
from typing import Iterable

from audit.coverage import CaseCoverage, collect_case_coverage
from audit.orientation import GroupOrientation, resolve_orientations
from audit.publication import FirstReceipt, Report, ReportStore
from audit.seam_matching import match_received_seams
from inbox.cases import CaseStore


@dataclass(frozen=True)
class GroupSettlement:
    face_ids: tuple[str, ...]
    status: str
    net_quantity: int | None
    provenance: tuple[tuple[str, tuple[int, ...]], ...]

    def to_record(self) -> dict:
        return {
            'face_ids': list(self.face_ids),
            'status': self.status,
            'net_quantity': self.net_quantity,
            'provenance': {face: list(receipts) for face, receipts in self.provenance},
        }


def calculate_group_totals(
    coverage: CaseCoverage, orientations: Iterable[GroupOrientation],
) -> tuple[GroupSettlement, ...]:
    by_face = {face.face_id: face for face in coverage.faces}
    groups = []
    for orientation in orientations:
        net = None
        if orientation.status == 'oriented':
            net = sum(sign * by_face[face].quantity for face, sign in orientation.directions)
        provenance = tuple((face, by_face[face].receipt_ids) for face in orientation.face_ids)
        groups.append(GroupSettlement(orientation.face_ids, orientation.status, net, provenance))
    return tuple(groups)


def settle(cases: CaseStore, reports: ReportStore, case_id: int) -> tuple[Report, FirstReceipt]:
    if cases.connection is not reports.connection:
        raise ValueError('case and report stores must use the same offline connection')
    case = cases.load(case_id)
    coverage = collect_case_coverage(case, cases.receipts)
    seams = match_received_seams(coverage)
    groups = calculate_group_totals(coverage, resolve_orientations(coverage, seams))
    return reports.publish(
        case.case_id, case.freeze_id, case.receipt_ids,
        tuple(group.to_record() for group in groups),
    )
