from dataclasses import dataclass
from typing import Iterable

from survey.faces import Adjacency, Face, require_name
from survey.freezes import FrozenRevision


@dataclass(frozen=True)
class SheetScope:
    freeze_id: int
    sheet: str
    faces: tuple[Face, ...]
    relations: tuple[Adjacency, ...]

    @property
    def face_ids(self) -> tuple[str, ...]:
        return tuple(face.face_id for face in self.faces)


def resolve_sheet_scope(
    frozen: FrozenRevision, sheet: str, face_ids: Iterable[str],
) -> SheetScope:
    require_name(sheet, 'sheet')
    by_id = {face.face_id: face for face in frozen.revision.faces}
    chosen = set()
    for face_id in face_ids:
        require_name(face_id, 'face ID')
        if face_id in chosen or face_id not in by_id:
            raise ValueError(f'duplicate or unknown face {face_id} in {sheet}')
        chosen.add(face_id)
    if not chosen:
        raise ValueError('sheet coverage is empty')
    relations = tuple(
        edge for edge in frozen.revision.relations
        if edge.left in chosen and edge.right in chosen
    )
    return SheetScope(
        frozen.freeze_id, sheet, tuple(by_id[face_id] for face_id in sorted(chosen)),
        relations,
    )
