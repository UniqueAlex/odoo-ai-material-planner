"""Evidence-only adoption conditions and coordination targets; never executes a plan."""
from collections import defaultdict
from decimal import Decimal

RULE = 'decision-support-2'


def build(result, priorities=None, context=None):
    priorities, context = priorities or {}, context or {}
    rows = {r.ref: r for r in result.demands}
    sources = {s.ref: s for s in result.sources}
    conditions, actions = [], []
    def condition(kind, ref):
        item = {'kind': kind, 'ref': ref}
        if item not in conditions:
            conditions.append(item)
    harmed = [i.ref for i in result.impacts if i.change in ('worsened', 'tradeoff')]
    for ref in harmed:
        condition('priority_conflict' if priorities.get(ref) else 'accept_harm', ref)
    for transfer in result.plan.transfers:
        source, receiver = sources[transfer.source_ref], rows[transfer.receiver_ref]
        if source.kind == 'reserved_stock':
            condition('release_reservation', transfer.donor_ref)
            condition('partial_production', transfer.donor_ref)
        condition('other_' + context.get(transfer.receiver_ref, {}).get('other_materials', 'unknown'), transfer.receiver_ref)
        condition('capacity', transfer.receiver_ref)
        actions.append({'kind': 'coordinate_transfer', 'owner': 'warehouse_planner',
                        'source_ref': source.ref, 'donor_ref': transfer.donor_ref,
                        'ref': receiver.ref, 'quantity': transfer.quantity,
                        'deadline': receiver.need_at, 'available_at': source.available_at,
                        'late': source.available_at > receiver.need_at})
    for row in result.demands:
        # Each late allocation is already counted in shortage_at_due. Never add
        # these targets to the total gap, or suggest unallocated late stock is timely.
        allocated = defaultdict(Decimal)
        for part in row.allocations:
            allocated[part.source_ref, part.available_at] += part.quantity
        for (source_ref, available_at), quantity in allocated.items():
            source = sources[source_ref]
            if source.kind == 'purchase_receipt':
                actions.append({'kind': 'expedite' if available_at > row.need_at else 'confirm_receipt',
                                'owner': 'purchasing_warehouse', 'ref': row.ref,
                                'source_ref': source_ref, 'quantity': quantity,
                                'deadline': row.need_at, 'available_at': available_at})
        if row.unfilled > 0:
            actions.append({'kind': 'additional_supply', 'owner': 'purchasing_planner',
                            'ref': row.ref, 'quantity': row.unfilled, 'deadline': row.need_at})
        if row.shortage_at_due > 0:
            actions.append({'kind': 'gap_target', 'owner': 'planner', 'ref': row.ref,
                            'quantity': row.shortage_at_due, 'deadline': row.need_at,
                            'late_quantity': row.shortage_at_due - row.unfilled,
                            'unfilled': row.unfilled})
    # Aggregate reservation movements per donor; show current native evidence,
    # never treat a materials readiness signal as a capacity commitment.
    moved = defaultdict(Decimal)
    for transfer in result.plan.transfers:
        if sources[transfer.source_ref].kind == 'reserved_stock':
            moved[transfer.donor_ref] += transfer.quantity
    production_evidence = [{'ref': ref, 'reserved': rows[ref].actual_reserved,
                            'moved': qty, 'remaining': rows[ref].actual_reserved - qty,
                            'native_readiness': context.get(ref, {}).get('native_readiness'),
                            'production_unit': context.get(ref, {}).get('production_unit')}
                           for ref, qty in moved.items()]
    return {'rule': RULE, 'production_evidence': production_evidence,
            'status': 'priority_conflict' if any(c['kind']=='priority_conflict' for c in conditions)
            else 'conditional' if result.plan.transfers else 'keep',
            'conditions': conditions, 'actions': actions,
            'partial_production_verified': False, 'execution_authorized': False}
