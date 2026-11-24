from collections import defaultdict
from dataclasses import dataclass

from field.anchors import Anchor
from field.seams import SeamEnd
from inbox.cases import AuditCase
from inbox.receipts import ReceiptStore
from survey.faces import Adjacency


@dataclass(frozen=True)
class CoveredFace:
    face_id: str
    quantity: int
    receipt_ids: tuple[int, ...]


@dataclass(frozen=True)
class CaseCoverage:
    freeze_id: int
    faces: tuple[CoveredFace, ...]
    relations: tuple[Adjacency, ...]
    seams: tuple[SeamEnd, ...]
    anchors: tuple[Anchor, ...]


def collect_case_coverage(case: AuditCase, receipts: ReceiptStore) -> CaseCoverage:
    quantities = {}
    provenance = defaultdict(set)
    relations = set()
    seams = set()
    anchors = {}
    for receipt_id in case.receipt_ids:
        packet = receipts.load(receipt_id).packet
        if packet.wire.freeze_id != case.freeze_id:
            raise ValueError(f'receipt {receipt_id} belongs to a different freeze')
        for face in packet.faces:
            existing = quantities.setdefault(face.face_id, face.quantity)
            if existing != face.quantity:
                raise ValueError(f'inconsistent quantity for frozen face {face.face_id}')
            provenance[face.face_id].add(receipt_id)
        relations.update(packet.relations)
        seams.update(packet.seams)
        for anchor in packet.anchors:
            existing = anchors.setdefault(anchor.name, anchor)
            if existing != anchor:
                raise ValueError(f'inconsistent evidence for anchor {anchor.name}')
    faces = tuple(
        CoveredFace(face_id, quantity, tuple(sorted(provenance[face_id])))
        for face_id, quantity in sorted(quantities.items())
    )
    return CaseCoverage(
        case.freeze_id, faces, tuple(sorted(relations)), tuple(sorted(seams)),
        tuple(anchors[name] for name in sorted(anchors)),
    )
