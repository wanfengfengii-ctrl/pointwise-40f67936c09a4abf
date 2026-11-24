from contextlib import closing
from dataclasses import dataclass

from audit.history import read_report
from audit.settlement import settle
from delivery.issue import issue
from delivery.plan import IssuePlan
from field.anchors import Anchor
from field.seams import SeamEnd
from survey.faces import Adjacency, Face
from tests.fixtures import Offline, Source


@dataclass(frozen=True)
class Sheet:
    name: str
    faces: tuple[str, ...]
    anchors: tuple[tuple[str, str, int], ...] = ()
    seams: tuple[tuple[str, str, str, int], ...] = ()


main = Sheet("main", ("A", "B"), (("main-mark", "A", 1),))
neighbor = Sheet("neighbor", ("B", "C"))

# Measurements, frozen relations, approved sheets, then selected sheet indexes
# and expected V1 groups (original faces, status, net quantity).
EXAMPLES = {
    "overlap": (
        (("A", 5), ("B", 7), ("C", 11)),
        (("A", "B", 1), ("B", "C", 1)),
        (main, neighbor),
        (
            ((0,), (("AB", "oriented", 12),)),
            ((0, 1), (("ABC", "oriented", 23),)),
        ),
    ),
    "equal_distinct": (
        (("A", 5), ("B", 7), ("C", 11), ("D", 7)),
        (("A", "B", 1), ("C", "D", 1)),
        (main, Sheet("neighbor", ("C", "D"))),
        (((0, 1), (("AB", "oriented", 12), ("CD", "pending", None))),),
    ),
    "triple": (
        (("A", 5), ("B", 7), ("C", 11), ("D", 13)),
        (("A", "B", 1), ("B", "C", 1), ("B", "D", 1)),
        (main, neighbor, Sheet("third", ("B", "D"))),
        (
            ((0,), (("AB", "oriented", 12),)),
            ((1,), (("BC", "pending", None),)),
            ((2,), (("BD", "pending", None),)),
            ((0, 1), (("ABC", "oriented", 23),)),
            ((0, 2), (("ABD", "oriented", 25),)),
            ((1, 2), (("BCD", "pending", None),)),
            ((0, 1, 2), (("ABCD", "oriented", 36),)),
        ),
    ),
    "zero_bridge": (
        (("A", 5), ("B", 0), ("C", 11), ("D", 13)),
        (("A", "B", 1), ("B", "C", 1)),
        (main, Sheet("neighbor", ("B", "C"), seams=(("span", "a", "C", 1),)),
         Sheet("third", ("D",), seams=(("span", "b", "D", -1),))),
        (
            ((0, 2), (("AB", "oriented", 5), ("D", "pending", None))),
            ((0, 1), (("ABC", "oriented", 16),)),
            ((0, 1, 2), (("ABCD", "oriented", 3),)),
        ),
    ),
    "opposed_reference": (
        (("A", 5), ("B", 11), ("C", 7)),
        (("A", "C", 1), ("B", "C", -1)),
        (Sheet("main", ("A", "C"), main.anchors), neighbor),
        (((0, 1), (("ABC", "oriented", 1),)),),
    ),
    "opposed_overlap": (
        (("P", 0), ("Q", 0), ("X", 5), ("Y", 11)),
        (("P", "X", 1), ("Q", "X", 1), ("P", "Y", 1), ("Q", "Y", -1)),
        (Sheet("main", ("P", "Q", "X"), (("main-mark", "P", 1),)),
         Sheet("neighbor", ("P", "Q", "Y"))),
        (
            ((0,), (("PQX", "oriented", 5),)),
            ((0, 1), (("PQXY", "conflict", None),)),
        ),
    ),
}


def prepare(source, name):
    measurements, relations, sheets, _ = EXAMPLES[name]
    _, freeze = source.snapshot(tuple(Face(*row) for row in measurements),
                                tuple(Adjacency(*row) for row in relations))
    plans = []
    for sheet in sheets:
        evidence = source.inspections.inspect(
            freeze, sheet.name, sheet.faces,
            anchors=tuple(Anchor(freeze, *row) for row in sheet.anchors),
            seams=tuple(SeamEnd(freeze, *row) for row in sheet.seams),
        )
        plans.append(IssuePlan(sheet.name, sheet.faces, evidence.evidence_id))
    return freeze, tuple(plans)


def verify_fixture(name):
    source = Source(":memory:")
    with closing(source.db):
        freeze, plans = prepare(source, name)
        packets = tuple(issue(source.inspections, source.archive, freeze, plan).raw
                        for plan in plans)
    offline = Offline(":memory:")
    with closing(offline.db):
        receipts = tuple(offline.receipts.receive(raw) for raw in packets)
        for indexes, expected in EXAMPLES[name][3]:
            selected = tuple(receipts[index] for index in indexes)
            case_id = offline.cases.select(selected)
            report, first = settle(offline.cases, offline.reports, case_id)
            actual = tuple(("".join(group["face_ids"]), group["status"], group["net_quantity"])
                           for group in report.groups)
            if (actual != expected or report.receipt_ids != selected
                    or read_report(offline.reports, report.report_id) != (report, first)):
                raise AssertionError((name, indexes, expected, actual))
            print(f"{name} {indexes} {actual}")


if __name__ == "__main__":
    for name in EXAMPLES:
        verify_fixture(name)
