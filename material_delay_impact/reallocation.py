"""Explicit virtual allocation plans over an immutable normalized snapshot.

No ORM, credential or provider access. The adapter must separately verify
business restrictions and supply an allowlist; absent permission fails closed.
The existing arrival-only core is deliberately unchanged.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json

from .core import Allocation, Analysis, MaterialSnapshot, ZERO, _quantity, analyze

MAX_TRANSFERS = 200
RULE_VERSION = "reallocation-0.1"


@dataclass(frozen=True)
class Transfer:
    source_ref: str
    donor_ref: str
    receiver_ref: str
    quantity: Decimal


@dataclass(frozen=True)
class Plan:
    scenario_key: str
    transfers: tuple[Transfer, ...]


@dataclass(frozen=True)
class Permission:
    scenario_key: str
    # A source may be transferable from one demand but restricted on another.
    movable_edges: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class SourceBalance:
    ref: str
    kind: str
    quantity: Decimal
    available_at: datetime
    allocated: Decimal
    unallocated: Decimal


@dataclass(frozen=True)
class Outcome:
    ref: str
    need_at: datetime
    quantity: Decimal
    actual_reserved: Decimal
    virtual_current_stock: Decimal
    covered_at_due: Decimal
    shortage_at_due: Decimal
    full_at: datetime | None
    unfilled: Decimal
    allocations: tuple[Allocation, ...]

    @property
    def material_wait_seconds(self) -> Decimal | None:
        if self.full_at is None:
            return None
        duration = self.full_at - self.need_at
        # Avoid floating-point loss, including subsecond timestamps.
        return (Decimal(duration.days * 86400 + duration.seconds)
                + Decimal(duration.microseconds) / Decimal(1000000))


@dataclass(frozen=True)
class Impact:
    ref: str
    shortage_before: Decimal
    shortage_after: Decimal
    shortage_delta: Decimal
    full_at_before: datetime | None
    full_at_after: datetime | None
    unfilled_before: Decimal
    unfilled_after: Decimal
    material_wait_before_seconds: Decimal | None
    material_wait_after_seconds: Decimal | None
    change: str
    allocation_changed: bool


@dataclass(frozen=True)
class Result:
    scenario_key: str
    original: Analysis
    plan: Plan
    demands: tuple[Outcome, ...]
    sources: tuple[SourceBalance, ...]
    impacts: tuple[Impact, ...]
    unallocated: Decimal
    unfilled: Decimal
    # None if any demand cannot be fully covered. Never a partial total.
    total_material_wait_seconds: Decimal | None
    total_material_wait_before_seconds: Decimal | None
    material_wait_delta_seconds: Decimal | None


@dataclass(frozen=True)
class Candidate:
    source_ref: str
    source_kind: str
    donor_ref: str
    receiver_ref: str
    quantity: Decimal
    available_at: datetime
    donor_need_at: datetime
    receiver_need_at: datetime
    available_by_receiver_need: bool
    may_improve_known_coverage_time: bool


def scenario_key(snapshot: MaterialSnapshot, target_ref: str, assumed_at: datetime) -> str:
    """Bind a plan to all facts, scope, the arrival hypothesis and this rule."""
    payload = {"snapshot": asdict(snapshot), "target": target_ref,
               "assumed_at": assumed_at.isoformat(), "rule": RULE_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _sources(snapshot, original):
    sources = {}

    def add(ref, kind, quantity, at):
        if ref in sources:
            raise ValueError("source evidence references collide")
        sources[ref] = (kind, quantity, at)

    reserved = sum((r.reserved for r in original.delayed.demands), ZERO)
    add(snapshot.stock_ref + ":unreserved", "unreserved_stock", snapshot.on_hand - reserved, snapshot.taken_at)
    for row in original.delayed.demands:
        if row.reserved:
            add(snapshot.stock_ref + ":reserved:" + row.ref, "reserved_stock", row.reserved, snapshot.taken_at)
    for supply in snapshot.supplies:
        if supply.active:
            at = original.assumed_arrival_at if supply.purchase_line_ref == original.target_purchase_line_ref else supply.available_at
            add(supply.ref, "purchase_receipt", supply.quantity, at)
    return sources


def _context(snapshot, target_ref, assumed_at, permission):
    original = analyze(snapshot, target_ref, assumed_at)
    key = scenario_key(snapshot, target_ref, assumed_at)
    if not isinstance(permission, Permission) or permission.scenario_key != key:
        raise ValueError("allocation permission belongs to a different or expired scenario")
    if not isinstance(permission.movable_edges, frozenset):
        raise ValueError("allocation permission must be an immutable allowlist")
    sources = _sources(snapshot, original)
    edges = defaultdict(lambda: ZERO)
    for row in original.delayed.demands:
        for part in row.allocations:
            edges[part.source_ref, row.ref] += part.quantity
    if any(edge not in edges for edge in permission.movable_edges):
        raise ValueError("allocation permission contains an unknown source or demand")
    return original, key, sources, edges


def candidates(snapshot: MaterialSnapshot, target_ref: str, assumed_at: datetime,
               receiver_ref: str, permission: Permission, *, later_only: bool = True) -> tuple[Candidate, ...]:
    """Offer authorized edges, not a recommendation or an executed transfer."""
    original, _, sources, edges = _context(snapshot, target_ref, assumed_at, permission)
    rows = {r.ref: r for r in original.delayed.demands}
    if receiver_ref not in rows:
        raise ValueError("receiver demand is inactive or unavailable")
    receiver = rows[receiver_ref]
    if receiver.shortage_at_due == ZERO:
        return ()
    result = []
    for (source_ref, donor_ref), amount in sorted(edges.items()):
        donor = rows[donor_ref]
        if donor_ref == receiver_ref or (source_ref, donor_ref) not in permission.movable_edges:
            continue
        if later_only and donor.need_at <= receiver.need_at:
            continue
        kind, _, at = sources[source_ref]
        result.append(Candidate(source_ref, kind, donor_ref, receiver_ref,
            min(amount, receiver.shortage_at_due), at, donor.need_at, receiver.need_at,
            at <= receiver.need_at, receiver.full_at is None or at < receiver.full_at))
    return tuple(result)


def simulate(snapshot: MaterialSnapshot, target_ref: str, assumed_at: datetime,
             plan: Plan, permission: Permission) -> Result:
    original, key, sources, edges = _context(snapshot, target_ref, assumed_at, permission)
    if not isinstance(plan, Plan) or plan.scenario_key != key:
        raise ValueError("allocation plan belongs to a different or expired scenario")
    if not isinstance(plan.transfers, tuple) or len(plan.transfers) > MAX_TRANSFERS:
        raise ValueError("allocation plan has an invalid number of transfers")
    rows = {r.ref: r for r in original.delayed.demands}
    outgoing = defaultdict(lambda: ZERO)
    incoming = defaultdict(lambda: ZERO)
    seen = set()
    for transfer in plan.transfers:
        if not isinstance(transfer, Transfer):
            raise ValueError("an explicit transfer record is required")
        if any(not isinstance(ref, str) or not ref for ref in
               (transfer.source_ref, transfer.donor_ref, transfer.receiver_ref)):
            raise ValueError("transfer references must be nonempty strings")
        if (transfer.source_ref, transfer.donor_ref) not in permission.movable_edges:
            raise ValueError("source allocation is restricted or unavailable")
        if transfer.receiver_ref not in rows or transfer.receiver_ref == transfer.donor_ref:
            raise ValueError("transfer requires distinct active donor and receiver demands")
        _quantity(transfer.quantity, snapshot.precision, "transfer quantity", positive=True)
        identity = (transfer.source_ref, transfer.donor_ref, transfer.receiver_ref)
        if identity in seen:
            raise ValueError("duplicate transfer; consolidate its quantity explicitly")
        seen.add(identity)
        outgoing[transfer.source_ref, transfer.donor_ref] += transfer.quantity
        incoming[transfer.source_ref, transfer.receiver_ref] += transfer.quantity
    for edge, amount in outgoing.items():
        if amount > edges[edge]:
            raise ValueError("transfers exceed the donor's original source allocation")

    # Only existing reserved stock is protected by default. An explicit incoming
    # transfer is a scenario commitment, including its real future availability.
    pins = defaultdict(lambda: ZERO)
    for row in original.delayed.demands:
        if row.reserved:
            source_ref = snapshot.stock_ref + ":reserved:" + row.ref
            pins[source_ref, row.ref] = row.reserved - outgoing[source_ref, row.ref]
    for edge, amount in incoming.items():
        pins[edge] += amount
    pinned_demand = defaultdict(lambda: ZERO)
    pinned_source = defaultdict(lambda: ZERO)
    allocations = {ref: [] for ref in rows}
    for (source_ref, demand_ref), amount in sorted(pins.items()):
        if amount:
            pinned_source[source_ref] += amount
            pinned_demand[demand_ref] += amount
            allocations[demand_ref].append(Allocation(source_ref, amount, sources[source_ref][2]))
    if any(amount > rows[ref].quantity for ref, amount in pinned_demand.items()):
        raise ValueError("transfers and protected stock exceed a receiver's demand")
    if any(amount > sources[ref][1] for ref, amount in pinned_source.items()):
        raise ValueError("transfers exceed a physical source quantity")

    # Remaining shared supply is recalculated for everyone. A donor may recover
    # coverage from quantity freed elsewhere, including the same bulk receipt;
    # do not manufacture a shortage by imposing an exclusive source-to-MO tie.
    pool = []
    backlog = []
    def take(demand_ref, wanted):
        total = ZERO
        for lot in pool:
            source_ref, _, _ = lot
            amount = min(wanted - total, lot[1])
            if amount:
                lot[1] -= amount
                total += amount
                allocations[demand_ref].append(Allocation(source_ref, amount, lot[2]))
            if total == wanted:
                break
        return total

    events = [(at, 0, ref, quantity - pinned_source[ref]) for ref, (_, quantity, at) in sources.items()]
    events.extend((row.need_at, 1, row.ref, row.quantity - pinned_demand[row.ref]) for row in rows.values())
    for at, kind, ref, amount in sorted(events, key=lambda item: (item[0], item[1], item[2])):
        if kind == 0:
            if amount:
                pool.append([ref, amount, at])
            for outstanding in backlog:
                outstanding[1] -= take(outstanding[0], outstanding[1])
        else:
            left = amount - take(ref, amount)
            if left:
                backlog.append([ref, left])

    outcomes, impacts = [], []
    used_source = defaultdict(lambda: ZERO)
    for before in original.delayed.demands:
        parts = tuple(sorted(allocations[before.ref], key=lambda a: (a.available_at, a.source_ref)))
        covered = sum((part.quantity for part in parts), ZERO)
        timely = sum((part.quantity for part in parts if part.available_at <= before.need_at), ZERO)
        full_at = max([before.need_at, *(part.available_at for part in parts)]) if covered == before.quantity else None
        current = sum((part.quantity for part in parts if sources[part.source_ref][0] != "purchase_receipt"), ZERO)
        after = Outcome(before.ref, before.need_at, before.quantity, before.reserved, current,
                        timely, before.quantity - timely, full_at, before.quantity - covered, parts)
        outcomes.append(after)
        for part in parts:
            used_source[part.source_ref] += part.quantity
        unfilled_before = before.quantity - sum((a.quantity for a in before.allocations), ZERO)
        wait_before = None if before.full_at is None else _seconds(before.full_at - before.need_at)
        effects = [after.shortage_at_due.compare(before.shortage_at_due), after.unfilled.compare(unfilled_before)]
        if before.full_at is not None and after.full_at is not None:
            effects.append(Decimal((after.full_at > before.full_at) - (after.full_at < before.full_at)))
        elif before.full_at != after.full_at:
            effects.append(Decimal(1 if after.full_at is None else -1))
        positive, negative = any(x > 0 for x in effects), any(x < 0 for x in effects)
        change = "tradeoff" if positive and negative else "worsened" if positive else "improved" if negative else "unchanged"
        impacts.append(Impact(before.ref, before.shortage_at_due, after.shortage_at_due,
            after.shortage_at_due - before.shortage_at_due, before.full_at, after.full_at,
            unfilled_before, after.unfilled, wait_before, after.material_wait_seconds, change,
            tuple(sorted(before.allocations, key=lambda a: (a.available_at, a.source_ref))) != parts))
    balances = tuple(SourceBalance(ref, kind, quantity, at, used_source[ref], quantity-used_source[ref])
        for ref, (kind, quantity, at) in sorted(sources.items()))
    unallocated = sum((r.unallocated for r in balances), ZERO)
    unfilled = sum((r.unfilled for r in outcomes), ZERO)
    total_supply = sum((r.quantity for r in balances), ZERO)
    total_demand = sum((r.quantity for r in outcomes), ZERO)
    if any(r.unallocated < ZERO for r in balances) or any(r.unfilled < ZERO for r in outcomes):
        raise AssertionError("allocation exceeds source or demand")
    if total_supply != total_demand - unfilled + unallocated:
        raise AssertionError("material quantities do not balance")
    if (unfilled, unallocated) != (original.delayed.unfilled, original.delayed.unallocated):
        raise AssertionError("reallocation cannot create supply or artificial final shortages")
    waits = [row.material_wait_seconds for row in outcomes]
    total_wait = sum(waits, ZERO) if all(value is not None for value in waits) else None
    before_waits = [row.material_wait_before_seconds for row in impacts]
    total_before = sum(before_waits, ZERO) if all(value is not None for value in before_waits) else None
    delta = total_wait - total_before if total_wait is not None and total_before is not None else None
    return Result(key, original, plan, tuple(outcomes), balances, tuple(impacts), unallocated, unfilled,
                  total_wait, total_before, delta)


def _seconds(duration):
    return Decimal(duration.days * 86400 + duration.seconds) + Decimal(duration.microseconds) / Decimal(1000000)
