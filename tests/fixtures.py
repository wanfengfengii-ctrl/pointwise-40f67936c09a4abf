import sqlite3
import tempfile
import unittest
from pathlib import Path

from audit.publication import ReportStore
from delivery.archive import IssueArchive
from delivery.issue import issue
from delivery.plan import IssuePlan
from field.anchors import Anchor
from field.inspection import InspectionStore
from field.seams import SeamEnd
from inbox.cases import CaseStore
from inbox.receipts import ReceiptStore
from inbox.wire import encode_packet
from survey.batches import ImportBatch, import_batch
from survey.faces import Face
from survey.freezes import FreezeStore
from survey.revisions import RevisionStore


class Source:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys = ON')
        self.revisions = RevisionStore(self.db)
        self.freezes = FreezeStore(self.db)
        self.inspections = InspectionStore(self.db)
        self.archive = IssueArchive(self.db)
        self.initialize()

    def initialize(self):
        for store in (self.revisions, self.freezes, self.inspections, self.archive):
            store.initialize()

    def snapshot(self, faces=None, relations=()):
        if faces is None:
            faces = (Face('A', 5), Face('B', 7), Face('C', 11))
        revision = import_batch(self.revisions, ImportBatch(faces, relations))
        return revision, self.freezes.freeze_revision(revision)

    def packet(self, freeze, sheet, faces, *, seams=(), anchors=()):
        evidence = self.inspections.inspect(freeze, sheet, faces, seams=seams, anchors=anchors)
        plan = IssuePlan(sheet, faces, evidence.evidence_id)
        return issue(self.inspections, self.archive, freeze, plan)

    def pair(self, freeze, b_sign=-1):
        west = self.packet(freeze, 'west', ('A', 'B'), seams=(
            SeamEnd(freeze, 'AC', 'a', 'A', 1), SeamEnd(freeze, 'BC', 'a', 'B', b_sign),
        ))
        east = self.packet(freeze, 'east', ('C',), seams=(
            SeamEnd(freeze, 'AC', 'b', 'C', 1), SeamEnd(freeze, 'BC', 'b', 'C', 1),
        ), anchors=(Anchor(freeze, 'MC', 'C', 1),))
        return west, east


class Offline:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys = ON')
        self.receipts = ReceiptStore(self.db)
        self.cases = CaseStore(self.db)
        self.reports = ReportStore(self.db)
        self.initialize()

    def initialize(self):
        for store in (self.receipts, self.cases, self.reports):
            store.initialize()

    def select_raw(self, *packets):
        receipts = tuple(self.receipts.receive(packet) for packet in packets)
        return self.cases.select(receipts), receipts


class Workbench(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source_path = self.directory / 'station.sqlite'
        self.offline_path = self.directory / 'night.sqlite'

    def source(self):
        source = Source(self.source_path)
        self.addCleanup(source.db.close)
        return source

    def offline(self):
        offline = Offline(self.offline_path)
        self.addCleanup(offline.db.close)
        return offline


def counts(connection, *tables):
    # Test callers use literal table names from the schema.
    return tuple(connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in tables)


def independent_pair(first_id=100, freeze=23, b_sign=-1):
    west = {
        'sheet': 'external-west',
        'faces': [{'face_id': 'B', 'quantity': 7}, {'face_id': 'A', 'quantity': 5}],
        'relations': [],
        'seams': [
            {'seam': 'AC', 'end': 'a', 'face': 'A', 'sign': 1},
            {'seam': 'BC', 'end': 'a', 'face': 'B', 'sign': b_sign},
        ],
        'anchors': [],
    }
    east = {
        'sheet': 'external-east',
        'faces': [{'face_id': 'C', 'quantity': 11}],
        'relations': [],
        'seams': [
            {'seam': 'AC', 'end': 'b', 'face': 'C', 'sign': 1},
            {'seam': 'BC', 'end': 'b', 'face': 'C', 'sign': 1},
        ],
        'anchors': [{'name': 'MC', 'face': 'C', 'sign': 1}],
    }
    return encode_packet(first_id, freeze, west), encode_packet(first_id + 1, freeze, east)


def independent_sheet(issue_id, freeze, sheet, measurements, *, relations=(), seams=(), anchors=()):
    return encode_packet(issue_id, freeze, {
        'sheet': sheet,
        'faces': [{'face_id': face, 'quantity': amount} for face, amount in measurements],
        'relations': [{'left': a, 'right': b, 'sign': sign} for a, b, sign in relations],
        'seams': [{'seam': name, 'end': position, 'face': face, 'sign': sign}
                  for name, position, face, sign in seams],
        'anchors': [{'name': name, 'face': face, 'sign': sign} for name, face, sign in anchors],
    })
