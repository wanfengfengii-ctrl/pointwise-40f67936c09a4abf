from dataclasses import dataclass
from typing import Iterable

from field.sheets import SheetScope
from survey.faces import require_id, require_name, require_sign


@dataclass(frozen=True, order=True)
class SeamEnd:
    freeze_id: int
    seam: str
    end: str
    face: str
    sign: int


def register_seam_ends(scope: SheetScope, seams: Iterable[SeamEnd]) -> tuple[SeamEnd, ...]:
    by_position = {}
    faces = set(scope.face_ids)
    for seam in seams:
        require_id(seam.freeze_id, 'seam freeze ID')
        require_name(seam.seam, 'seam name')
        require_name(seam.face, 'seam face')
        require_sign(seam.sign)
        if seam.freeze_id != scope.freeze_id or seam.face not in faces:
            raise ValueError(f'seam {seam.seam} does not belong to this frozen scope')
        if seam.end not in ('a', 'b'):
            raise ValueError(f'invalid position for seam {seam.seam}')
        position = (seam.seam, seam.end)
        if position in by_position:
            raise ValueError(f'duplicate seam end {position}')
        by_position[position] = seam
    return tuple(by_position[position] for position in sorted(by_position))
