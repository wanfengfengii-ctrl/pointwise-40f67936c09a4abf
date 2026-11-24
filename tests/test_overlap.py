import sqlite3

from audit.history import ReportNotFound, read_report
from audit.settlement import settle
from delivery.issue import issue_set
from delivery.plan import IssuePlan
from delivery.reissue import reissue
from field.anchors import Anchor
from field.seams import SeamEnd
from inbox.wire import decode_packet, encode_packet
from survey.faces import Adjacency, Face
from tests.fixtures import Workbench, counts


def set_packet(issue_id, freeze, set_id, sheet, components):
    return encode_packet(issue_id, freeze, {
        'sheet': sheet, 'set_id': set_id, 'components': components,
    }, version=2)


def component(component_id, directed, shares=(), seams=(), anchors=()):
    return {
        'component_id': component_id, 'directed': directed,
        'shares': list(shares), 'seams': list(seams), 'anchors': list(anchors),
    }


class TestSetIssue(Workbench):
    def overlap_source(self):
        source = self.source()
        _, freeze = source.snapshot(
            relations=(Adjacency('A', 'B', 1), Adjacency('B', 'C', 1)))
        main = source.inspections.inspect(
            freeze, 'main', ('A', 'B'), anchors=(Anchor(freeze, 'main-mark', 'A', 1),))
        neighbor = source.inspections.inspect(freeze, 'neighbor', ('B', 'C'))
        plans = (
            IssuePlan('main', ('A', 'B'), main.evidence_id),
            IssuePlan('neighbor', ('B', 'C'), neighbor.evidence_id),
        )
        return source, freeze, plans

    def test_issue_set_and_reissue(self):
        source, freeze, plans = self.overlap_source()
        set_id, packets = issue_set(source.inspections, source.archive, freeze, plans)
        self.assertTrue(type(set_id) is int and set_id > 0)
        self.assertEqual(len(packets), 2)
        again, _ = issue_set(source.inspections, source.archive, freeze, plans)
        self.assertNotEqual(set_id, again)
        self.assertEqual(len({packet.issue_id for packet in packets}), 2)
        for plan, packet in zip(plans, packets):
            self.assertEqual(reissue(source.archive, packet.issue_id), packet.raw)
            wire = decode_packet(packet.raw)
            self.assertEqual(wire.version, 2)
            self.assertEqual(set(wire.payload), {'sheet', 'set_id', 'components'})
            self.assertEqual((wire.payload['set_id'], wire.payload['sheet']), (set_id, plan.sheet))
        shares = [wire.payload['components'][0]['shares'] for wire in
                  (decode_packet(packet.raw) for packet in packets)]
        self.assertEqual(shares, [[{'token': 's1', 'quantity': 7, 'sign': 1}]] * 2)
        with self.assertRaises(LookupError):
            reissue(source.archive, packets[-1].issue_id + 100)

    def test_payload_keeps_face_details_at_station(self):
        source = self.source()
        _, freeze = source.snapshot(
            (Face('alpha-face', 5), Face('beta-face', 7)),
            (Adjacency('alpha-face', 'beta-face', 1),),
        )
        evidence = source.inspections.inspect(
            freeze, 'wide-sheet', ('alpha-face', 'beta-face'),
            anchors=(Anchor(freeze, 'mark', 'alpha-face', 1),),
        )
        _, packets = issue_set(source.inspections, source.archive, freeze,
                               (IssuePlan('wide-sheet', ('alpha-face', 'beta-face'),
                                          evidence.evidence_id),))
        text = packets[0].raw.decode('utf-8')
        self.assertNotIn('alpha-face', text)
        self.assertNotIn('beta-face', text)
        self.assertNotIn('face_id', text)
        self.assertNotIn('quantity', text)
        payload = decode_packet(packets[0].raw).payload
        self.assertEqual(payload['components'], [{
            'component_id': 'c1', 'directed': 12, 'shares': [], 'seams': [],
            'anchors': [{'name': 'mark', 'sign': 1, 'attach': 1}],
        }])

    def test_issue_set_rejects_contradictory_sheet(self):
        source = self.source()
        _, freeze = source.snapshot(
            relations=(Adjacency('A', 'B', 1), Adjacency('A', 'B', -1)))
        evidence = source.inspections.inspect(freeze, 'main', ('A', 'B'))
        with self.assertRaisesRegex(ValueError, 'contradictory relative directions'):
            issue_set(source.inspections, source.archive, freeze,
                      (IssuePlan('main', ('A', 'B'), evidence.evidence_id),))
        self.assertEqual(counts(source.db, 'issued_packets', 'issued_sets'), (0, 0))

    def test_issue_set_rejects_duplicate_marks(self):
        source = self.source()
        _, freeze = source.snapshot()
        first = source.inspections.inspect(
            freeze, 'one', ('A',), anchors=(Anchor(freeze, 'M', 'A', 1),))
        second = source.inspections.inspect(
            freeze, 'two', ('B',), anchors=(Anchor(freeze, 'M', 'B', 1),))
        plans = (IssuePlan('one', ('A',), first.evidence_id),
                 IssuePlan('two', ('B',), second.evidence_id))
        with self.assertRaisesRegex(ValueError, 'duplicate anchor'):
            issue_set(source.inspections, source.archive, freeze, plans)
        self.assertEqual(counts(source.db, 'issued_packets', 'issued_sets'), (0, 0))

    def test_issue_set_rejects_duplicate_seam_end(self):
        source = self.source()
        _, freeze = source.snapshot()
        first = source.inspections.inspect(
            freeze, 'one', ('A',), seams=(SeamEnd(freeze, 'S', 'a', 'A', 1),))
        second = source.inspections.inspect(
            freeze, 'two', ('B',), seams=(SeamEnd(freeze, 'S', 'a', 'B', 1),))
        third = source.inspections.inspect(
            freeze, 'three', ('C',), seams=(SeamEnd(freeze, 'S', 'b', 'C', 1),))
        plans = (IssuePlan('one', ('A',), first.evidence_id),
                 IssuePlan('two', ('B',), second.evidence_id))
        with self.assertRaisesRegex(ValueError, 'duplicate seam end'):
            issue_set(source.inspections, source.archive, freeze, plans)
        self.assertEqual(counts(source.db, 'issued_packets', 'issued_sets'), (0, 0))
        complementary = (plans[0], IssuePlan('three', ('C',), third.evidence_id))
        set_id, packets = issue_set(source.inspections, source.archive, freeze, complementary)
        self.assertEqual(len(packets), 2)
        self.assertEqual(counts(source.db, 'issued_packets', 'issued_sets'), (2, 1))

    def test_issue_set_plan_count(self):
        source, freeze, plans = self.overlap_source()
        with self.assertRaisesRegex(ValueError, 'one to three'):
            issue_set(source.inspections, source.archive, freeze, ())
        extra = source.inspections.inspect(freeze, 'extra', ('C',))
        four = plans + (IssuePlan('extra', ('C',), extra.evidence_id),
                        IssuePlan('main', ('A',), plans[0].evidence_id))
        with self.assertRaisesRegex(ValueError, 'one to three'):
            issue_set(source.inspections, source.archive, freeze, four)
        self.assertEqual(counts(source.db, 'issued_packets', 'issued_sets'), (0, 0))


