import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Iterable

from survey.faces import Adjacency, Face, require_id, validate_measurements


@dataclass(frozen=True)
class Revision:
    revision_id: int
    parent_id: int | None
    faces: tuple[Face, ...]
    relations: tuple[Adjacency, ...]


class RevisionStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('''
            CREATE TABLE IF NOT EXISTS revisions (
                revision_id INTEGER PRIMARY KEY,
                parent_id INTEGER REFERENCES revisions(revision_id),
                snapshot TEXT NOT NULL
            )
        ''')

    def append(
        self, faces: Iterable[Face], relations: Iterable[Adjacency],
        *, parent_id: int | None = None,
    ) -> int:
        faces, relations = validate_measurements(faces, relations)
        if parent_id is not None:
            self._row(parent_id)
        snapshot = json.dumps({
            'faces': [asdict(face) for face in faces],
            'relations': [asdict(relation) for relation in relations],
        }, sort_keys=True)
        with self.connection:
            cursor = self.connection.execute(
                'INSERT INTO revisions (parent_id, snapshot) VALUES (?, ?)',
                (parent_id, snapshot),
            )
        return cursor.lastrowid

    def _row(self, revision_id: int) -> tuple:
        require_id(revision_id, 'revision ID')
        row = self.connection.execute(
            'SELECT parent_id, snapshot FROM revisions WHERE revision_id = ?',
            (revision_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown revision {revision_id}')
        return row

    def load(self, revision_id: int) -> Revision:
        parent_id, raw = self._row(revision_id)
        snapshot = json.loads(raw)
        return Revision(
            revision_id, parent_id,
            tuple(Face(**item) for item in snapshot['faces']),
            tuple(Adjacency(**item) for item in snapshot['relations']),
        )
