from field.anchors import Anchor
from field.seams import SeamEnd
from survey.batches import ImportBatch, apply_correction, import_batch
from survey.faces import Adjacency, Face
from tests.fixtures import Workbench, counts


class TestSurvey(Workbench):
    def test_frozen_inspection(self):
        source = self.source()
        revision, freeze = source.snapshot((Face('B', 5), Face('A', 5)))
        evidence = source.inspections.inspect(
            freeze, 'west', ('B', 'A'), anchors=(Anchor(freeze, 'M', 'A', 1),),
            seams=(SeamEnd(freeze, 'AB', 'b', 'B', -1),),
        )
        self.assertEqual(evidence.faces, (Face('A', 5), Face('B', 5)))
        self.assertEqual(evidence.freeze_id, freeze)
        self.assertEqual(evidence.anchors, (Anchor(freeze, 'M', 'A', 1),))
        self.assertEqual(evidence.seams, (SeamEnd(freeze, 'AB', 'b', 'B', -1),))
        self.assertEqual(
            [(part.face_ids, part.status, part.anchor_names) for part in evidence.components],
            [(('A',), 'oriented', ('M',)), (('B',), 'pending', ())],
        )
        self.assertEqual(source.inspections.load(evidence.evidence_id), evidence)
        self.assertEqual(source.freezes.freeze_revision(revision), freeze)

    def test_local_constraints(self):
        source = self.source()
        _, freeze = source.snapshot(
            (Face('A', 8), Face('B', 4), Face('C', 6), Face('D', 3)),
            (Adjacency('A', 'B', 1), Adjacency('A', 'B', -1)),
        )
        evidence = source.inspections.inspect(
            freeze, 'one', ('D', 'B', 'C', 'A'), anchors=(
                Anchor(freeze, 'bound-A', 'A', 1), Anchor(freeze, 'bound-C', 'C', -1),
            ),
        )
        self.assertEqual(
            [(item.face_ids, item.status, item.relation_conflict, item.anchor_names)
             for item in evidence.components],
            [(('A', 'B'), 'conflict', True, ('bound-A',)),
             (('C',), 'oriented', False, ('bound-C',)), (('D',), 'pending', False, ())],
        )

    def test_frozen_after_correction(self):
        source = self.source()
        old_revision, old_freeze = source.snapshot(relations=(Adjacency('A', 'B', -1),))
        old_anchor = Anchor(old_freeze, 'M', 'B', 1)
        old = source.inspections.inspect(old_freeze, 'west', ('A', 'B'), anchors=(old_anchor,))
        new_revision = apply_correction(source.revisions, old_revision, measurements=(Face('B', 70),))
        new_freeze = source.freezes.freeze_revision(new_revision)
        self.assertEqual(source.revisions.load(new_revision).parent_id, old_revision)
        self.assertEqual(source.freezes.load_freeze(new_freeze).revision.faces[1], Face('B', 70))
        self.assertEqual(source.freezes.load_freeze(old_freeze).revision.faces[1], Face('B', 7))
        self.assertEqual(source.inspections.load(old.evidence_id), old)
        again = source.inspections.inspect(old_freeze, 'west', ('A', 'B'), anchors=(old_anchor,))
        self.assertEqual(again.faces, (Face('A', 5), Face('B', 7)))
        self.assertEqual(again.components[0].relative_signs, (('A', 1), ('B', -1)))
        self.assertEqual(again.anchors, (old_anchor,))
        with self.assertRaises(ValueError):
            source.inspections.inspect(new_freeze, 'west', ('A', 'B'), anchors=(old_anchor,))
        with self.assertRaises(ValueError):
            source.inspections.inspect(old_freeze, 'west', ('A',), seams=(SeamEnd(old_freeze, 'E', 'a', 'B', 1),))
        self.assertEqual(counts(source.db, 'inspections'), (2,))

    def test_missing_face(self):
        source = self.source()
        old, _ = source.snapshot()
        before = counts(source.db, 'revisions', 'freezes')
        bad = ImportBatch((Face('A', 10),), (Adjacency('A', 'Z', -1),))
        with self.assertRaisesRegex(ValueError, 'unknown face'):
            import_batch(source.revisions, bad)
        with self.assertRaises(LookupError):
            source.revisions.load(old + 1)
        self.assertEqual(counts(source.db, 'revisions', 'freezes'), before)
        frozen = source.freezes.freeze_revision(old)
        self.assertEqual(source.freezes.load_freeze(frozen).revision.faces[0], Face('A', 5))
        with self.assertRaises(LookupError):
            source.freezes.freeze_revision(old + 1)
        self.assertEqual(counts(source.db, 'revisions', 'freezes'), before)

    def test_invalid_batch_and_correction_are_atomic(self):
        source = self.source()
        old, _ = source.snapshot(relations=(Adjacency('A', 'B', 1),))
        for faces in ((Face('A', 3), Face('A', 3)), (Face('A', True),), (Face('A', None),)):
            with self.subTest(faces=faces), self.assertRaises(ValueError):
                import_batch(source.revisions, ImportBatch(faces))
        with self.assertRaises(ValueError):
            apply_correction(source.revisions, old, remove_faces=('B',))
        self.assertEqual(counts(source.db, 'revisions'), (1,))
        new = apply_correction(source.revisions, old, remove_faces=('B',), relations=())
        self.assertEqual(source.revisions.load(new).faces, (Face('A', 5), Face('C', 11)))
        self.assertEqual(source.revisions.load(old).relations, (Adjacency('A', 'B', 1),))
