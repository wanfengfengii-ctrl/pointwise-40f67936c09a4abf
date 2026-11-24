from dataclasses import asdict, dataclass

from delivery.plan import ValidatedIssuePlan
from field.anchors import Anchor
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
