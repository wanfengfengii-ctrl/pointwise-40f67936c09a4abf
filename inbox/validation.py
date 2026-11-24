from dataclasses import dataclass

from field.anchors import Anchor, register_anchors
from field.seams import SeamEnd, register_seam_ends
from field.sheets import SheetScope
from inbox.wire import WirePacket, decode_packet
from survey.faces import Adjacency, Face, require_id, require_name, require_sign, validate_measurements


@dataclass(frozen=True)
class ValidatedPacket:
    wire: WirePacket
    sheet: str
    faces: tuple[Face, ...]
    relations: tuple[Adjacency, ...]
    seams: tuple[SeamEnd, ...]
    anchors: tuple[Anchor, ...]


@dataclass(frozen=True)
class SharedFaceRecord:
    token: str
    quantity: int
    sign: int


@dataclass(frozen=True)
class SetSeamRecord:
    seam: str
    end: str
    sign: int
    attach: int


@dataclass(frozen=True)
class SetAnchorRecord:
    name: str
    sign: int
    attach: int


@dataclass(frozen=True)
class SetComponent:
    component_id: str
    directed: int
    shares: tuple[SharedFaceRecord, ...]
    seams: tuple[SetSeamRecord, ...]
    anchors: tuple[SetAnchorRecord, ...]


@dataclass(frozen=True)
class ValidatedSetPacket:
    wire: WirePacket
    sheet: str
    set_id: int
    components: tuple[SetComponent, ...]


def _rows(payload: dict, key: str, fields: set[str]) -> tuple[dict, ...]:
    rows = payload[key]
    if not isinstance(rows, list):
        raise ValueError(f'{key} must be an array')
    for row in rows:
        if not isinstance(row, dict) or row.keys() != fields:
            raise ValueError(f'invalid row in {key}')
    return tuple(rows)


def _require_integer(value: int, label: str) -> None:
    if type(value) is not int:
        raise ValueError(f'{label} must be an integer')


def _validate_v1(wire: WirePacket) -> ValidatedPacket:
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


def _validate_v2(wire: WirePacket) -> ValidatedSetPacket:
    payload = wire.payload
    if payload.keys() != {'sheet', 'set_id', 'components'}:
        raise ValueError('invalid V2 evidence fields')
    sheet = payload['sheet']
    require_name(sheet, 'sheet')
    require_id(payload['set_id'], 'set ID')
    rows = payload['components']
    if not isinstance(rows, list) or not rows:
        raise ValueError('components must be a non-empty array')
    components = []
    component_ids = set()
    tokens = set()
    seam_positions = set()
    anchor_names = set()
    for row in rows:
        if not isinstance(row, dict) or row.keys() != {'component_id', 'directed', 'shares', 'seams', 'anchors'}:
            raise ValueError('invalid row in components')
        component_id = row['component_id']
        require_name(component_id, 'component ID')
        if component_id in component_ids:
            raise ValueError(f'duplicate component {component_id}')
        component_ids.add(component_id)
        _require_integer(row['directed'], f'component {component_id} directed quantity')
        shares = []
        for share in _rows(row, 'shares', {'token', 'quantity', 'sign'}):
            require_name(share['token'], 'shared face token')
            _require_integer(share['quantity'], 'shared face quantity')
            require_sign(share['sign'])
            if share['token'] in tokens:
                raise ValueError(f'duplicate shared face {share["token"]}')
            tokens.add(share['token'])
            shares.append(SharedFaceRecord(share['token'], share['quantity'], share['sign']))
        seams = []
        for seam in _rows(row, 'seams', {'seam', 'end', 'sign', 'attach'}):
            require_name(seam['seam'], 'seam name')
            require_sign(seam['sign'])
            require_sign(seam['attach'])
            if seam['end'] not in ('a', 'b'):
                raise ValueError(f'invalid position for seam {seam["seam"]}')
            position = (seam['seam'], seam['end'])
            if position in seam_positions:
                raise ValueError(f'duplicate seam end {position}')
            seam_positions.add(position)
            seams.append(SetSeamRecord(seam['seam'], seam['end'], seam['sign'], seam['attach']))
        anchors = []
        for anchor in _rows(row, 'anchors', {'name', 'sign', 'attach'}):
            require_name(anchor['name'], 'anchor name')
            require_sign(anchor['sign'])
            require_sign(anchor['attach'])
            if anchor['name'] in anchor_names:
                raise ValueError(f'duplicate anchor {anchor["name"]}')
            anchor_names.add(anchor['name'])
            anchors.append(SetAnchorRecord(anchor['name'], anchor['sign'], anchor['attach']))
        components.append(SetComponent(
            component_id, row['directed'], tuple(shares), tuple(seams), tuple(anchors),
        ))
    return ValidatedSetPacket(wire, sheet, payload['set_id'], tuple(components))


def validate_packet(raw: bytes) -> ValidatedPacket:
    wire = decode_packet(raw)
    if wire.version != 1:
        raise ValueError('unsupported packet version')
    return _validate_v1(wire)


def validate_set_packet(raw: bytes) -> ValidatedSetPacket:
    wire = decode_packet(raw)
    if wire.version != 2:
        raise ValueError('unsupported packet version')
    return _validate_v2(wire)


def validate_incoming(raw: bytes) -> ValidatedPacket | ValidatedSetPacket:
    wire = decode_packet(raw)
    if wire.version == 1:
        return _validate_v1(wire)
    if wire.version == 2:
        return _validate_v2(wire)
    raise ValueError('unsupported packet version')
