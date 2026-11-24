from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, order=True)
class Face:
    face_id: str
    quantity: int


@dataclass(frozen=True, order=True)
class Adjacency:
    left: str
    right: str
    sign: int


def require_name(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be a nonblank string')


def require_id(value: int, label: str) -> None:
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError(f'{label} must be a positive SQLite integer ID')


def require_sign(value: int) -> None:
    if type(value) is not int or value not in (-1, 1):
        raise ValueError('direction sign must be -1 or 1')


def index_faces(faces: Iterable[Face]) -> dict[str, Face]:
    by_id = {}
    for face in faces:
        require_name(face.face_id, 'face ID')
        if type(face.quantity) is not int:
            raise ValueError(f'face {face.face_id} requires an integer quantity')
        if face.face_id in by_id:
            raise ValueError(f'duplicate face {face.face_id}')
        by_id[face.face_id] = face
    return by_id


def validate_measurements(
    faces: Iterable[Face], relations: Iterable[Adjacency],
) -> tuple[tuple[Face, ...], tuple[Adjacency, ...]]:
    by_id = index_faces(faces)
    if not by_id:
        raise ValueError('measurement coverage is empty')
    normalized = set()
    for relation in relations:
        require_name(relation.left, 'adjacency endpoint')
        require_name(relation.right, 'adjacency endpoint')
        require_sign(relation.sign)
        if relation.left not in by_id or relation.right not in by_id:
            raise ValueError(f'adjacency references an unknown face: {relation}')
        left, right = sorted((relation.left, relation.right))
        normalized.add(Adjacency(left, right, relation.sign))
    return tuple(sorted(by_id.values())), tuple(sorted(normalized))
