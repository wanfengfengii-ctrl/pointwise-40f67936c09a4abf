import sqlite3

from inbox.wire import encode_packet
from survey.faces import require_id


class IssueArchive:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS issued_packets (
                issue_id INTEGER PRIMARY KEY,
                freeze_id INTEGER NOT NULL REFERENCES freezes(freeze_id),
                sheet TEXT NOT NULL,
                packet BLOB NOT NULL
            )
        ''')
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS issued_sets (
                set_id INTEGER PRIMARY KEY,
                freeze_id INTEGER NOT NULL REFERENCES freezes(freeze_id)
            )
        ''')

    def store_packet(self, freeze_id: int, payload: dict) -> tuple[int, bytes]:
        # Reserve the next number while holding the SQLite writer lock.
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            highest, = self.connection.execute(
                'SELECT MAX(issue_id) FROM issued_packets',
            ).fetchone()
            issue_id = (highest or 0) + 1
            raw = encode_packet(issue_id, freeze_id, payload)
            self.connection.execute('''
                INSERT INTO issued_packets (issue_id, freeze_id, sheet, packet)
                VALUES (?, ?, ?, ?)
            ''', (issue_id, freeze_id, payload['sheet'], raw))
        return issue_id, raw

    def store_set_packets(self, freeze_id: int, payloads: tuple[dict, ...]) -> tuple[int, tuple]:
        # Reserve the set number and all issue numbers in one commit.
        payloads = tuple(payloads)
        if not payloads:
            raise ValueError('a set requires at least one packet')
        self.connection.execute('BEGIN IMMEDIATE')
        with self.connection:
            cursor = self.connection.execute(
                'INSERT INTO issued_sets (freeze_id) VALUES (?)', (freeze_id,),
            )
            set_id = cursor.lastrowid
            highest, = self.connection.execute(
                'SELECT MAX(issue_id) FROM issued_packets',
            ).fetchone()
            next_issue_id = highest or 0
            stored = []
            for payload in payloads:
                next_issue_id += 1
                completed = {**payload, 'set_id': set_id}
                raw = encode_packet(next_issue_id, freeze_id, completed, version=2)
                self.connection.execute('''
                    INSERT INTO issued_packets (issue_id, freeze_id, sheet, packet)
                    VALUES (?, ?, ?, ?)
                ''', (next_issue_id, freeze_id, completed['sheet'], raw))
                stored.append((next_issue_id, raw))
        return set_id, tuple(stored)

    def load_packet(self, issue_id: int) -> bytes:
        require_id(issue_id, 'issue ID')
        row = self.connection.execute(
            'SELECT packet FROM issued_packets WHERE issue_id = ?', (issue_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown issue {issue_id}')
        return row[0]
