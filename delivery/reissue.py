from delivery.archive import IssueArchive


def reissue(archive: IssueArchive, issue_id: int) -> bytes:
    return archive.load_packet(issue_id)
