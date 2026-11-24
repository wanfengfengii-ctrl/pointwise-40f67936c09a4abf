from collections import deque
from dataclasses import dataclass
from typing import Iterable

from field.sheets import SheetScope
from survey.faces import Adjacency


@dataclass(frozen=True)
class FieldComponent:
    face_ids: tuple[str, ...]
    relative_signs: tuple[tuple[str, int], ...]
    relation_conflict: bool


def find_sheet_components(scope: SheetScope) -> tuple[FieldComponent, ...]:
    return check_local_relations(scope.face_ids, scope.relations)


def check_local_relations(
    face_ids: Iterable[str], relations: Iterable[Adjacency],
) -> tuple[FieldComponent, ...]:
    graph = {face_id: [] for face_id in face_ids}
    for relation in relations:
        graph[relation.left].append((relation.right, relation.sign))
        graph[relation.right].append((relation.left, relation.sign))
    seen = set()
    components = []
    for start in sorted(graph):
        if start in seen:
            continue
        relative = {start: 1}
        conflict = False
        queue = deque([start])
        while queue:
            face = queue.popleft()
            for neighbor, multiplier in graph[face]:
                expected = relative[face] * multiplier
                if neighbor in relative:
                    if relative[neighbor] != expected:
                        conflict = True
                else:
                    relative[neighbor] = expected
                    queue.append(neighbor)
        seen.update(relative)
        signs = tuple(sorted(relative.items()))
        components.append(FieldComponent(tuple(face for face, _ in signs), signs, conflict))
    return tuple(components)
