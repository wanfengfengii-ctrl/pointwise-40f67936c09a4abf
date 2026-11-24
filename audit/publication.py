import json
import sqlite3
from dataclasses import dataclass

from survey.faces import require_id


@dataclass(frozen=True)
class Report:
    report_id: int
    case_id: int
    freeze_id: int
    receipt_ids: tuple[int, ...]
    groups: tuple[dict, ...]


@dataclass(frozen=True)
class FirstReceipt:
    first_receipt_id: int
    report_id: int
    case_id: int


class ReportStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY,
                case_id INTEGER NOT NULL REFERENCES audit_cases(case_id),
                freeze_id INTEGER NOT NULL,
                body TEXT NOT NULL
            )
        ''')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS first_receipts (
                first_receipt_id INTEGER PRIMARY KEY,
                report_id INTEGER NOT NULL UNIQUE REFERENCES reports(report_id)
            )
        ''')

    def publish(
        self, case_id: int, freeze_id: int, receipt_ids: tuple[int, ...], groups: tuple[dict, ...],
    ) -> tuple[Report, FirstReceipt]:
        body = json.dumps({'receipt_ids': receipt_ids, 'groups': groups}, sort_keys=True)
        saved = json.loads(body)
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            cursor = self.connection.execute(
                'INSERT INTO reports (case_id, freeze_id, body) VALUES (?, ?, ?)',
                (case_id, freeze_id, body),
            )
            report_id = cursor.lastrowid
            cursor = self.connection.execute(
                'INSERT INTO first_receipts (report_id) VALUES (?)', (report_id,),
            )
            first_receipt_id = cursor.lastrowid
        return (
            Report(report_id, case_id, freeze_id, tuple(saved['receipt_ids']), tuple(saved['groups'])),
            FirstReceipt(first_receipt_id, report_id, case_id),
        )

    def load_published_pair(self, report_id: int) -> tuple[Report, FirstReceipt] | None:
        require_id(report_id, 'report ID')
        row = self.connection.execute('''
            SELECT r.case_id, r.freeze_id, r.body, f.first_receipt_id
            FROM reports AS r JOIN first_receipts AS f ON f.report_id = r.report_id
            WHERE r.report_id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            return None
        case_id, freeze_id, body, first_receipt_id = row
        saved = json.loads(body)
        return (
            Report(report_id, case_id, freeze_id, tuple(saved['receipt_ids']), tuple(saved['groups'])),
            FirstReceipt(first_receipt_id, report_id, case_id),
        )
