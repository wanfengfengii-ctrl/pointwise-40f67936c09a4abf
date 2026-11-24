import sqlite3
from dataclasses import dataclass

from inbox.validation import ValidatedPacket, validate_packet
from survey.faces import require_id


@dataclass(frozen=True)
class Receipt:
    receipt_id: int
    packet: ValidatedPacket


class ReceiptStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id INTEGER PRIMARY KEY,
                issue_id INTEGER NOT NULL UNIQUE,
                packet BLOB NOT NULL
            )
        ''')

    def receive(self, raw: bytes) -> int:
        packet = validate_packet(raw)
        issue_id = packet.wire.issue_id
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            row = self.connection.execute(
                'SELECT receipt_id, packet FROM receipts WHERE issue_id = ?', (issue_id,),
            ).fetchone()
            if row is None:
                cursor = self.connection.execute(
                    'INSERT INTO receipts (issue_id, packet) VALUES (?, ?)', (issue_id, raw),
                )
                receipt_id = cursor.lastrowid
            else:
                receipt_id, saved = row
                if saved != raw:
                    raise ValueError(f'issue {issue_id} was received with different bytes')
        return receipt_id

    def load(self, receipt_id: int) -> Receipt:
        require_id(receipt_id, 'receipt ID')
        row = self.connection.execute(
            'SELECT issue_id, packet FROM receipts WHERE receipt_id = ?', (receipt_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown receipt {receipt_id}')
        packet = validate_packet(row[1])
        if packet.wire.issue_id != row[0]:
            raise ValueError(f'issue identity mismatch in receipt {receipt_id}')
        return Receipt(receipt_id, packet)
