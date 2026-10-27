"""Synthetic engine-derived fixtures; no ORM, credentials or customer data."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import importlib
import json
from pathlib import Path
import sys
import types

ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('mdic_f6_fixture')
package.__path__=[str(ROOT/'material_delay_impact')]
sys.modules[package.__name__]=package
core=importlib.import_module(package.__name__+'.core')
calc=importlib.import_module(package.__name__+'.reallocation')
ai=importlib.import_module(package.__name__+'.reallocation_ai')
TZ=timezone(timedelta(hours=8))
def at(day): return datetime(2026,11,day,9,tzinfo=TZ)
def jsonable(value): return json.loads(json.dumps(value,default=lambda item:item.isoformat() if isinstance(item,datetime) else str(item)))

def make(name, later_quantity='3', incoming='3', bystander=False):
    unit='kg'
    snapshot=core.MaterialSnapshot('fixture-'+name,datetime(2026,10,14,9,tzinfo=TZ),'test-company',
        'test-warehouse','test-material',unit,D('.01'),'stock:test',D(3),
        (core.Supply('receipt:test','line:test',D(incoming),at(2),unit),),
        (core.Demand('early',D(3),D(0),at(3),unit),core.Demand('later',D(later_quantity),D(3),at(4),unit)))
    if bystander:
        snapshot=replace(snapshot,on_hand=D(2),supplies=(replace(snapshot.supplies[0],quantity=D(2)),
            core.Supply('receipt:other','line:other',D(2),at(7),unit)),demands=(
            replace(snapshot.demands[0],quantity=D(2)),
            replace(snapshot.demands[1],quantity=D(2),reserved=D(2),need_at=at(5)),
            core.Demand('bystander',D(2),D(0),at(4),unit)))
    key=calc.scenario_key(snapshot,'line:test',at(6))
    original=core.analyze(snapshot,'line:test',at(6))
    permission=calc.Permission(key,frozenset((a.source_ref,r.ref) for r in original.delayed.demands for a in r.allocations))
    names={'early':'TEST/MO/early-71','later':'TEST/MO/later-24','bystander':'TEST/MO/third-53'}
    report={'snapshot_id':key[:16],'assumed_at':at(6).isoformat(),'taken_at':snapshot.taken_at.isoformat(),
        'product':'Synthetic test resin','unit':'kg','order':'TEST/PO/41','line_id':991,'on_hand':float(snapshot.on_hand),
        'reserved':float(sum(r.reserved for r in snapshot.demands)),'rows':[], 'evidence':[]}
    for index,(before,row) in enumerate(zip(original.baseline.demands,original.delayed.demands,strict=True)):
        report['rows'].append({'ref':row.ref,'mo':names[row.ref],'mo_id':990+index,
            'need_at':row.need_at.isoformat(),'quantity':float(row.quantity),'reserved':float(row.reserved),
            'baseline_shortage':float(before.shortage_at_due),'delayed_shortage':float(row.shortage_at_due),
            'unfilled':float(row.quantity-sum((a.quantity for a in row.allocations),D(0))),
            'full_at':row.full_at.isoformat() if row.full_at else None,
            'allocations':[{'ref':a.source_ref,'at':a.available_at.isoformat(),'quantity':float(a.quantity)} for a in row.allocations]})
    for index,source in enumerate(snapshot.supplies):
        report['evidence'].append({'ref':source.ref,'kind':'receipt','purchase':'TEST/PO/'+str(41+index),
            'label':'TEST/IN/'+str(83+index),'model':'stock.picking','id':990+index,'state':'assigned','receipt_status':'pending'})
    # Enabled only in synthetic UI mocks to exercise dormant interpretation UI.
    prepared={'facts_key':key,'report':report,'mode':'prepare','comparison':None,'candidates':[],
              'rule_version':calc.RULE_VERSION,'ai_interpretation_enabled':True}
    found={**prepared,'candidates':jsonable([asdict(c) for c in calc.candidates(snapshot,'line:test',at(6),'early',permission)])}
    comparisons={}
    amounts=['1.50','3'] if not bystander else ['2']
    for amount in amounts:
        result=calc.simulate(snapshot,'line:test',at(6),calc.Plan(key,(
            calc.Transfer('stock:test:reserved:later','later','early',D(amount)),)),permission)
        comparison={'plan':asdict(result.plan),'rows':[asdict(r) for r in result.demands],
            'impacts':[asdict(r) for r in result.impacts],'source_balances':[asdict(r) for r in result.sources],
            'unallocated':result.unallocated,'unfilled':result.unfilled,
            'material_wait_before_seconds':result.total_material_wait_before_seconds,
            'material_wait_after_seconds':result.total_material_wait_seconds,
            'material_wait_delta_seconds':result.material_wait_delta_seconds}
        comparisons[amount]=jsonable({**prepared,'mode':'comparison','comparison':comparison})
    return {'prepared':prepared,'found':found,'comparisons':comparisons,'demo_only':True}

def fixtures():
    return {'tradeoff':make('tradeoff'),'unknown':make('unknown',later_quantity='5',incoming='2'),
            'bystander':make('bystander',bystander=True)}
