import sqlite3
from contextlib import closing

from audit.history import ReportNotFound, read_report
from audit.settlement import settle
from field.anchors import Anchor
from survey.batches import apply_correction
from survey.faces import Adjacency, Face
from tests.fixtures import Workbench, counts, independent_pair, independent_sheet


class TestAudit(Workbench):
    def test_offline_net_and_history(self):
        source = self.source()
        revision, freeze = source.snapshot()
        packets = source.pair(freeze)
        source.db.close()
        offline = self.offline()
        case, (west, east) = offline.select_raw(*(packet.raw for packet in packets))
        result = settle(offline.cases, offline.reports, case)
        report, first = result
        self.assertEqual((report.case_id, report.freeze_id, report.receipt_ids), (case, freeze, (west, east)))
        self.assertEqual(report.groups, ({
            'face_ids': ['A', 'B', 'C'], 'status': 'oriented', 'net_quantity': 9,
            'provenance': {'A': [west], 'B': [west], 'C': [east]},
        },))
        self.assertEqual((first.report_id, first.case_id), (report.report_id, case))
        offline.db.close()
        source = self.source()
        changed = apply_correction(source.revisions, revision, measurements=(Face('B', 70),))
        self.assertNotEqual(source.freezes.freeze_revision(changed), freeze)
        source.db.close()
        reopened = self.offline()
        self.assertEqual(read_report(reopened.reports, report.report_id), result)
        with self.assertRaises(ReportNotFound):
            read_report(reopened.reports, report.report_id + 1)

    def test_sign_control(self):
        offline = self.offline()
        for issue_id, sign, expected in ((100, -1, 9), (110, 1, 23)):
            with self.subTest(sign=sign):
                case, (west, east) = offline.select_raw(*independent_pair(issue_id, b_sign=sign))
                report, _ = settle(offline.cases, offline.reports, case)
                self.assertEqual(report.groups, ({
                    'face_ids': ['A', 'B', 'C'], 'status': 'oriented', 'net_quantity': expected,
                    'provenance': {'A': [west], 'B': [west], 'C': [east]},
                },))

    def test_group_states(self):
        offline = self.offline()
        # The possible closing edge CA disagrees with the two same-direction edges.
        for offset, closing_edge, marks, expected in (
            (200, True, (), ('conflict', None)),
            (210, False, (), ('pending', None)),
            (220, False, (('M', 'A', 1),), ('oriented', 0)),
            (230, False, (('M', 'A', 1), ('N', 'C', -1)), ('conflict', None)),
            (240, True, (('M', 'A', 1),), ('conflict', None)),
        ):
            with self.subTest(expected=expected, offset=offset):
                a_seams = [('AB', 'a', 'A', 1)]
                if closing_edge:
                    a_seams.append(('CA', 'b', 'A', -1))
                c_marks = tuple(mark for mark in marks if mark[1] == 'C')
                c_packet = independent_sheet(offset + 2, 30, 'C', (('C', -1),),
                    seams=(('BC', 'b', 'C', 1), ('CA', 'a', 'C', 1)), anchors=c_marks)
                a_packet = independent_sheet(offset, 30, 'A', (('A', 2),),
                    seams=a_seams, anchors=tuple(mark for mark in marks if mark[1] == 'A'))
                b_packet = independent_sheet(offset + 1, 30, 'B', (('B', -1),),
                    seams=(('AB', 'b', 'B', 1), ('BC', 'a', 'B', 1)))
                case, (a, b, c) = offline.select_raw(a_packet, b_packet, c_packet)
                report, _ = settle(offline.cases, offline.reports, case)
                self.assertEqual(report.groups, ({
                    'face_ids': ['A', 'B', 'C'], 'status': expected[0], 'net_quantity': expected[1],
                    'provenance': {'A': [a], 'B': [b], 'C': [c]},
                },))

    def test_local_conflict_survives_issue(self):
        source, offline = self.source(), self.offline()
        _, freeze = source.snapshot(relations=(Adjacency('A', 'B', 1), Adjacency('A', 'B', -1)))
        packet = source.packet(freeze, 'west', ('A', 'B'), anchors=(Anchor(freeze, 'MA', 'A', 1),))
        source.db.close()
        case, (receipt,) = offline.select_raw(packet.raw)
        report, _ = settle(offline.cases, offline.reports, case)
        self.assertEqual(report.groups, ({
            'face_ids': ['A', 'B'], 'status': 'conflict', 'net_quantity': None,
            'provenance': {'A': [receipt], 'B': [receipt]},
        },))

    def test_equivalent_representation(self):
        source, offline = self.source(), self.offline()
        edges = (Adjacency('A', 'C', 1), Adjacency('B', 'C', -1))
        revision, freeze = source.snapshot(relations=edges)
        west, east = source.pair(freeze)
        combined = source.packet(freeze, 'all', ('C', 'A', 'B'), anchors=(Anchor(freeze, 'MC', 'C', 1),))
        revised = apply_correction(source.revisions, revision, measurements=(Face('B', -7),),
            relations=(Adjacency('A', 'C', 1), Adjacency('B', 'C', 1)))
        flipped = source.freezes.freeze_revision(revised)
        flipped_west, flipped_east = source.pair(flipped, b_sign=1)
        source.db.close()
        cases = (
            ((west.raw, east.raw), (0, 0, 1)),
            ((east.raw, west.raw), (1, 1, 0)),
            ((combined.raw,), (0, 0, 0)),
            ((flipped_west.raw, flipped_east.raw), (0, 0, 1)),
        )
        for packets, owner in cases:
            case, receipts = offline.select_raw(*packets)
            report, _ = settle(offline.cases, offline.reports, case)
            self.assertEqual(report.groups, ({
                'face_ids': ['A', 'B', 'C'], 'status': 'oriented', 'net_quantity': 9,
                'provenance': {face: [receipts[index]] for face, index in zip('ABC', owner)},
            },))

    def test_overlap_provenance(self):
        offline = self.offline()
        west, east = independent_pair()
        overlap = independent_sheet(102, 23, 'overlap', (('A', 5),), seams=(('AC', 'a', 'A', 1),))
        first_case, (a, c) = offline.select_raw(west, east)
        baseline, _ = settle(offline.cases, offline.reports, first_case)
        case, (_, _, extra) = offline.select_raw(west, east, overlap)
        report, _ = settle(offline.cases, offline.reports, case)
        self.assertEqual(baseline.groups[0]['net_quantity'], 9)
        self.assertEqual(report.groups, ({
            'face_ids': ['A', 'B', 'C'], 'status': 'oriented', 'net_quantity': 9,
            'provenance': {'A': [a, extra], 'B': [a], 'C': [c]},
        },))

    def test_unpaired_seam(self):
        offline = self.offline()
        west, east = independent_pair()
        partial_east = independent_sheet(105, 23, 'partial-east', (('C', 11),),
            seams=(('AC', 'b', 'C', 1),), anchors=(('MC', 'C', 1),))
        case, (w, e) = offline.select_raw(west, partial_east)
        offline.receipts.receive(east)
        report, _ = settle(offline.cases, offline.reports, case)
        self.assertEqual(report.groups, (
            {'face_ids': ['A', 'C'], 'status': 'oriented', 'net_quantity': 16,
             'provenance': {'A': [w], 'C': [e]}},
            {'face_ids': ['B'], 'status': 'pending', 'net_quantity': None, 'provenance': {'B': [w]}},
        ))
        self.assertEqual(report.receipt_ids, (w, e))

    def test_inconsistent_selected_evidence_cannot_publish(self):
        offline = self.offline()
        west, east = independent_pair()
        for packet, message in (
            (independent_sheet(120, 23, 'overlap', (('A', 50),)), 'quantity'),
            (independent_sheet(121, 23, 'overlap', (('A', 5),), seams=(('AC', 'a', 'A', -1),)), 'seam'),
            (independent_sheet(122, 23, 'overlap', (('A', 5),), anchors=(('MC', 'A', -1),)), 'anchor'),
        ):
            with self.subTest(message=message):
                case, _ = offline.select_raw(west, east, packet)
                with self.assertRaisesRegex(ValueError, message):
                    settle(offline.cases, offline.reports, case)
        self.assertEqual(counts(offline.db, 'reports', 'first_receipts'), (0, 0))

    def test_integer_quantities_are_exact_beyond_sqlite_integer_range(self):
        offline = self.offline()
        amount = 10**38 + 9
        packet = independent_sheet(130, 23, 'wide', (('A', amount), ('B', 2)),
            relations=(('A', 'B', -1),), anchors=(('M', 'A', 1),))
        case, _ = offline.select_raw(packet)
        report, _ = settle(offline.cases, offline.reports, case)
        self.assertEqual(report.groups[0]['net_quantity'], 10**38 + 7)

    def test_failed_commit(self):
        offline = self.offline()
        old_case, _ = offline.select_raw(*independent_pair())
        old_result = settle(offline.cases, offline.reports, old_case)
        new_case, _ = offline.select_raw(*independent_pair(140, b_sign=1))
        # Insertion succeeds, but the missing parent forces a real COMMIT failure.
        offline.db.executescript('''
            CREATE TABLE commit_guard (
                parent_id INTEGER REFERENCES reports(report_id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER fail_report_commit AFTER INSERT ON first_receipts
            BEGIN
                INSERT INTO commit_guard (parent_id) VALUES (0);
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            settle(offline.cases, offline.reports, new_case)
        self.assertFalse(offline.db.in_transaction)
        with closing(sqlite3.connect(self.offline_path)) as reopened:
            self.assertEqual(counts(reopened, 'reports', 'first_receipts', 'commit_guard'), (1, 1, 0))
            self.assertEqual(reopened.execute('SELECT case_id FROM reports').fetchall(), [(old_case,)])
        desk = self.offline()
        self.assertEqual(read_report(desk.reports, old_result[0].report_id), old_result)
        with self.assertRaises(ReportNotFound):
            read_report(desk.reports, old_result[0].report_id + 1)
        offline.db.execute('DROP TRIGGER fail_report_commit')
        retried, retry_receipt = settle(offline.cases, offline.reports, new_case)
        self.assertEqual(retried.groups[0]['net_quantity'], 23)
        self.assertEqual(retry_receipt.report_id, retried.report_id)
        self.assertEqual(counts(desk.db, 'reports', 'first_receipts'), (2, 2))

    def test_atomic_pair(self):
        offline = self.offline()
        old_case, _ = offline.select_raw(*independent_pair())
        old = settle(offline.cases, offline.reports, old_case)
        new_case, _ = offline.select_raw(*independent_pair(150))
        offline.db.executescript('''
            CREATE TRIGGER fail_first_receipt BEFORE INSERT ON first_receipts
                WHEN EXISTS (SELECT 1 FROM reports WHERE report_id = NEW.report_id)
            BEGIN
                SELECT RAISE(ABORT, 'first receipt write interrupted');
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt write interrupted'):
            settle(offline.cases, offline.reports, new_case)
        offline.db.close()
        desk = self.offline()
        self.assertEqual(counts(desk.db, 'reports', 'first_receipts'), (1, 1))
        self.assertEqual(read_report(desk.reports, old[0].report_id), old)
