from collections import defaultdict
from dataclasses import dataclass

from audit.coverage import CaseCoverage
from survey.faces import Adjacency


@dataclass(frozen=True)
class SeamRelation:
    freeze_id: int
    seam: str
    adjacency: Adjacency


def match_received_seams(coverage: CaseCoverage) -> tuple[SeamRelation, ...]:
    by_seam = defaultdict(dict)
    for end in coverage.seams:
        if end.freeze_id != coverage.freeze_id:
            raise ValueError(f'seam {end.seam} belongs to a different freeze')
        key = (end.freeze_id, end.seam)
        positions = by_seam[key]
        existing = positions.setdefault(end.end, end)
        if existing != end:
            raise ValueError(f'inconsistent evidence for seam {end.seam} end {end.end}')
    result = []
    for (freeze_id, name), positions in sorted(by_seam.items()):
        if 'a' in positions and 'b' in positions:
            first, second = positions['a'], positions['b']
            result.append(SeamRelation(
                freeze_id, name, Adjacency(first.face, second.face, first.sign * second.sign),
            ))
    return tuple(result)
