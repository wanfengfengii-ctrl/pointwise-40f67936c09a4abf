import json

from delivery.issue import issue
from delivery.plan import IssuePlan
from delivery.reissue import reissue
from field.anchors import Anchor
from field.seams import SeamEnd
from inbox.validation import validate_packet
from inbox.wire import decode_packet, encode_packet
from survey.batches import apply_correction
from survey.faces import Adjacency, Face
from tests.fixtures import Workbench, counts, independent_sheet


class TestDelivery(Workbench):
    def test_foreign_anchor(self):
        source = self.source()
        old_revision, old_freeze = source.snapshot()
        old = source.inspections.inspect(old_freeze, 'west', ('A',), anchors=(Anchor(old_freeze, 'M', 'A', 1),))
        new_revision = apply_correction(source.revisions, old_revision, measurements=(Face('A', 15),))
        new_freeze = source.freezes.freeze_revision(new_revision)
        new = source.inspections.inspect(new_freeze, 'west', ('A',), anchors=(Anchor(new_freeze, 'M', 'A', -1),))
        with self.assertRaisesRegex(ValueError, 'different freeze'):
            issue(source.inspections, source.archive, new_freeze, IssuePlan('west', ('A',), old.evidence_id))
        self.assertEqual(counts(source.db, 'issued_packets'), (0,))
        valid = issue(source.inspections, source.archive, new_freeze, IssuePlan('west', ('A',), new.evidence_id))
        packet = validate_packet(valid.raw)
        self.assertEqual(packet.anchors, (Anchor(new_freeze, 'M', 'A', -1),))
        self.assertEqual(packet.faces, (Face('A', 15),))

    def test_exact_reissue(self):
        source, offline = self.source(), self.offline()
        revision, freeze = source.snapshot()
        first, _ = source.pair(freeze)
        receipt = offline.receipts.receive(first.raw)
        apply_correction(source.revisions, revision, measurements=(Face('B', 77),))
        duplicate = reissue(source.archive, first.issue_id)
        self.assertEqual(duplicate, first.raw)
        self.assertEqual(offline.receipts.receive(duplicate), receipt)
        self.assertEqual(offline.receipts.load(receipt).packet.faces, (Face('A', 5), Face('B', 7)))
        self.assertEqual(counts(offline.db, 'receipts'), (1,))
        with self.assertRaises(LookupError):
            reissue(source.archive, first.issue_id + 100)

    def test_per_face_evidence(self):
        source = self.source()
        _, freeze = source.snapshot()
        reverse, east = source.pair(freeze)
        forward, _ = source.pair(freeze, b_sign=1)
        expected_faces = [{'face_id': 'A', 'quantity': 5}, {'face_id': 'B', 'quantity': 7}]
        for issued, sign in ((reverse, -1), (forward, 1)):
            with self.subTest(sign=sign):
                raw = reissue(source.archive, issued.issue_id)
                self.assertEqual(raw, issued.raw)
                packet = decode_packet(raw)
                self.assertEqual(packet.freeze_id, freeze)
                self.assertEqual(packet.payload['faces'], expected_faces)
                self.assertEqual(packet.payload['relations'], [])
                self.assertEqual(packet.payload['seams'], [
                    {'seam': 'AC', 'end': 'a', 'face': 'A', 'sign': 1},
                    {'seam': 'BC', 'end': 'a', 'face': 'B', 'sign': sign},
                ])
        east_packet = validate_packet(reissue(source.archive, east.issue_id))
        self.assertEqual(east_packet.anchors, (Anchor(freeze, 'MC', 'C', 1),))
        self.assertEqual(east_packet.seams, (
            SeamEnd(freeze, 'AC', 'b', 'C', 1), SeamEnd(freeze, 'BC', 'b', 'C', 1),
        ))

    def test_plan_cannot_extend_inspection(self):
        source = self.source()
        _, freeze = source.snapshot(relations=(Adjacency('A', 'B', -1),))
        evidence = source.inspections.inspect(
            freeze, 'west', ('A', 'B'), anchors=(Anchor(freeze, 'MA', 'A', 1),),
            seams=(SeamEnd(freeze, 'BC', 'a', 'B', -1),),
        )
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            issue(source.inspections, source.archive, freeze, IssuePlan('west', ('A', 'C'), evidence.evidence_id))
        self.assertEqual(counts(source.db, 'issued_packets'), (0,))
        chosen = issue(source.inspections, source.archive, freeze, IssuePlan('west', ('A',), evidence.evidence_id))
        packet = validate_packet(chosen.raw)
        self.assertEqual(packet.faces, (Face('A', 5),))
        self.assertEqual((packet.relations, packet.seams, packet.anchors), ((), (), (Anchor(freeze, 'MA', 'A', 1),)))
        self.assertEqual(counts(source.db, 'issued_packets'), (1,))

    def test_stable_initialization(self):
        source, offline = self.source(), self.offline()
        revision, freeze = source.snapshot()
        issued, east = source.pair(freeze)
        received = offline.receipts.receive(issued.raw)
        correction = apply_correction(source.revisions, revision, measurements=(Face('A', 99),))
        newer = source.freezes.freeze_revision(correction)
        extra = offline.receipts.receive(east.raw)
        source.initialize()
        offline.initialize()
        source.db.close()
        offline.db.close()
        restored, desk = self.source(), self.offline()
        self.assertEqual(restored.freezes.load_freeze(freeze).revision.faces[0], Face('A', 5))
        self.assertEqual(restored.freezes.load_freeze(newer).revision.faces[0], Face('A', 99))
        self.assertEqual(reissue(restored.archive, issued.issue_id), issued.raw)
        self.assertEqual(desk.receipts.receive(issued.raw), received)
        self.assertEqual(desk.receipts.load(extra).packet.wire.raw, east.raw)
        self.assertEqual(counts(restored.db, 'revisions', 'freezes', 'issued_packets'), (2, 2, 2))
        self.assertEqual(counts(desk.db, 'receipts'), (2,))

    def test_damaged_packet(self):
        offline = self.offline()
        good = independent_sheet(51, 3, 'one', (('A', 8),))
        damaged = good.replace(b'"quantity":8', b'"quantity":9')
        dangling = independent_sheet(52, 3, 'bad', (('A', 8),), relations=(('A', 'Z', 1),))
        for raw in (damaged, dangling, b'{bad', b'{"version":1,"version":1}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                offline.receipts.receive(raw)
        self.assertEqual(counts(offline.db, 'receipts'), (0,))
        self.assertEqual(offline.receipts.load(offline.receipts.receive(good)).packet.faces, (Face('A', 8),))

    def test_same_id_different_payload(self):
        offline = self.offline()
        original = independent_sheet(60, 3, 'one', (('A', 5),))
        other = independent_sheet(60, 3, 'one', (('A', 6),))
        self.assertEqual(validate_packet(other).faces, (Face('A', 6),))
        receipt = offline.receipts.receive(original)
        self.assertEqual(offline.receipts.receive(original), receipt)
        with self.assertRaisesRegex(ValueError, 'different bytes'):
            offline.receipts.receive(other)
        self.assertEqual(offline.receipts.load(receipt).packet.wire.raw, original)
        self.assertEqual(counts(offline.db, 'receipts'), (1,))
        # A different byte encoding of the same valid envelope is still a different arrival.
        alternate_bytes = json.dumps(json.loads(original), indent=2).encode('utf-8')
        self.assertEqual(validate_packet(alternate_bytes).faces, (Face('A', 5),))
        with self.assertRaisesRegex(ValueError, 'different bytes'):
            offline.receipts.receive(alternate_bytes)

    def test_mixed_revision(self):
        source, offline = self.source(), self.offline()
        old_revision, old = source.snapshot()
        new_revision = apply_correction(source.revisions, old_revision, measurements=(Face('A', 6),))
        new = source.freezes.freeze_revision(new_revision)
        early = source.packet(old, 'west', ('A',))
        later = source.packet(new, 'west', ('A',))
        early_receipt, later_receipt = (offline.receipts.receive(packet.raw) for packet in (early, later))
        with self.assertRaisesRegex(ValueError, 'different freezes'):
            offline.cases.select((early_receipt, later_receipt))
        with self.assertRaises(LookupError):
            offline.cases.select((early_receipt, 9000))
        self.assertEqual(counts(offline.db, 'receipts', 'audit_cases', 'reports', 'first_receipts'), (2, 0, 0, 0))
        self.assertEqual(offline.cases.load(offline.cases.select((later_receipt,))).freeze_id, new)

    def test_explicit_selection(self):
        offline = self.offline()
        received = [offline.receipts.receive(independent_sheet(i, 11, f's{i}', ((f'F{i}', i),))) for i in (90, 91, 92)]
        case_id = offline.cases.select((received[2], received[0], received[0]))
        another = offline.receipts.receive(independent_sheet(93, 11, 'late', (('D', 4),)))
        offline.db.close()
        reopened = self.offline()
        self.assertEqual(reopened.cases.load(case_id).receipt_ids, (received[0], received[2]))
        self.assertEqual(reopened.receipts.load(another).packet.wire.issue_id, 93)
        self.assertEqual(counts(reopened.db, 'receipts', 'audit_cases'), (4, 1))