class TestSetReceipt(Workbench):
    def test_receive_set_packet(self):
        source = self.source()
        _, freeze = source.snapshot(
            relations=(Adjacency('A', 'B', 1), Adjacency('B', 'C', 1)))
        main = source.inspections.inspect(freeze, 'main', ('A', 'B'))
        neighbor = source.inspections.inspect(freeze, 'neighbor', ('B', 'C'))
        plans = (IssuePlan('main', ('A', 'B'), main.evidence_id),
                 IssuePlan('neighbor', ('B', 'C'), neighbor.evidence_id))
        set_id, packets = issue_set(source.inspections, source.archive, freeze, plans)
        offline = self.offline()
        first = offline.receipts.receive(packets[0].raw)
        self.assertEqual(offline.receipts.receive(packets[0].raw), first)
        self.assertEqual(offline.receipts.receive(packets[1].raw), first + 1)
        other = set_packet(packets[0].issue_id, freeze, set_id, 'main', [component('c1', 5)])
        with self.assertRaisesRegex(ValueError, 'different bytes'):
            offline.receipts.receive(other)
        damaged = packets[1].raw.replace(b'"directed":18', b'"directed":19')
        with self.assertRaises(ValueError):
            offline.receipts.receive(damaged)
        self.assertEqual(counts(offline.db, 'receipts'), (2,))
        loaded = offline.receipts.load(first)
        self.assertEqual(loaded.packet.set_id, set_id)
        self.assertEqual(loaded.packet.components[0].directed, 12)

    def test_invalid_set_packet_structures(self):
        offline = self.offline()
        payloads = [
            {'sheet': 's', 'set_id': 1},
            {'sheet': 's', 'set_id': 1, 'components': []},
            {'sheet': 's', 'set_id': 1, 'components': [component('c1', 5), component('c1', 6)]},
            {'sheet': 's', 'set_id': 1, 'components': [component('c1', True)]},
            {'sheet': 's', 'set_id': 1, 'components': [component('c1', 5, shares=(
                {'token': 't', 'quantity': 1, 'sign': 1},
                {'token': 't', 'quantity': 2, 'sign': 1}))]},
            {'sheet': 's', 'set_id': 1, 'components': [component('c1', 5, seams=(
                {'seam': 'S', 'end': 'a', 'sign': 1, 'attach': 1},
                {'seam': 'S', 'end': 'a', 'sign': 1, 'attach': 1}))]},
            {'sheet': 's', 'set_id': 1, 'components': [component('c1', 5, anchors=(
                {'name': 'M', 'sign': 1, 'attach': 1},
                {'name': 'M', 'sign': -1, 'attach': 1}))]},
            {'sheet': 's', 'set_id': 1, 'components': [component('c1', 5, seams=(
                {'seam': 'S', 'end': 'x', 'sign': 1, 'attach': 1},))]},
            {'sheet': 's', 'set_id': 1, 'components': [component('', 5)]},
        ]
        for offset, payload in enumerate(payloads):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                offline.receipts.receive(encode_packet(100 + offset, 7, payload, version=2))
        self.assertEqual(counts(offline.db, 'receipts'), (0,))

    def test_case_selection_set_rules(self):
        source = self.source()
        _, freeze = source.snapshot(relations=(Adjacency('A', 'B', 1),))
        evidence = source.inspections.inspect(freeze, 'main', ('A', 'B'))
        plan = IssuePlan('main', ('A', 'B'), evidence.evidence_id)
        _, first_set = issue_set(source.inspections, source.archive, freeze, (plan,))
        _, second_set = issue_set(source.inspections, source.archive, freeze, (plan,))
        v1 = source.packet(freeze, 'west', ('A',))
        offline = self.offline()
        one = offline.receipts.receive(first_set[0].raw)
        two = offline.receipts.receive(second_set[0].raw)
        old = offline.receipts.receive(v1.raw)
        with self.assertRaisesRegex(ValueError, 'different sets'):
            offline.cases.select((one, two))
        with self.assertRaisesRegex(ValueError, 'mix packet versions'):
            offline.cases.select((one, old))
        case_id = offline.cases.select((two, two))
        self.assertEqual(offline.cases.load(case_id).receipt_ids, (two,))
        self.assertEqual(counts(offline.db, 'receipts', 'audit_cases'), (3, 1))


