import json
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from inbox.receipts import ReceiptStore
from survey.faces import require_id


@dataclass(frozen=True)
class AuditCase:
    case_id: int
    freeze_id: int
    receipt_ids: tuple[int, ...]


class CaseStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.receipts = ReceiptStore(connection)

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS audit_cases (
                case_id INTEGER PRIMARY KEY,
                freeze_id INTEGER NOT NULL,
                receipt_ids TEXT NOT NULL
            )
        ''')

    def select(self, receipt_ids: Iterable[int]) -> int:
        selected = set()
        for receipt_id in receipt_ids:
            require_id(receipt_id, 'receipt ID')
            selected.add(receipt_id)
        ordered = tuple(sorted(selected))
        if not ordered:
            raise ValueError('a case must select at least one receipt')
        packets = [self.receipts.load(receipt_id).packet for receipt_id in ordered]
        freezes = {packet.wire.freeze_id for packet in packets}
        if len(freezes) != 1:
            raise ValueError('selected receipts belong to different freezes')
        versions = {packet.wire.version for packet in packets}
        if len(versions) != 1:
            raise ValueError('selected receipts mix packet versions')
        if versions == {2}:
            set_ids = {packet.set_id for packet in packets}
            if len(set_ids) != 1:
                raise ValueError('selected receipts belong to different sets')
        freeze_id = freezes.pop()
        with self.connection:
            cursor = self.connection.execute(
                'INSERT INTO audit_cases (freeze_id, receipt_ids) VALUES (?, ?)',
                (freeze_id, json.dumps(ordered)),
            )
        return cursor.lastrowid

    def load(self, case_id: int) -> AuditCase:
        require_id(case_id, 'case ID')
        row = self.connection.execute(
            'SELECT freeze_id, receipt_ids FROM audit_cases WHERE case_id = ?', (case_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown audit case {case_id}')
        return AuditCase(case_id, row[0], tuple(json.loads(row[1])))
