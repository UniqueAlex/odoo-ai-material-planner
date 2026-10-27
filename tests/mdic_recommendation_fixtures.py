"""Independent automatic multi-strategy fixtures, with no business reads."""
from dataclasses import asdict,replace
from decimal import Decimal as D
from mdic_reallocation_fixtures import core,calc,jsonable,at,ROOT,TZ
from datetime import datetime
import importlib
import json

search=importlib.import_module(calc.__package__+'.reallocation_search')

def make(unknown=False):
    snapshot=core.MaterialSnapshot('auto-unknown' if unknown else 'auto-tradeoff',
        datetime(2026,10,14,9,tzinfo=TZ),'synthetic-company','synthetic-warehouse','synthetic-material','kg',D('.01'),
        'stock:test',D(3),(core.Supply('receipt:test','line:test',D(2 if unknown else 3),at(2),'kg'),),
        (core.Demand('early',D(3),D(0),at(3),'kg'),core.Demand('later',D(5 if unknown else 3),D(3),at(4),'kg')))
    original=core.analyze(snapshot,'line:test',at(6))
    key=calc.scenario_key(snapshot,'line:test',at(6))
    permission=calc.Permission(key,frozenset((a.source_ref,r.ref) for r in original.delayed.demands for a in r.allocations))
    found=search.search(snapshot,'line:test',at(6),permission,{'later':1})
    report={'snapshot_id':key[:16],'assumed_at':at(6).isoformat(),'taken_at':snapshot.taken_at.isoformat(),
        'product':'Synthetic test resin','unit':'kg','order':'TEST/PO/41','line_id':991,'on_hand':3,'reserved':3,
        'rows':[],'evidence':[{'ref':'receipt:test','kind':'receipt','purchase':'TEST/PO/41','label':'TEST/IN/83',
            'state':'assigned','receipt_status':'pending','model':'stock.picking','id':991}]}
    labels={'early':'TEST/MO/early-71','later':'TEST/MO/later-24'}
    for row in original.delayed.demands:
        report['rows'].append({'ref':row.ref,'mo':labels[row.ref],'mo_id':991 if row.ref=='early' else 992,
            'need_at':row.need_at,'quantity':float(row.quantity),'reserved':float(row.reserved),
            'delayed_shortage':float(row.shortage_at_due),'full_at':row.full_at,
            'allocations':[{'ref':a.source_ref,'at':a.available_at,'quantity':float(a.quantity)} for a in row.allocations]})
    def comparison(r):
        return {'plan':asdict(r.plan),'rows':[asdict(x) for x in r.demands],
            'impacts':[asdict(x) for x in r.impacts],'source_balances':[asdict(x) for x in r.sources],
            'unallocated':r.unallocated,'unfilled':r.unfilled,
            'material_wait_before_seconds':r.total_material_wait_before_seconds,
            'material_wait_after_seconds':r.total_material_wait_seconds,
            'material_wait_delta_seconds':r.material_wait_delta_seconds}
    result={'facts_key':key,'recommendation_facts_key':key,'report':report,'mode':'recommendation',
        'automatic':{'evaluated':found.evaluated,'unique_outcomes':found.unique_outcomes,
            'all_orderings_examined':found.all_orderings_examined,'global_optimum_proven':False,
            'priority_refs':found.priority_refs,'priority_basis':found.priority_basis,
            'alternatives':[{'id':a.ref,'strategies':a.strategies,'metrics':search.metrics(a.result),
                'comparison':comparison(a.result)} for a in found.alternatives]},
        'ai_recommendation':{'status':'verified_structured_options','modules':[
            {'candidate_id':a.ref,'rationale':'MOCK strategy explanation; synthetic fixture only.','checks':[]}
            for a in found.alternatives]}}
    return jsonable(result)

def fixtures():return {'tradeoff':make(),'unknown':make(True)}

