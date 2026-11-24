from collections import Counter
from dataclasses import asdict, dataclass

from delivery.plan import ValidatedIssuePlan
from field.anchors import Anchor
from field.components import check_local_relations
from field.seams import SeamEnd
from survey.faces import Adjacency, Face


@dataclass(frozen=True)
class PacketEvidence:
    sheet: str
    faces: tuple[Face, ...]
    relations: tuple[Adjacency, ...]
    seams: tuple[SeamEnd, ...]
    anchors: tuple[Anchor, ...]

    def to_payload(self) -> dict:
        return {
            'sheet': self.sheet,
            'faces': [asdict(face) for face in self.faces],
            'relations': [asdict(edge) for edge in self.relations],
            'seams': [
                {'seam': end.seam, 'end': end.end, 'face': end.face, 'sign': end.sign}
                for end in self.seams
            ],
            'anchors': [
                {'name': anchor.name, 'face': anchor.face, 'sign': anchor.sign}
                for anchor in self.anchors
            ],
        }


def build_packet_evidence(plan: ValidatedIssuePlan) -> PacketEvidence:
    return PacketEvidence(
        plan.scope.sheet, plan.scope.faces, plan.scope.relations, plan.seams, plan.anchors,
    )


def build_set_payloads(plans: tuple[ValidatedIssuePlan, ...]) -> list[dict]:
    # Per-sheet connected components become anonymous aggregates. Only the
    # information needed for grouping and overlap removal crosses the counter:
    # shared faces carry a per-set token, seam ends and anchors carry the
    # relative sign of their attachment point. Face identifiers, per-face
    # quantities and per-face adjacency stay at the station.
    coverage = Counter(face_id for plan in plans for face_id in plan.scope.face_ids)
    shared = sorted(face_id for face_id, count in coverage.items() if count > 1)
    tokens = {face_id: f's{index}' for index, face_id in enumerate(shared, 1)}
    payloads = []
    for plan in plans:
        components = check_local_relations(plan.scope.face_ids, plan.scope.relations)
        quantities = {face.face_id: face.quantity for face in plan.scope.faces}
        rows = []
        for index, component in enumerate(components, 1):
            relative = dict(component.relative_signs)
            faces = set(component.face_ids)
            rows.append({
                'component_id': f'c{index}',
                'directed': sum(relative[face_id] * quantities[face_id]
                                for face_id in component.face_ids),
                'shares': [
                    {'token': tokens[face_id], 'quantity': quantities[face_id],
                     'sign': relative[face_id]}
                    for face_id in component.face_ids if face_id in tokens
                ],
                'seams': [
                    {'seam': seam.seam, 'end': seam.end, 'sign': seam.sign,
                     'attach': relative[seam.face]}
                    for seam in plan.seams if seam.face in faces
                ],
                'anchors': [
                    {'name': anchor.name, 'sign': anchor.sign, 'attach': relative[anchor.face]}
                    for anchor in plan.anchors if anchor.face in faces
                ],
            })
        payloads.append({'sheet': plan.scope.sheet, 'components': rows})
    return payloads
