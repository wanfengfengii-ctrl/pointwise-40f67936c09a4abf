from dataclasses import dataclass

from field.anchors import Anchor
from field.inspection import InspectionStore
from field.seams import SeamEnd
from field.sheets import SheetScope, resolve_sheet_scope


@dataclass(frozen=True)
class IssuePlan:
    sheet: str
    face_ids: tuple[str, ...]
    evidence_id: int


@dataclass(frozen=True)
class ValidatedIssuePlan:
    scope: SheetScope
    seams: tuple[SeamEnd, ...]
    anchors: tuple[Anchor, ...]


def validate_issue_plan(
    inspections: InspectionStore, freeze_id: int, plan: IssuePlan,
) -> ValidatedIssuePlan:
    frozen = inspections.freezes.load_freeze(freeze_id)
    scope = resolve_sheet_scope(frozen, plan.sheet, plan.face_ids)
    evidence = inspections.load(plan.evidence_id)
    if evidence.freeze_id != freeze_id or evidence.sheet != scope.sheet:
        raise ValueError('inspection belongs to a different freeze or sheet')
    selected = set(scope.face_ids)
    observed = {face.face_id for face in evidence.faces}
    if not selected <= observed:
        raise ValueError('issue coverage exceeds inspected coverage')
    return ValidatedIssuePlan(
        scope,
        tuple(seam for seam in evidence.seams if seam.face in selected),
        tuple(anchor for anchor in evidence.anchors if anchor.face in selected),
    )
