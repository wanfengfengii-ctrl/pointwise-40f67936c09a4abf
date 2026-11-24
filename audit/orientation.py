from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from audit.coverage import CaseCoverage
from audit.seam_matching import SeamRelation
from field.anchors import check_component_anchors
from field.components import check_local_relations


@dataclass(frozen=True)
class GroupOrientation:
    face_ids: tuple[str, ...]
    status: str
    directions: tuple[tuple[str, int], ...]


def resolve_orientations(
    coverage: CaseCoverage, seams: Iterable[SeamRelation],
) -> tuple[GroupOrientation, ...]:
    relations = (*coverage.relations, *(seam.adjacency for seam in seams))
    components = check_local_relations((face.face_id for face in coverage.faces), relations)
    by_face = defaultdict(list)
    for anchor in coverage.anchors:
        by_face[anchor.face].append(anchor)
    groups = []
    for component in components:
        anchors = (anchor for face in component.face_ids for anchor in by_face.get(face, ()))
        finding = check_component_anchors(component, anchors)
        directions = ()
        if finding.root_sign is not None:
            directions = tuple(
                (face, relative * finding.root_sign) for face, relative in component.relative_signs
            )
        groups.append(GroupOrientation(component.face_ids, finding.status, directions))
    return tuple(groups)
