from dataclasses import dataclass

from field.anchors import Anchor, register_anchors
from field.seams import SeamEnd, register_seam_ends
from field.sheets import SheetScope
from inbox.wire import WirePacket, decode_packet
from survey.faces import Adjacency, Face, require_name, validate_measurements


@dataclass(frozen=True)
class ValidatedPacket:
    wire: WirePacket
    sheet: str
    faces: tuple[Face, ...]
    relations: tuple[Adjacency, ...]
    seams: tuple[SeamEnd, ...]
    anchors: tuple[Anchor, ...]


def _rows(payload: dict, key: str, fields: set[str]) -> tuple[dict, ...]:
    rows = payload[key]
    if not isinstance(rows, list):
        raise ValueError(f'{key} must be an array')
    for row in rows:
        if not isinstance(row, dict) or row.keys() != fields:
            raise ValueError(f'invalid row in {key}')
    return tuple(rows)


def validate_packet(raw: bytes) -> ValidatedPacket:
    wire = decode_packet(raw)
    payload = wire.payload
    if payload.keys() != {'sheet', 'faces', 'relations', 'seams', 'anchors'}:
        raise ValueError('invalid V1 evidence fields')
    sheet = payload['sheet']
    require_name(sheet, 'sheet')
    faces, relations = validate_measurements(
        (Face(**row) for row in _rows(payload, 'faces', {'face_id', 'quantity'})),
        (Adjacency(**row) for row in _rows(payload, 'relations', {'left', 'right', 'sign'})),
    )
    scope = SheetScope(wire.freeze_id, sheet, faces, relations)
    seams = register_seam_ends(scope, (
        SeamEnd(wire.freeze_id, **row)
        for row in _rows(payload, 'seams', {'seam', 'end', 'face', 'sign'})
    ))
    anchors = register_anchors(scope, (
        Anchor(wire.freeze_id, **row)
        for row in _rows(payload, 'anchors', {'name', 'face', 'sign'})
    ))
    return ValidatedPacket(wire, sheet, faces, relations, seams, anchors)
