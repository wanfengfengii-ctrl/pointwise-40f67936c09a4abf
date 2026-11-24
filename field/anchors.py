from dataclasses import dataclass
from typing import Iterable

from field.components import FieldComponent
from field.sheets import SheetScope
from survey.faces import require_id, require_name, require_sign


@dataclass(frozen=True, order=True)
class Anchor:
    freeze_id: int
    name: str
    face: str
    sign: int


@dataclass(frozen=True)
class AnchorCheck:
    status: str
    root_sign: int | None
    anchor_names: tuple[str, ...]


def register_anchors(scope: SheetScope, anchors: Iterable[Anchor]) -> tuple[Anchor, ...]:
    by_name = {}
    faces = set(scope.face_ids)
    for anchor in anchors:
        require_id(anchor.freeze_id, 'anchor freeze ID')
        require_name(anchor.name, 'anchor name')
        require_name(anchor.face, 'anchor face')
        require_sign(anchor.sign)
        if anchor.freeze_id != scope.freeze_id or anchor.face not in faces:
            raise ValueError(f'anchor {anchor.name} does not belong to this frozen scope')
        if anchor.name in by_name:
            raise ValueError(f'duplicate anchor {anchor.name}')
        by_name[anchor.name] = anchor
    return tuple(by_name[name] for name in sorted(by_name))


def check_component_anchors(
    component: FieldComponent, anchors: Iterable[Anchor],
) -> AnchorCheck:
    relative = dict(component.relative_signs)
    names = []
    signs = set()
    for anchor in anchors:
        names.append(anchor.name)
        signs.add(anchor.sign * relative[anchor.face])
    anchor_names = tuple(sorted(names))
    if component.relation_conflict or len(signs) > 1:
        return AnchorCheck('conflict', None, anchor_names)
    if not signs:
        return AnchorCheck('pending', None, anchor_names)
    return AnchorCheck('oriented', signs.pop(), anchor_names)
