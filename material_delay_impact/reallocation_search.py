"""Automatically compare distinct allocation tradeoffs over verified F6 plans.

Search is bounded and covers demand orderings, not every possible allocation.
No global-optimum claim, financial cost, ORM access, provider or business writes.
"""
from dataclasses import dataclass
from decimal import Decimal
from itertools import permutations,chain
import hashlib
import json

from . import reallocation as calc
from .core import ZERO

MAX_DEMANDS = 8
MAX_EVALUATIONS = 768
RULE_VERSION = 'recommendation-search-0.2'


@dataclass(frozen=True)
class Alternative:
    ref: str
    strategies: tuple[str, ...]
    result: calc.Result


@dataclass(frozen=True)
class SearchResult:
    alternatives: tuple[Alternative, ...]
    evaluated: int
    unique_outcomes: int
    all_orderings_examined: bool
    global_optimum_proven: bool
    priority_refs: tuple[str, ...]
    priority_basis: str


def metrics(result):
    return {'late_orders': sum(r.shortage_at_due > ZERO for r in result.demands),
        'unknown_coverage_orders': sum(r.full_at is None for r in result.demands),
        'total_material_wait_seconds': result.total_material_wait_seconds,
        'final_unfilled': result.unfilled,
        'worsened_orders': tuple(r.ref for r in result.impacts if r.change in ('worsened', 'tradeoff')),
        'improved_orders': tuple(r.ref for r in result.impacts if r.change in ('improved', 'tradeoff'))}


def _fingerprint(result):
    facts = [(r.ref, str(r.shortage_at_due), str(r.unfilled), r.full_at.isoformat() if r.full_at else None)
        for r in sorted(result.demands, key=lambda r:r.ref)]
    return hashlib.sha256(json.dumps(facts).encode()).hexdigest()


def _identity(plan):
    return tuple((t.source_ref, t.donor_ref, t.receiver_ref, t.quantity) for t in plan.transfers)


def _effort(result):
    return (len(result.plan.transfers), sum((t.quantity for t in result.plan.transfers), ZERO),
        _identity(result.plan))


def _plan(order, key, sources, edges, rows, permission, stock_ref):
    """Fill a desired demand ordering using movable original allocation atoms.

    Each atom has an original donor, so conversion to an explicit F6 plan never
    invents transfer permission or borrows an unallocated source twice. Shared
    remainder is left to the production simulator; only its results are scored.
    """
    atoms = [[source, donor, amount, sources[source][2]]
        for (source, donor), amount in edges.items()
        if amount and (source, donor) in permission.movable_edges]
    atoms.sort(key=lambda a:(a[3], a[0], a[1]))
    fixed_stock = {r.ref: r.reserved if (stock_ref+':reserved:'+r.ref, r.ref) not in permission.movable_edges else ZERO
        for r in rows.values()}
    moved = {}
    for ref in order:
        wanted = rows[ref].quantity - fixed_stock[ref]
        # At a common availability, retain one's own allocation when possible.
        for atom in sorted(atoms, key=lambda a:(a[3], a[1] != ref, a[0], a[1])):
            amount = min(wanted, atom[2])
            if amount:
                atom[2] -= amount
                wanted -= amount
                if atom[1] != ref:
                    edge = (atom[0], atom[1], ref)
                    moved[edge] = moved.get(edge, ZERO) + amount
            if wanted == ZERO:
                break
    if any(atom[2] for atom in atoms):
        raise AssertionError('Movable original allocations must fit active demand')
    return calc.Plan(key, tuple(calc.Transfer(*edge, amount) for edge, amount in sorted(moved.items())))


