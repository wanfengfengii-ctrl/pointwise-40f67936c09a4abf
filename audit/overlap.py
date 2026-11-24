from collections import defaultdict, deque


def _link(edges: dict, first: tuple, second: tuple, sign: int) -> None:
    edges[first].append((second, sign))
    edges[second].append((first, sign))


def calculate_set_groups(loaded: list) -> tuple[dict, ...]:
    """Settle a V2 case from the selected receipts of one issued set.

    Component pieces of the selected packets are joined through shared-face
    tokens and paired seam ends. A shared face transmits direction even when
    its quantity is zero, and its quantity is counted only once per case.
    """
    freezes = {receipt.packet.wire.freeze_id for receipt in loaded}
    if len(freezes) != 1:
        raise ValueError('selected receipts belong to different freezes')
    set_ids = {receipt.packet.set_id for receipt in loaded}
    if len(set_ids) != 1:
        raise ValueError('selected receipts belong to different sets')
    directed = {}
    edges = defaultdict(list)
    requirements = defaultdict(list)
    shares = defaultdict(list)
    seam_positions = {}
    anchor_records = {}
    for receipt in loaded:
        receipt_id = receipt.receipt_id
        for component in receipt.packet.components:
            node = (receipt_id, component.component_id)
            directed[node] = component.directed
            for share in component.shares:
                shares[share.token].append((node, share.sign, share.quantity))
            for seam in component.seams:
                position = (seam.seam, seam.end)
                record = (node, seam.attach, seam.sign)
                existing = seam_positions.setdefault(position, record)
                if existing[1:] != record[1:]:
                    raise ValueError(
                        f'inconsistent evidence for seam {position[0]} end {position[1]}')
            for anchor in component.anchors:
                record = (node, anchor.attach, anchor.sign)
                existing = anchor_records.setdefault(anchor.name, record)
                if existing[1:] != record[1:]:
                    raise ValueError(f'inconsistent evidence for anchor {anchor.name}')
    for token in sorted(shares):
        records = shares[token]
        if len({quantity for _, _, quantity in records}) != 1:
            raise ValueError(f'inconsistent quantity for shared face {token}')
        (first_node, first_sign, _), *rest = records
        for node, sign, _ in rest:
            _link(edges, first_node, node, first_sign * sign)
    paired = defaultdict(dict)
    for (seam, end), record in seam_positions.items():
        paired[seam][end] = record
    for seam in sorted(paired):
        ends = paired[seam]
        if 'a' in ends and 'b' in ends:
            node_a, attach_a, sign_a = ends['a']
            node_b, attach_b, sign_b = ends['b']
            _link(edges, node_a, node_b, attach_a * attach_b * sign_a * sign_b)
    for node, attach, sign in anchor_records.values():
        requirements[node].append(attach * sign)
    groups = []
    visited = set()
    for start in sorted(directed):
        if start in visited:
            continue
        signs = {start: 1}
        conflict = False
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbor, edge_sign in edges.get(node, ()):
                expected = signs[node] * edge_sign
                if neighbor in signs:
                    if signs[neighbor] != expected:
                        conflict = True
                else:
                    signs[neighbor] = expected
                    queue.append(neighbor)
        members = sorted(signs)
        visited.update(members)
        anchored = False
        for node in members:
            required = requirements.get(node, ())
            if required:
                anchored = True
                if len(set(required)) != 1 or required[0] != signs[node]:
                    conflict = True
        status = 'conflict' if conflict else 'oriented' if anchored else 'pending'
        groups.append((members, signs, status))
    records = []
    for members, signs, status in groups:
        net = None
        if status == 'oriented':
            member_set = set(members)
            net = sum(signs[node] * directed[node] for node in members)
            for token in sorted(shares):
                arrivals = [record for record in shares[token] if record[0] in member_set]
                if len(arrivals) > 1:
                    node, sign, quantity = arrivals[0]
                    net -= (len(arrivals) - 1) * signs[node] * sign * quantity
        records.append({
            'members': [
                {'receipt_id': receipt_id, 'component_id': component_id}
                for receipt_id, component_id in members
            ],
            'receipt_ids': sorted({receipt_id for receipt_id, _ in members}),
            'status': status,
            'net_quantity': net,
        })
    records.sort(
        key=lambda group: (group['members'][0]['receipt_id'], group['members'][0]['component_id']))
    return tuple(records)
