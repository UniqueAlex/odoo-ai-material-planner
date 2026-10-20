"""Fresh read-only adapter for virtual plans; no provider/key/cache operations."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

from odoo.exceptions import UserError
from . import snapshot
from .. import reallocation, reallocation_ai, reallocation_search, decision_support


def request(env, order_id, line_id, arrival, receiver_ref=None, transfers=None, expected_facts_key=None, *, recommend=False):
    if type(line_id) is not int or line_id <= 0 or not isinstance(arrival, str) or len(arrival) > 64:
        raise UserError(env._("Select a purchase line and a valid arrival date and time."))
    try:
        assumed_at = datetime.fromisoformat(arrival)
        if assumed_at.tzinfo is None or assumed_at.utcoffset() is None:
            raise ValueError()
        assumed_at = assumed_at.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise UserError(env._("The arrival date must include a valid timezone.")) from None
    if receiver_ref is not None and (not isinstance(receiver_ref, str) or not 0 < len(receiver_ref) <= 200):
        raise UserError(env._("Select an available manufacturing demand."))
    if transfers is not None and (type(transfers) is not list or len(transfers) > reallocation.MAX_TRANSFERS):
        raise UserError(env._("The virtual transfer plan has an invalid size."))
    if expected_facts_key is not None and (not isinstance(expected_facts_key, str) or len(expected_facts_key) != 64):
        raise UserError(env._("The reallocation scenario is no longer current. Analyze again."))
    if transfers is not None and expected_facts_key is None:
        raise UserError(env._("Prepare a current reallocation scenario before comparing a plan."))

    # Existing scope checks exclude linked routes, owners, lots, packages,
    # picked stock, other demands, incomplete visibility and unsupported MOs.
    report, material, original = snapshot.calculate(env, order_id, line_id, assumed_at, include_snapshot=True)
    facts = asdict(material)
    # Each request reads fresh facts. A moving read timestamp alone does not
    # invalidate a plan; source/demand timestamps and all quantities still do.
    facts.pop("taken_at")
    facts.pop("ref")
    facts["supplies"] = sorted(facts["supplies"], key=lambda r: r["ref"])
    facts["demands"] = sorted(facts["demands"], key=lambda r: r["ref"])
    evidence = sorted(report["evidence"], key=lambda r: r["ref"])
    payload = {"facts": facts, "evidence": evidence, "arrival": assumed_at.isoformat(),
               "target": line_id, "rule": reallocation.RULE_VERSION,
               "scope": [env.cr.dbname, env.uid, sorted(env.companies.ids), order_id,
                         env.context.get("lang") or env.user.lang]}
    facts_key = hashlib.sha256(json.dumps(payload, default=str, sort_keys=True).encode()).hexdigest()
    if expected_facts_key is not None and facts_key != expected_facts_key:
        raise UserError(env._("The reallocation scenario is no longer current. Analyze again."))
    target = f"purchase.order.line:{line_id}"
    key = reallocation.scenario_key(material, target, assumed_at)
    permission = reallocation.Permission(key, frozenset(
        (part.source_ref, row.ref) for row in original.delayed.demands for part in row.allocations))
    response = {"facts_key": facts_key, "report": report, "rule_version": reallocation.RULE_VERSION,
                "mode": "prepare", "candidates": [], "comparison": None,
                "ai_interpretation_enabled": reallocation_ai.INTERPRETATION_ENABLED}
    try:
        if receiver_ref is not None:
            response["candidates"] = [asdict(r) for r in
                reallocation.candidates(material, target, assumed_at, receiver_ref, permission)]
        if transfers is not None:
            changes = []
            fields = {"source_ref", "donor_ref", "receiver_ref", "quantity"}
            for item in transfers:
                if type(item) is not dict or set(item) != fields:
                    raise ValueError("transfer fields are missing or unexpected")
                if any(not isinstance(item[field], str) or not 0 < len(item[field]) <= 200
                       for field in ("source_ref", "donor_ref", "receiver_ref")):
                    raise ValueError("transfer references must identify available source and demand records")
                # Decimal strings preserve the product's precision across JSON.
                if not isinstance(item["quantity"], str) or not 0 < len(item["quantity"]) <= 40:
                    raise ValueError("transfer quantity must be an exact decimal string")
                changes.append(reallocation.Transfer(item["source_ref"], item["donor_ref"],
                    item["receiver_ref"], Decimal(item["quantity"])))
            result = reallocation.simulate(material, target, assumed_at,
                reallocation.Plan(key, tuple(changes)), permission)
            response["mode"] = "comparison"
            response["comparison"] = comparison(result)
        if recommend:
            if len(report['rows']) > reallocation_search.MAX_DEMANDS:
                raise ValueError('automatic comparison supports at most eight material demands')
            priorities={}
            adoption_context={}
            for row in report['rows']:
                production=env['mrp.production'].browse(row['mo_id'])
                production.check_access('read')
                priority=production.priority
                if priority not in ('0','1'):
                    raise ValueError('automatic comparison requires a supported recorded priority')
                priorities[row['ref']]=int(priority)
                other = env['stock.move'].search([
                    ('raw_material_production_id', '=', production.id),
                    ('product_id', '!=', env['purchase.order.line'].browse(line_id).product_id.id),
                    ('state', 'not in', ['done', 'cancel']),
                    ('product_uom_qty', '>', 0)], limit=snapshot.MAX_RECORDS + 1)
                other.check_access('read')
                # Reservation is evidence of current allocation, not proof of
                # other-material future coverage or production feasibility.
                adoption_context[row['ref']] = {'other_materials':
                    'unknown' if len(other) > snapshot.MAX_RECORDS else
                    'none' if not other else
                    'reserved' if all(m.state == 'assigned' and not m.picked for m in other) else 'unconfirmed'}
                # Use the same readiness formatter as native MO Overview. Keep
                # costs and all other report fields out of this response.
                raw_moves = production.move_raw_ids
                raw_moves.check_access('read')
                if len(raw_moves) <= snapshot.MAX_RECORDS:
                    overview = env['report.mrp.report_mo_overview']
                    native = production.with_context(warehouse_id=production.warehouse_id.id)
                    components = overview._get_components_data(native, level=1, current_index='')
                    adoption_context[row['ref']].update(
                        native_readiness=overview._format_state(native, components),
                        production_unit=production.product_uom_id.display_name)
            found=reallocation_search.search(material,target,assumed_at,permission,priorities)
            response['mode']='recommendation'
            response['recommendation_facts_key']=hashlib.sha256(json.dumps(
                [facts_key,priorities,adoption_context,reallocation_search.RULE_VERSION,decision_support.RULE],sort_keys=True).encode()).hexdigest()
            response['automatic']={'rule':reallocation_search.RULE_VERSION,
                'evaluated':found.evaluated,'unique_outcomes':found.unique_outcomes,
                'all_orderings_examined':found.all_orderings_examined,
                'global_optimum_proven':False,'priority_refs':found.priority_refs,
                'priority_basis':found.priority_basis,
                'alternatives':[{'id':a.ref,'strategies':a.strategies,
                    'decision_support':decision_support.build(a.result,priorities,adoption_context),
                    'metrics':reallocation_search.metrics(a.result),'comparison':comparison(a.result)}
                    for a in found.alternatives]}
            from ..review_contract import digest, option_key, targets
            # Cross-user identity excludes access scope and translated display labels.
            readiness = {r['ref']: {'other_materials': adoption_context[r['ref']]['other_materials'],
                'state': env['mrp.production'].browse(r['mo_id']).state,
                'moves': [(m.id, m.state, m.quantity, m.product_uom_qty, m.picked) for m in
                          env['mrp.production'].browse(r['mo_id']).move_raw_ids.sorted('id')]}
                for r in report['rows']}
            response['review_revision'] = digest([facts, assumed_at.isoformat(), line_id, priorities, readiness,
                                                 reallocation_search.RULE_VERSION, decision_support.RULE])
            for option in response['automatic']['alternatives']:
                option['review_key'] = option_key(option)
                option['review_targets'] = targets(option)
    except (ValueError, InvalidOperation) as exc:
        raise UserError(env._("The virtual transfer plan cannot be calculated: %s", str(exc))) from None
    return _json_values(response)


def comparison(result):
    return {'plan':asdict(result.plan),'rows':[asdict(r) for r in result.demands],
        'impacts':[asdict(r) for r in result.impacts],
        'source_balances':[asdict(r) for r in result.sources],
        'unallocated':result.unallocated,'unfilled':result.unfilled,
        'material_wait_before_seconds':result.total_material_wait_before_seconds,
        'material_wait_after_seconds':result.total_material_wait_seconds,
        'material_wait_delta_seconds':result.material_wait_delta_seconds}


def _json_values(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_values(item) for item in value]
    return value
