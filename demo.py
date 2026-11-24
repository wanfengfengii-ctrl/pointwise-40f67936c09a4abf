import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from audit.history import read_report
from audit.publication import ReportStore
from audit.settlement import settle
from delivery.archive import IssueArchive
from delivery.issue import issue, issue_set
from delivery.plan import IssuePlan
from delivery.reissue import reissue
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


def demo_overlap_set(directory):
    station = Path(directory) / 'set-station.sqlite'
    desk = Path(directory) / 'set-offline.sqlite'
    with closing(sqlite3.connect(station)) as source:
        source.execute('PRAGMA foreign_keys = ON')
        revisions, freezes = RevisionStore(source), FreezeStore(source)
        inspections, archive = InspectionStore(source), IssueArchive(source)
        for store in (revisions, freezes, inspections, archive):
            store.initialize()
        revision = import_batch(revisions, ImportBatch(
            (Face('A', 5), Face('B', 7), Face('C', 11)),
            (Adjacency('A', 'B', 1), Adjacency('B', 'C', 1)),
        ))
        freeze = freezes.freeze_revision(revision)
        main_evidence = inspections.inspect(
            freeze, 'main', ('A', 'B'), anchors=(Anchor(freeze, 'main-mark', 'A', 1),))
        neighbor_evidence = inspections.inspect(freeze, 'neighbor', ('B', 'C'))
        set_id, packets = issue_set(inspections, archive, freeze, (
            IssuePlan('main', ('A', 'B'), main_evidence.evidence_id),
            IssuePlan('neighbor', ('B', 'C'), neighbor_evidence.evidence_id),
        ))
        reissued_ok = all(reissue(archive, packet.issue_id) == packet.raw for packet in packets)
    station.unlink()
    with closing(sqlite3.connect(desk)) as connection:
        connection.execute('PRAGMA foreign_keys = ON')
        receipts, cases, reports = ReceiptStore(connection), CaseStore(connection), ReportStore(connection)
        for store in (receipts, cases, reports):
            store.initialize()
        main_receipt = receipts.receive(packets[0].raw)
        neighbor_receipt = receipts.receive(packets[1].raw)
        full_case = cases.select((neighbor_receipt, main_receipt))
        set_report, set_first = settle(cases, reports, full_case)
        main_case = cases.select((main_receipt,))
        main_report, main_first = settle(cases, reports, main_case)
    with closing(sqlite3.connect(desk)) as connection:
        restored_set = read_report(ReportStore(connection), set_report.report_id)
        restored_main = read_report(ReportStore(connection), main_report.report_id)
    expected_set_groups = [{
        'members': [
            {'receipt_id': main_receipt, 'component_id': 'c1'},
            {'receipt_id': neighbor_receipt, 'component_id': 'c1'},
        ],
        'receipt_ids': [main_receipt, neighbor_receipt],
        'status': 'oriented', 'net_quantity': 23,
    }]
    expected_main_groups = [{
        'members': [{'receipt_id': main_receipt, 'component_id': 'c1'}],
        'receipt_ids': [main_receipt],
        'status': 'oriented', 'net_quantity': 12,
    }]
    downstream = {
        'reissue_identical': reissued_ok,
        'set_report_unchanged': restored_set == (set_report, set_first),
        'main_report_unchanged': restored_main == (main_report, main_first),
    }
    downstream_expected = {
        'reissue_identical': True, 'set_report_unchanged': True, 'main_report_unchanged': True,
    }
    if (list(set_report.groups) != expected_set_groups
            or list(main_report.groups) != expected_main_groups
            or downstream != downstream_expected):
        raise SystemExit(
            f'unexpected set result: {set_report.groups!r}, {main_report.groups!r}, {downstream!r}')
    print(f'套号 {set_id} · 案号 {full_case} · 报告号 {set_report.report_id} · '
          f'首执号 {set_first.first_receipt_id}')
    print(f'成套 main、neighbor · 已定向 · 净量 {set_report.groups[0]["net_quantity"]}'
          f'（主幅独签 {main_report.groups[0]["net_quantity"]}）')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v2-overlap',
        'input': {
            'measurements': {
                'faces': [{'face_id': 'A', 'quantity': 5}, {'face_id': 'B', 'quantity': 7},
                          {'face_id': 'C', 'quantity': 11}],
                'relations': [{'left': 'A', 'right': 'B', 'sign': 1},
                              {'left': 'B', 'right': 'C', 'sign': 1}],
            },
            'plans': ['main', 'neighbor'],
            'receipt_ids': [main_receipt, neighbor_receipt],
        },
        'expected': expected_set_groups,
        'actual': list(set_report.groups),
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream,
        'code_paths': [
            'delivery/issue.py', 'delivery/evidence.py', 'delivery/archive.py',
            'inbox/wire.py', 'inbox/validation.py', 'inbox/receipts.py', 'inbox/cases.py',
            'audit/overlap.py', 'audit/settlement.py', 'audit/publication.py',
            'audit/history.py',
        ],
        'oracle': '主幅小计 12、邻幅小计 18，共享面 B 量 7 只计一次：12 + 18 - 7 = 23；'
                  '主幅独签 12。关源后凭实收叠幅件出账，离线库重开按原报告号复领。',
    }, ensure_ascii=False, sort_keys=True))


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
        demo_overlap_set(directory)


if __name__ == '__main__':
    main()
