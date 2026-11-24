import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from audit.history import read_report
from audit.publication import ReportStore
from audit.settlement import settle
from delivery.archive import IssueArchive
from delivery.issue import issue
from delivery.plan import IssuePlan
from field.anchors import Anchor
from field.inspection import InspectionStore
from field.seams import SeamEnd
from inbox.cases import CaseStore
from inbox.receipts import ReceiptStore
from survey.batches import ImportBatch, import_batch
from survey.faces import Adjacency, Face
from survey.freezes import FreezeStore
from survey.revisions import RevisionStore


def issue_demo_packets(path, measurements, handoff):
    with closing(sqlite3.connect(path)) as source:
        source.execute('PRAGMA foreign_keys = ON')
        revisions, freezes = RevisionStore(source), FreezeStore(source)
        inspections, archive = InspectionStore(source), IssueArchive(source)
        for store in (revisions, freezes, inspections, archive):
            store.initialize()
        revision = import_batch(revisions, ImportBatch(
            tuple(Face(**face) for face in measurements['faces']),
            tuple(Adjacency(**edge) for edge in measurements['relations']),
        ))
        freeze = freezes.freeze_revision(revision)
        packets = []
        for sheet in handoff['sheets']:
            names = tuple(sheet['face_ids'])
            evidence = inspections.inspect(
                freeze, sheet['sheet'], names,
                seams=(SeamEnd(freeze, **end) for end in sheet['seams']),
                anchors=(Anchor(freeze, **mark) for mark in sheet['anchors']),
            )
            plan = IssuePlan(sheet['sheet'], names, evidence.evidence_id)
            packets.append(issue(inspections, archive, freeze, plan).raw)
    return packets


def main():
    samples = Path(__file__).resolve().parent / 'samples'
    measurements = json.loads((samples / 'measurements.json').read_text(encoding='utf-8'))
    handoff = json.loads((samples / 'handoff.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='northbay-handoff-') as directory:
        station = Path(directory) / 'station.sqlite'
        desk = Path(directory) / 'offline.sqlite'
        packets = issue_demo_packets(station, measurements, handoff)
        station.unlink()
        with closing(sqlite3.connect(desk)) as connection:
            connection.execute('PRAGMA foreign_keys = ON')
            receipts, cases, reports = ReceiptStore(connection), CaseStore(connection), ReportStore(connection)
            for store in (receipts, cases, reports):
                store.initialize()
            west, east = (receipts.receive(packet) for packet in packets)
            case_id = cases.select((east, west))
            report, first_receipt = settle(cases, reports, case_id)
        with closing(sqlite3.connect(desk)) as connection:
            restored_report, restored_receipt = read_report(ReportStore(connection), report.report_id)
    expected = [{
        'face_ids': ['A', 'B', 'C'], 'status': 'oriented', 'net_quantity': 9,
        'provenance': {'A': [west], 'B': [west], 'C': [east]},
    }]
    downstream = {
        'report_unchanged': restored_report == report,
        'first_receipt_unchanged': restored_receipt == first_receipt,
    }
    downstream_expected = {'report_unchanged': True, 'first_receipt_unchanged': True}
    if list(report.groups) != expected or downstream != downstream_expected:
        raise SystemExit(f'unexpected offline result: {report.groups!r}, {downstream!r}')
    print(f'案号 {case_id} · 报告号 {report.report_id} · 首执号 {first_receipt.first_receipt_id}')
    print(f'原面 A、B、C · 已定向 · 净量 {report.groups[0]["net_quantity"]}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v7',
        'input': {'measurements': measurements, 'handoff': handoff, 'receipt_ids': [west, east]},
        'expected': expected,
        'actual': report.groups,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream,
        'code_paths': [
            'delivery/evidence.py', 'inbox/cases.py', 'audit/coverage.py',
            'audit/seam_matching.py', 'audit/orientation.py', 'audit/settlement.py',
            'audit/publication.py', 'audit/history.py',
        ],
        'oracle': 'C 为 +1，两缝推出 A 为 +1、B 为 -1，手算 5 - 7 + 11 = 9。复领与原提交结果逐项比较。',
    }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
