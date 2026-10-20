"""Pure, read-only material-delay calculation over a normalized snapshot.

The Odoo adapter must normalize quantities to one product unit, include all
relevant active demand and supply, and verify that receipt quantities are
pending rather than already included in on-hand stock. This module does no
database access, AI calls, or business writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from collections import deque


ZERO = Decimal("0")


@dataclass(frozen=True)
class Supply:
    ref: str
    purchase_line_ref: str
    quantity: Decimal
    available_at: datetime
    unit: str
    active: bool = True


@dataclass(frozen=True)
class Demand:
    ref: str
    quantity: Decimal
    reserved: Decimal
    need_at: datetime
    unit: str
    active: bool = True


@dataclass(frozen=True)
class MaterialSnapshot:
    ref: str
    taken_at: datetime
    company_ref: str
    warehouse_ref: str
    product_ref: str
    unit: str
    precision: Decimal
    stock_ref: str
    on_hand: Decimal
    supplies: tuple[Supply, ...]
    demands: tuple[Demand, ...]


@dataclass(frozen=True)
class Allocation:
    source_ref: str
    quantity: Decimal
    available_at: datetime


@dataclass(frozen=True)
class DemandOutcome:
    ref: str
    need_at: datetime
    quantity: Decimal
    reserved: Decimal
    public_at_due: Decimal
    shortage_at_due: Decimal
    full_at: datetime | None
    allocations: tuple[Allocation, ...]


@dataclass(frozen=True)
class ScenarioResult:
    demands: tuple[DemandOutcome, ...]
    unallocated: Decimal
    unfilled: Decimal


@dataclass(frozen=True)
class DemandImpact:
    ref: str
    baseline_shortage: Decimal
    delayed_shortage: Decimal
    shortage_delta: Decimal
    new_shortage: Decimal
    baseline_full_at: datetime | None
    delayed_full_at: datetime | None
    change: str
    coverage_grade: str


@dataclass(frozen=True)
class Analysis:
    snapshot_ref: str
    target_purchase_line_ref: str
    assumed_arrival_at: datetime
    baseline: ScenarioResult
    delayed: ScenarioResult
    impacts: tuple[DemandImpact, ...]


def _aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")


def _quantity(value: Decimal, precision: Decimal, field: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")
    if value < ZERO or (positive and value == ZERO):
        raise ValueError(f"{field} must be {'positive' if positive else 'nonnegative'}")
    if value % precision:
        raise ValueError(f"{field} is not a multiple of {precision}")


def _validate(snapshot: MaterialSnapshot, target_ref: str, assumed_at: datetime) -> tuple[tuple[Supply, ...], tuple[Demand, ...]]:
    for field in ("ref", "company_ref", "warehouse_ref", "product_ref", "unit", "stock_ref"):
        if not getattr(snapshot, field):
            raise ValueError(f"snapshot {field} is required")
    if not target_ref:
        raise ValueError("target purchase line is required")
    _aware(snapshot.taken_at, "snapshot time")
    _aware(assumed_at, "assumed arrival time")
    if not isinstance(snapshot.precision, Decimal) or not snapshot.precision.is_finite() or snapshot.precision <= ZERO:
        raise ValueError("unit precision must be a positive Decimal")
    _quantity(snapshot.on_hand, snapshot.precision, "on-hand stock")

    supply_refs: set[str] = set()
    active_supplies: list[Supply] = []
    for supply in snapshot.supplies:
        if not supply.ref or supply.ref in supply_refs:
            raise ValueError("supply evidence references must be unique and nonempty")
        supply_refs.add(supply.ref)
        _aware(supply.available_at, f"supply {supply.ref} time")
        _quantity(supply.quantity, snapshot.precision, f"supply {supply.ref} quantity", positive=True)
        if supply.unit != snapshot.unit:
            raise ValueError(f"supply {supply.ref} unit was not normalized")
        if supply.active:
            if not supply.purchase_line_ref:
                raise ValueError(f"supply {supply.ref} has no purchase-line evidence")
            if supply.available_at <= snapshot.taken_at:
                raise ValueError(f"pending supply {supply.ref} has an overdue or unverified arrival")
            active_supplies.append(supply)

    demand_refs: set[str] = set()
    active_demands: list[Demand] = []
    for demand in snapshot.demands:
        if not demand.ref or demand.ref in demand_refs:
            raise ValueError("demand evidence references must be unique and nonempty")
        demand_refs.add(demand.ref)
        _aware(demand.need_at, f"demand {demand.ref} time")
        _quantity(demand.quantity, snapshot.precision, f"demand {demand.ref} quantity", positive=True)
        _quantity(demand.reserved, snapshot.precision, f"demand {demand.ref} reserved")
        if demand.unit != snapshot.unit:
            raise ValueError(f"demand {demand.ref} unit was not normalized")
        if demand.reserved > demand.quantity:
            raise ValueError(f"demand {demand.ref} reserves more than it needs")
        if demand.active:
            if demand.need_at <= snapshot.taken_at:
                raise ValueError(f"active demand {demand.ref} has an overdue or unverified need time")
            active_demands.append(demand)
        elif demand.reserved:
            raise ValueError(f"inactive demand {demand.ref} still has a reservation")

    if sum((item.reserved for item in active_demands), ZERO) > snapshot.on_hand:
        raise ValueError("reservations exceed on-hand stock")
    targets = [item for item in active_supplies if item.purchase_line_ref == target_ref]
    if not targets:
        raise ValueError("target purchase line has no active pending receipt")
    if any(assumed_at <= item.available_at for item in targets):
        raise ValueError("assumed arrival must delay every active target receipt")
    return tuple(active_supplies), tuple(active_demands)


def _calculate(snapshot: MaterialSnapshot, supplies: tuple[Supply, ...], demands: tuple[Demand, ...]) -> ScenarioResult:
    # Every reservation stays attached to its existing demand. Only the
    # unreserved remainder of on-hand stock enters the public supply pool.
    reserved_total = sum((item.reserved for item in demands), ZERO)
    # Exhausted lots and satisfied demands leave their queues immediately.
    # Each allocation visits only a live lot, preserving the original FIFO.
    pool = deque()
    if snapshot.on_hand > reserved_total:
        pool.append({"ref": f"{snapshot.stock_ref}:unreserved", "left": snapshot.on_hand - reserved_total, "at": snapshot.taken_at})
    records = {
        item.ref: {
            "demand": item,
            "public_at_due": ZERO,
            "shortage_at_due": ZERO,
            "full_at": None,
            "allocations": ([Allocation(f"{snapshot.stock_ref}:reserved:{item.ref}", item.reserved, snapshot.taken_at)] if item.reserved else []),
        }
        for item in demands
    }
    backlog = deque()

    def take(ref: str, wanted: Decimal) -> Decimal:
        taken_total = ZERO
        while pool and taken_total < wanted:
            lot = pool[0]
            taken = min(wanted - taken_total, lot["left"])
            if taken:
                lot["left"] -= taken
                taken_total += taken
                records[ref]["allocations"].append(Allocation(lot["ref"], taken, lot["at"]))
            if lot["left"] == ZERO:
                pool.popleft()
        return taken_total

    events = [(item.available_at, 0, item.ref, item) for item in supplies]
    events.extend((item.need_at, 1, item.ref, item) for item in demands)
    for at, kind, _, item in sorted(events, key=lambda event: (event[0], event[1], event[2])):
        if kind == 0:
            pool.append({"ref": item.ref, "left": item.quantity, "at": at})
            while backlog and pool:
                outstanding = backlog[0]
                taken = take(outstanding["ref"], outstanding["left"])
                outstanding["left"] -= taken
                if outstanding["left"] == ZERO:
                    records[outstanding["ref"]]["full_at"] = at
                    backlog.popleft()
        else:
            wanted = item.quantity - item.reserved
            taken = take(item.ref, wanted)
            shortage = wanted - taken
            records[item.ref]["public_at_due"] = taken
            records[item.ref]["shortage_at_due"] = shortage
            if shortage:
                backlog.append({"ref": item.ref, "left": shortage})
            else:
                records[item.ref]["full_at"] = at

    unallocated = sum((lot["left"] for lot in pool), ZERO)
    unfilled = sum((item["left"] for item in backlog), ZERO)
    incoming = sum((item.quantity for item in supplies), ZERO)
    demand_total = sum((item.quantity for item in demands), ZERO)
    if snapshot.on_hand + incoming != demand_total - unfilled + unallocated:
        raise AssertionError("material quantity did not balance")

    outcomes = tuple(
        DemandOutcome(
            ref=item.ref,
            need_at=item.need_at,
            quantity=item.quantity,
            reserved=item.reserved,
            public_at_due=records[item.ref]["public_at_due"],
            shortage_at_due=records[item.ref]["shortage_at_due"],
            full_at=records[item.ref]["full_at"],
            allocations=tuple(records[item.ref]["allocations"]),
        )
        for item in sorted(demands, key=lambda demand: (demand.need_at, demand.ref))
    )
    return ScenarioResult(outcomes, unallocated, unfilled)


def analyze(snapshot: MaterialSnapshot, target_purchase_line_ref: str, assumed_arrival_at: datetime) -> Analysis:
    """Compare one purchase line's later arrival with the same baseline snapshot."""
    active_supplies, active_demands = _validate(snapshot, target_purchase_line_ref, assumed_arrival_at)
    baseline = _calculate(snapshot, active_supplies, active_demands)
    delayed_supplies = tuple(
        Supply(item.ref, item.purchase_line_ref, item.quantity, assumed_arrival_at, item.unit)
        if item.purchase_line_ref == target_purchase_line_ref else item
        for item in active_supplies
    )
    delayed = _calculate(snapshot, delayed_supplies, active_demands)
    impacts = []
    for before, after in zip(baseline.demands, delayed.demands, strict=True):
        if before.ref != after.ref:
            raise AssertionError("scenario demand order changed")
        delta = after.shortage_at_due - before.shortage_at_due
        if delta > ZERO:
            change = "new_shortage" if before.shortage_at_due == ZERO else "worsened_shortage"
        elif delta < ZERO:
            change = "improved_shortage"
        elif before.full_at and (after.full_at is None or after.full_at > before.full_at):
            change = "later_fulfillment"
        elif before.shortage_at_due:
            change = "existing_shortage_unchanged"
        else:
            change = "no_new_risk"
        grade = "low" if after.shortage_at_due == ZERO else ("medium" if after.full_at else "high")
        impacts.append(DemandImpact(
            ref=before.ref,
            baseline_shortage=before.shortage_at_due,
            delayed_shortage=after.shortage_at_due,
            shortage_delta=delta,
            new_shortage=max(delta, ZERO),
            baseline_full_at=before.full_at,
            delayed_full_at=after.full_at,
            change=change,
            coverage_grade=grade,
        ))
    return Analysis(snapshot.ref, target_purchase_line_ref, assumed_arrival_at, baseline, delayed, tuple(impacts))