class TestSetSettlement(Workbench):
    def overlap_packets(self, source):
        _, freeze = source.snapshot(
            relations=(Adjacency('A', 'B', 1), Adjacency('B', 'C', 1)))
        main = source.inspections.inspect(
            freeze, 'main', ('A', 'B'), anchors=(Anchor(freeze, 'main-mark', 'A', 1),))
        neighbor = source.inspections.inspect(freeze, 'neighbor', ('B', 'C'))
        return issue_set(source.inspections, source.archive, freeze, (
            IssuePlan('main', ('A', 'B'), main.evidence_id),
            IssuePlan('neighbor', ('B', 'C'), neighbor.evidence_id),
        ))

    def test_overlap_settlement_and_history(self):
        source = self.source()
        _, packets = self.overlap_packets(source)
        source.db.close()
        offline = self.offline()
        main_receipt = offline.receipts.receive(packets[0].raw)
        neighbor_receipt = offline.receipts.receive(packets[1].raw)
        case = offline.cases.select((neighbor_receipt, main_receipt))
        report, first = settle(offline.cases, offline.reports, case)
        self.assertEqual(report.groups, ({
            'members': [
                {'receipt_id': main_receipt, 'component_id': 'c1'},
                {'receipt_id': neighbor_receipt, 'component_id': 'c1'},
            ],
            'receipt_ids': [main_receipt, neighbor_receipt],
            'status': 'oriented', 'net_quantity': 23,
        },))
        self.assertEqual(report.receipt_ids, (main_receipt, neighbor_receipt))
        main_case = offline.cases.select((main_receipt,))
        main_report, _ = settle(offline.cases, offline.reports, main_case)
        self.assertEqual(main_report.groups, ({
            'members': [{'receipt_id': main_receipt, 'component_id': 'c1'}],
            'receipt_ids': [main_receipt],
            'status': 'oriented', 'net_quantity': 12,
        },))
        offline.db.close()
        desk = self.offline()
        self.assertEqual(read_report(desk.reports, report.report_id), (report, first))
        with self.assertRaises(ReportNotFound):
            read_report(desk.reports, report.report_id + 100)

    def test_equal_distinct_settlement(self):
        source = self.source()
        _, freeze = source.snapshot(
            (Face('A', 5), Face('B', 7), Face('C', 11), Face('D', 7)),
            (Adjacency('A', 'B', 1), Adjacency('C', 'D', 1)),
        )
        main = source.inspections.inspect(
            freeze, 'main', ('A', 'B'), anchors=(Anchor(freeze, 'main-mark', 'A', 1),))
        neighbor = source.inspections.inspect(freeze, 'neighbor', ('C', 'D'))
        _, packets = issue_set(source.inspections, source.archive, freeze, (
            IssuePlan('main', ('A', 'B'), main.evidence_id),
            IssuePlan('neighbor', ('C', 'D'), neighbor.evidence_id),
        ))
        offline = self.offline()
        main_receipt = offline.receipts.receive(packets[0].raw)
        neighbor_receipt = offline.receipts.receive(packets[1].raw)
        case = offline.cases.select((main_receipt, neighbor_receipt))
        report, _ = settle(offline.cases, offline.reports, case)
        self.assertEqual(report.groups, (
            {'members': [{'receipt_id': main_receipt, 'component_id': 'c1'}],
             'receipt_ids': [main_receipt], 'status': 'oriented', 'net_quantity': 12},
            {'members': [{'receipt_id': neighbor_receipt, 'component_id': 'c1'}],
             'receipt_ids': [neighbor_receipt], 'status': 'pending', 'net_quantity': None},
        ))

    def test_zero_bridge_and_seam_pairing(self):
        source = self.source()
        _, freeze = source.snapshot(
            (Face('A', 5), Face('B', 0), Face('C', 11), Face('D', 13)),
            (Adjacency('A', 'B', 1), Adjacency('B', 'C', 1)),
        )
        main = source.inspections.inspect(
            freeze, 'main', ('A', 'B'), anchors=(Anchor(freeze, 'main-mark', 'A', 1),))
        neighbor = source.inspections.inspect(
            freeze, 'neighbor', ('B', 'C'), seams=(SeamEnd(freeze, 'span', 'a', 'C', 1),))
        third = source.inspections.inspect(
            freeze, 'third', ('D',), seams=(SeamEnd(freeze, 'span', 'b', 'D', -1),))
        _, packets = issue_set(source.inspections, source.archive, freeze, (
            IssuePlan('main', ('A', 'B'), main.evidence_id),
            IssuePlan('neighbor', ('B', 'C'), neighbor.evidence_id),
            IssuePlan('third', ('D',), third.evidence_id),
        ))
        offline = self.offline()
        main_r, neighbor_r, third_r = (
            offline.receipts.receive(packet.raw) for packet in packets)
        full = offline.cases.select((main_r, neighbor_r, third_r))
        report, _ = settle(offline.cases, offline.reports, full)
        self.assertEqual(report.groups, ({
            'members': [
                {'receipt_id': main_r, 'component_id': 'c1'},
                {'receipt_id': neighbor_r, 'component_id': 'c1'},
                {'receipt_id': third_r, 'component_id': 'c1'},
            ],
            'receipt_ids': [main_r, neighbor_r, third_r],
            'status': 'oriented', 'net_quantity': 3,
        },))
        partial = offline.cases.select((main_r, third_r))
        partial_report, _ = settle(offline.cases, offline.reports, partial)
        self.assertEqual(partial_report.groups, (
            {'members': [{'receipt_id': main_r, 'component_id': 'c1'}],
             'receipt_ids': [main_r], 'status': 'oriented', 'net_quantity': 5},
            {'members': [{'receipt_id': third_r, 'component_id': 'c1'}],
             'receipt_ids': [third_r], 'status': 'pending', 'net_quantity': None},
        ))

    def test_opposed_overlap_conflict(self):
        source = self.source()
        _, freeze = source.snapshot(
            (Face('P', 0), Face('Q', 0), Face('X', 5), Face('Y', 11)),
            (Adjacency('P', 'X', 1), Adjacency('Q', 'X', 1),
             Adjacency('P', 'Y', 1), Adjacency('Q', 'Y', -1)),
        )
        main = source.inspections.inspect(
            freeze, 'main', ('P', 'Q', 'X'), anchors=(Anchor(freeze, 'main-mark', 'P', 1),))
        neighbor = source.inspections.inspect(freeze, 'neighbor', ('P', 'Q', 'Y'))
        _, packets = issue_set(source.inspections, source.archive, freeze, (
            IssuePlan('main', ('P', 'Q', 'X'), main.evidence_id),
            IssuePlan('neighbor', ('P', 'Q', 'Y'), neighbor.evidence_id),
        ))
        offline = self.offline()
        main_r = offline.receipts.receive(packets[0].raw)
        neighbor_r = offline.receipts.receive(packets[1].raw)
        case = offline.cases.select((main_r, neighbor_r))
        report, _ = settle(offline.cases, offline.reports, case)
        self.assertEqual(report.groups, ({
            'members': [
                {'receipt_id': main_r, 'component_id': 'c1'},
                {'receipt_id': neighbor_r, 'component_id': 'c1'},
            ],
            'receipt_ids': [main_r, neighbor_r],
            'status': 'conflict', 'net_quantity': None,
        },))

    def test_inconsistent_shared_quantity_cannot_publish(self):
        offline = self.offline()
        first = set_packet(300, 9, 1, 'one', [
            component('c1', 5, shares=({'token': 's1', 'quantity': 7, 'sign': 1},))])
        second = set_packet(301, 9, 1, 'two', [
            component('c1', 8, shares=({'token': 's1', 'quantity': 8, 'sign': 1},))])
        case, _ = offline.select_raw(first, second)
        with self.assertRaisesRegex(ValueError, 'inconsistent quantity'):
            settle(offline.cases, offline.reports, case)
        self.assertEqual(counts(offline.db, 'reports', 'first_receipts'), (0, 0))

    def test_crafted_seam_pairing_and_unpaired_end(self):
        offline = self.offline()
        first = set_packet(310, 9, 1, 'one', [component(
            'c1', 5,
            seams=({'seam': 'S', 'end': 'a', 'sign': 1, 'attach': 1},),
            anchors=({'name': 'M', 'sign': 1, 'attach': 1},))])
        second = set_packet(311, 9, 1, 'two', [component(
            'c1', 11, seams=({'seam': 'S', 'end': 'b', 'sign': -1, 'attach': 1},))])
        case, (one, two) = offline.select_raw(first, second)
        report, _ = settle(offline.cases, offline.reports, case)
        self.assertEqual(report.groups, ({
            'members': [
                {'receipt_id': one, 'component_id': 'c1'},
                {'receipt_id': two, 'component_id': 'c1'},
            ],
            'receipt_ids': [one, two],
            'status': 'oriented', 'net_quantity': -6,
        },))
        solo_case, (alone,) = offline.select_raw(first)
        solo, _ = settle(offline.cases, offline.reports, solo_case)
        self.assertEqual(solo.groups, ({
            'members': [{'receipt_id': alone, 'component_id': 'c1'}],
            'receipt_ids': [alone],
            'status': 'oriented', 'net_quantity': 5,
        },))

    def test_set_report_commit_failure(self):
        offline = self.offline()
        old_case, _ = offline.select_raw(set_packet(330, 9, 1, 'one', [
            component('c1', 5, anchors=({'name': 'M', 'sign': 1, 'attach': 1},))]))
        old = settle(offline.cases, offline.reports, old_case)
        new_case, _ = offline.select_raw(set_packet(331, 9, 1, 'two', [
            component('c1', 7, anchors=({'name': 'M', 'sign': 1, 'attach': 1},))]))
        offline.db.executescript('''
            CREATE TRIGGER fail_set_first_receipt BEFORE INSERT ON first_receipts
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
