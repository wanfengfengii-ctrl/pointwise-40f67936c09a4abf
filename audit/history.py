from audit.publication import FirstReceipt, Report, ReportStore


class ReportNotFound(LookupError):
    pass


def read_report(reports: ReportStore, report_id: int) -> tuple[Report, FirstReceipt]:
    published = reports.load_published_pair(report_id)
    if published is None:
        raise ReportNotFound(f'unknown published report {report_id}')
    return published
