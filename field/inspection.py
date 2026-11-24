import json
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Iterable

from field.anchors import Anchor, check_component_anchors, register_anchors
from field.components import find_sheet_components
from field.seams import SeamEnd, register_seam_ends
from field.sheets import resolve_sheet_scope
from survey.faces import Adjacency, Face, require_id
from survey.freezes import FreezeStore


@dataclass(frozen=True)
class ComponentInspection:
    face_ids: tuple[str, ...]
    relative_signs: tuple[tuple[str, int], ...]
    relation_conflict: bool
    status: str
    anchor_names: tuple[str, ...]


@dataclass(frozen=True)
class FieldEvidence:
    evidence_id: int
    freeze_id: int
    sheet: str
    faces: tuple[Face, ...]
    relations: tuple[Adjacency, ...]
    seams: tuple[SeamEnd, ...]
    anchors: tuple[Anchor, ...]
    components: tuple[ComponentInspection, ...]


class InspectionStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.freezes = FreezeStore(connection)

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS inspections (
                evidence_id INTEGER PRIMARY KEY,
                freeze_id INTEGER NOT NULL REFERENCES freezes(freeze_id),
                sheet TEXT NOT NULL,
                evidence TEXT NOT NULL
            )
        ''')

    def inspect(
        self, freeze_id: int, sheet: str, face_ids: Iterable[str], *,
        seams: Iterable[SeamEnd] = (), anchors: Iterable[Anchor] = (),
    ) -> FieldEvidence:
        scope = resolve_sheet_scope(self.freezes.load_freeze(freeze_id), sheet, face_ids)
        seams = register_seam_ends(scope, seams)
        anchors = register_anchors(scope, anchors)
        by_face = defaultdict(list)
        for anchor in anchors:
            by_face[anchor.face].append(anchor)
        components = []
        for component in find_sheet_components(scope):
            marks = (mark for face in component.face_ids for mark in by_face.get(face, ()))
            finding = check_component_anchors(component, marks)
            components.append(ComponentInspection(
                component.face_ids, component.relative_signs, component.relation_conflict,
                finding.status, finding.anchor_names,
            ))
        body = json.dumps({
            'faces': [asdict(face) for face in scope.faces],
            'relations': [asdict(edge) for edge in scope.relations],
            'seams': [asdict(seam) for seam in seams],
            'anchors': [asdict(anchor) for anchor in anchors],
            'components': [asdict(component) for component in components],
        }, sort_keys=True)
        with self.connection:
            cursor = self.connection.execute(
                'INSERT INTO inspections (freeze_id, sheet, evidence) VALUES (?, ?, ?)',
                (freeze_id, sheet, body),
            )
        return FieldEvidence(
            cursor.lastrowid, freeze_id, sheet, scope.faces, scope.relations,
            seams, anchors, tuple(components),
        )

    def load(self, evidence_id: int) -> FieldEvidence:
        require_id(evidence_id, 'evidence ID')
        row = self.connection.execute('''
            SELECT freeze_id, sheet, evidence FROM inspections WHERE evidence_id = ?
        ''', (evidence_id,)).fetchone()
        if row is None:
            raise LookupError(f'unknown inspection {evidence_id}')
        freeze_id, sheet, raw = row
        body = json.loads(raw)
        return FieldEvidence(
            evidence_id, freeze_id, sheet,
            tuple(Face(**item) for item in body['faces']),
            tuple(Adjacency(**item) for item in body['relations']),
            tuple(SeamEnd(**item) for item in body['seams']),
            tuple(Anchor(**item) for item in body['anchors']),
            tuple(ComponentInspection(
                tuple(item['face_ids']), tuple(map(tuple, item['relative_signs'])),
                item['relation_conflict'], item['status'], tuple(item['anchor_names']),
            ) for item in body['components']),
        )