def search(snapshot, target_ref, assumed_at, permission, priorities=None, *, max_evaluations=MAX_EVALUATIONS):
    if type(max_evaluations) is not int or not 2 <= max_evaluations <= MAX_EVALUATIONS:
        raise ValueError('invalid search budget')
    original, key, sources, edges = calc._context(snapshot, target_ref, assumed_at, permission)
    rows = {r.ref:r for r in original.delayed.demands}
    if len(rows) > MAX_DEMANDS:
        raise ValueError('automatic comparison supports at most eight material demands')
    priorities = priorities or {}
    if type(priorities) is not dict or any(ref not in rows or type(p) is not int or p not in (0,1) for ref,p in priorities.items()):
        raise ValueError('priority must come from known explicit order priority facts')
    high = tuple(sorted(ref for ref in rows if priorities.get(ref,0)==1))
    baseline = calc.simulate(snapshot,target_ref,assumed_at,calc.Plan(key,()),permission)
    if not rows:
        return SearchResult((),1,1,True,False,(),'no_distinct_high_priority')
    best_outcomes = {_fingerprint(baseline):baseline}
    examined = {_identity(baseline.plan)}
    ordered = tuple(sorted(rows, key=lambda ref:(rows[ref].need_at,ref)))
    # Seed explicit priority and reverse ordering before the bounded permutation
    # search, so truncation does not silently exclude the main policy families.
    seeds = [ordered,tuple(reversed(ordered))]
    if high:
        seeds.append(tuple(sorted(rows,key=lambda ref:(-priorities.get(ref,0),rows[ref].need_at,ref))))
    for ref in ordered:
        seeds.append((ref,*(other for other in ordered if other!=ref)))
    evaluated_orders=set()
    exhausted=True
    def single_plans():
        for (source,donor),quantity in sorted(edges.items()):
            if (source,donor) not in permission.movable_edges:continue
            for receiver in ordered:
                if receiver==donor:continue
                amount=min(quantity,rows[receiver].shortage_at_due)
                if amount>ZERO:yield calc.Plan(key,(calc.Transfer(source,donor,receiver,amount),))
    def ordering_plans():
        for order in _orders(seeds,ordered):
            if order not in evaluated_orders:
                evaluated_orders.add(order)
                yield _plan(order,key,sources,edges,rows,permission,snapshot.stock_ref)
    proposals=0
    for plan in chain(single_plans(),ordering_plans()):
        if proposals >= max_evaluations-1:
            exhausted=False
            break
        proposals+=1
        identity = _identity(plan)
        if identity in examined:
            continue
        examined.add(identity)
        try:
            result = calc.simulate(snapshot,target_ref,assumed_at,plan,permission)
        except ValueError:
            # The final simulator is authoritative about protected capacity and
            # permission; an infeasible proposal never becomes a recommendation.
            continue
        signature=_fingerprint(result)
        previous=best_outcomes.get(signature)
        if previous is None or _effort(result) < _effort(previous):
            best_outcomes[signature]=result

    values=list(best_outcomes.values())
    def total(r):
        return r.total_material_wait_seconds if r.total_material_wait_seconds is not None else Decimal('Infinity')
    def late(r):return sum(x.shortage_at_due>ZERO for x in r.demands)
    def score_refs(r, refs):
        selected=[x for x in r.demands if x.ref in refs]
        waits=[x.material_wait_seconds for x in selected]
        return (sum((x.unfilled for x in selected),ZERO),
            sum((x.shortage_at_due for x in selected),ZERO),
            sum(waits,ZERO) if all(x is not None for x in waits) else Decimal('Infinity'))
    strategies=[]
    # An undefined total cannot support a "shortest overall wait" conclusion.
    if baseline.total_material_wait_seconds is not None:
        finite=[r for r in values if r.total_material_wait_seconds is not None]
        strategies.append(('overall_wait',min(finite,key=lambda r:(total(r),late(r),_effort(r)))))
    strategies.append(('fewer_late_orders',min(values,key=lambda r:(late(r),total(r),_effort(r)))))
    if high and len(high)<len(rows):
        strategies.append(('explicit_priority',min(values,key=lambda r:(score_refs(r,high),total(r),late(r),_effort(r)))))
    elif ordered:
        earliest=tuple(ref for ref in ordered if rows[ref].need_at==rows[ordered[0]].need_at)
        if len(earliest)<len(rows):
            strategies.append(('earliest_need',min(values,key=lambda r:(score_refs(r,earliest),total(r),late(r),_effort(r)))))
    grouped={}
    for strategy,result in strategies:
        ref=_fingerprint(result)
        grouped.setdefault(ref,[result,[]])[1].append(strategy)
    alternatives=tuple(Alternative('plan-'+ref[:16],tuple(labels),result)
        for ref,(result,labels) in grouped.items())
    return SearchResult(alternatives,len(examined),len(values),exhausted,False,high,
        'recorded_high_priority' if high and len(high)<len(rows) else 'no_distinct_high_priority')


def _orders(seeds, ordered):
    yield from seeds
    yield from permutations(ordered)
