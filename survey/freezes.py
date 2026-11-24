import sqlite3
from dataclasses import dataclass

from survey.faces import require_id
from survey.revisions import Revision, RevisionStore


@dataclass(frozen=True)
class FrozenRevision:
    freeze_id: int
    revision: Revision


class FreezeStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.revisions = RevisionStore(connection)

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS freezes (
                freeze_id INTEGER PRIMARY KEY,
                revision_id INTEGER NOT NULL UNIQUE REFERENCES revisions(revision_id)
            )
        ''')

    def freeze_revision(self, revision_id: int) -> int:
        self.revisions.load(revision_id)
        with self.connection:
            self.connection.execute('''
                INSERT INTO freezes (revision_id) VALUES (?)
                ON CONFLICT(revision_id) DO NOTHING
            ''', (revision_id,))
            row = self.connection.execute(
                'SELECT freeze_id FROM freezes WHERE revision_id = ?', (revision_id,),
            ).fetchone()
        return row[0]

    def load_freeze(self, freeze_id: int) -> FrozenRevision:
        require_id(freeze_id, 'freeze ID')
        row = self.connection.execute(
            'SELECT revision_id FROM freezes WHERE freeze_id = ?', (freeze_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown freeze {freeze_id}')
        return FrozenRevision(freeze_id, self.revisions.load(row[0]))
