from dataclasses import dataclass
from typing import Iterable

from survey.faces import Adjacency, Face, index_faces, require_name
from survey.revisions import RevisionStore


@dataclass(frozen=True)
class ImportBatch:
    faces: tuple[Face, ...]
    relations: tuple[Adjacency, ...] = ()


def import_batch(store: RevisionStore, batch: ImportBatch) -> int:
    return store.append(batch.faces, batch.relations)


def apply_correction(
    store: RevisionStore, base_revision_id: int, *,
    measurements: Iterable[Face] = (), remove_faces: Iterable[str] = (),
    relations: Iterable[Adjacency] | None = None,
) -> int:
    base = store.load(base_revision_id)
    updated = {face.face_id: face for face in base.faces}
    replacements = index_faces(measurements)
    removed = set()
    for face_id in remove_faces:
        require_name(face_id, 'removed face ID')
        if face_id not in updated or face_id in removed or face_id in replacements:
            raise ValueError(f'invalid removal of {face_id}')
        removed.add(face_id)
    for face_id in removed:
        del updated[face_id]
    updated.update(replacements)
    if relations is None:
        relations = base.relations
    return store.append(updated.values(), relations, parent_id=base.revision_id)
