import hashlib
import json
from dataclasses import dataclass

from survey.faces import require_id


@dataclass(frozen=True)
class WirePacket:
    issue_id: int
    freeze_id: int
    payload: dict
    integrity: str
    raw: bytes


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def packet_integrity(issue_id: int, freeze_id: int, payload: dict) -> str:
    unsigned = {'version': 1, 'issue_id': issue_id, 'freeze_id': freeze_id, 'payload': payload}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def encode_packet(issue_id: int, freeze_id: int, payload: dict) -> bytes:
    require_id(issue_id, 'issue ID')
    require_id(freeze_id, 'freeze ID')
    if not isinstance(payload, dict):
        raise ValueError('packet payload must be an object')
    return _canonical({
        'version': 1, 'issue_id': issue_id, 'freeze_id': freeze_id, 'payload': payload,
        'integrity': packet_integrity(issue_id, freeze_id, payload),
    })


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f'duplicate JSON field {name}')
        result[name] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f'invalid JSON number {value}')


def decode_packet(raw: bytes) -> WirePacket:
    if not isinstance(raw, bytes):
        raise ValueError('packet must be bytes')
    try:
        data = json.loads(
            raw.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError('packet is not valid UTF-8 JSON') from error
    keys = {'version', 'issue_id', 'freeze_id', 'payload', 'integrity'}
    if not isinstance(data, dict) or data.keys() != keys:
        raise ValueError('invalid V1 envelope')
    if type(data['version']) is not int or data['version'] != 1:
        raise ValueError('unsupported packet version')
    issue_id, freeze_id = data['issue_id'], data['freeze_id']
    require_id(issue_id, 'issue ID')
    require_id(freeze_id, 'freeze ID')
    payload, integrity = data['payload'], data['integrity']
    if not isinstance(payload, dict) or not isinstance(integrity, str):
        raise ValueError('invalid payload or integrity field')
    try:
        expected = packet_integrity(issue_id, freeze_id, payload)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid packet payload') from error
    if integrity != expected:
        raise ValueError('packet integrity check failed')
    return WirePacket(issue_id, freeze_id, payload, integrity, raw)
