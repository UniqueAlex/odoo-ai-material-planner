import importlib,json,unittest
from copy import deepcopy
from unittest.mock import patch
import mdic_recommendation_fixtures as fixtures

ai=importlib.import_module(fixtures.calc.__package__+'.recommendation_ai')

class RecommendationAITests(unittest.TestCase):
    def setUp(self):
        self.value=fixtures.make()
        self.report={'modules':[{'candidate_id':a['id'],'fact_ids':['allocation','metrics'],'checks':[]}
            for a in self.value['automatic']['alternatives']]}
    def response(self,value=None):
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value or self.report)}}],
            'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}}
    def test_one_bounded_request_preserves_every_alternative_and_no_secret_in_payload(self):
        with patch.object(ai.ai_engine,'post',return_value=self.response()) as post:
            result=ai.run(self.value,'deepseek','test','zh_CN','fake-private-key','Asia/Shanghai')
        self.assertEqual(post.call_count,1)
        payload=post.call_args.args[1]
        self.assertEqual(payload['max_tokens'],900)
        self.assertNotIn('fake-private-key',json.dumps(payload))
        self.assertEqual(len(result['modules']),2)
        self.assertLessEqual(result['limits']['input_bytes'],10000)
    def test_wrong_missing_reordered_and_duplicate_plan_refs_fail(self):
        variants=[{'modules':[]},deepcopy(self.report),deepcopy(self.report),deepcopy(self.report)]
        variants[1]['modules'][0]['candidate_id']='invented-plan'
        variants[2]['modules'].reverse()
        variants[3]['modules'][1]=variants[3]['modules'][0]
        for report in variants:
            with patch.object(ai.ai_engine,'post',return_value=self.response(report)),self.assertRaises(ai.ai_engine.AnalysisError):
                ai.run(self.value,'deepseek','test','zh_CN','fake')
    def test_contextually_wrong_checks_fail(self):
        for check in ({'kind':'confirm_arrival','refs':['early']},
                      {'kind':'confirm_reservation','refs':['early']},
                      {'kind':'review_priority','refs':['early']},
                      {'kind':'find_additional_supply','refs':['later']},
                      {'kind':'confirm_arrival','refs':['invented']}):
            report=deepcopy(self.report);report['modules'][0]['checks']=[check]
            with patch.object(ai.ai_engine,'post',return_value=self.response(report)),self.assertRaises(ai.ai_engine.AnalysisError):
                ai.run(self.value,'deepseek','test','zh_CN','fake')
    def test_optional_checks_with_no_targets_are_omitted_without_inventing_targets(self):
        report=deepcopy(self.report);report['modules'][0]['checks']=[{'kind':'review_priority','refs':[]}]
        with patch.object(ai.ai_engine,'post',return_value=self.response(report)):
            result=ai.run(self.value,'deepseek','test','en_US','fake')
        self.assertEqual(result['modules'][0]['checks'],[])
    def test_unknown_residual_has_no_false_overall_wait_strategy(self):
        value=fixtures.make(True)
        contract,_=ai.contract(value,'Asia/Shanghai')
        self.assertTrue(all(p['metrics']['total_material_wait_hours'] is None for p in contract['alternatives']))
        self.assertTrue(all('overall_wait' not in p['strategy'] for p in contract['alternatives']))
    def test_model_hours_and_material_shortage_terms_preserve_source(self):
        original=deepcopy(self.value)
        contract,_=ai.contract(self.value,'Asia/Shanghai')
        from decimal import Decimal
        for given,source in zip(contract['alternatives'],original['automatic']['alternatives']):
            metrics=given['metrics'];comparison=source['comparison']
            self.assertNotIn('total_material_wait_seconds',metrics)
            self.assertNotIn('late_orders',metrics)
            self.assertEqual(Decimal(metrics['total_material_wait_hours'])*3600,
                Decimal(comparison['material_wait_after_seconds']))
            self.assertEqual(Decimal(metrics['material_wait_before_hours'])*3600,
                Decimal(comparison['material_wait_before_seconds']))
            self.assertEqual(metrics['orders_short_at_material_need_after'],source['metrics']['late_orders'])
        self.assertEqual(self.value,original)
    def test_truncated_and_transport_failure_never_retry(self):
        for response in ({'choices':[]},{'choices':[{'finish_reason':'length'}]},
                         {'choices':[{'finish_reason':'stop','message':{'content':'no json'}}]}):
            with patch.object(ai.ai_engine,'post',return_value=response) as post,self.assertRaises(ai.ai_engine.AnalysisError):
                ai.run(self.value,'deepseek','test','en_US','fake')
            self.assertEqual(post.call_count,1)
        with patch.object(ai.ai_engine,'post',side_effect=ai.ai_engine.AnalysisError('network')) as post,self.assertRaises(ai.ai_engine.AnalysisError):
            ai.run(self.value,'deepseek','test','en_US','fake')
        self.assertEqual(post.call_count,1)
    def test_order_existence_and_recorded_priority_are_independent(self):
        data,_=ai.contract(self.value,'Asia/Shanghai')
        self.assertTrue(data['record_boundaries']['all_listed_orders_are_existing_records'])
        self.assertFalse(data['record_boundaries']['customer_delivery_dates_provided'])
        for plan in data['alternatives']:
            orders={r['ref']:r for r in plan['orders']}
            self.assertTrue(orders['later']['recorded_high_priority'])
            self.assertFalse(orders['early']['recorded_high_priority'])
            self.assertEqual(orders['later']['order'],'TEST/MO/later-24')
        value=deepcopy(self.value)
        value['automatic']['priority_refs']=[]
        value['automatic']['priority_basis']='no_distinct_high_priority'
        ordinary,_=ai.contract(value,'Asia/Shanghai')
        self.assertTrue(ordinary['record_boundaries']['all_listed_orders_are_existing_records'])
        self.assertTrue(all(not r['recorded_high_priority'] for p in ordinary['alternatives'] for r in p['orders']))
    def test_oversized_input_stops_before_request(self):
        value=deepcopy(self.value);value['report']['product']='长'*10000
        with patch.object(ai.ai_engine,'post') as post,self.assertRaises(ai.ai_engine.AnalysisError):
            ai.run(value,'deepseek','test','zh_CN','fake')
        post.assert_not_called()
    def test_openai_uses_same_modules_and_single_request(self):
        response={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(self.report)}]}]}
        with patch.object(ai.ai_engine,'post',return_value=response) as post:
            result=ai.run(self.value,'openai','test','fr_FR','fake')
        self.assertEqual(len(result['modules']),2)
        self.assertFalse(post.call_args.args[1]['store'])

    def test_arbitrary_prose_cannot_enter_new_output_contract(self):
        # Reproduces the accepted old French failure as an adversarial response.
        report=deepcopy(self.report)
        report['modules'][0]['rationale']='Conserver le stock réservé actuel; aucune réaffectation.'
        with patch.object(ai.ai_engine,'post',return_value=self.response(report)),self.assertRaises(ai.ai_engine.AnalysisError):
            ai.run(self.value,'deepseek','test','fr_FR','fake')

    def test_unknown_duplicate_empty_and_cross_plan_fact_ids_rejected(self):
        for ids in ([],['metrics','metrics'],['invented-source'],['order99']):
            report=deepcopy(self.report);report['modules'][0]['fact_ids']=ids
            with patch.object(ai.ai_engine,'post',return_value=self.response(report)),self.assertRaises(ai.ai_engine.AnalysisError):
                ai.run(self.value,'deepseek','test','en_US','fake')


class NoAdjustmentTests(unittest.TestCase):
    def covered(self):
        row={'ref':'d','need_at':'2036-11-03T17:00:00+08:00','full_at':'2036-11-03T17:00:00+08:00',
             'delayed_shortage':0,'unfilled':0}
        return {'report':{'rows':[row],'unfilled':0},'automatic':{'alternatives':[{'comparison':{
            'plan':{'transfers':[]},'unfilled':'0','rows':[{**row,'shortage_at_due':'0'}]}}]}}
    def test_complete_coverage_skips_provider_without_changing_input(self):
        value=self.covered();original=deepcopy(value)
        with patch.object(ai.ai_engine,'post',side_effect=AssertionError('Unnecessary paid call')) as post:
            for lang in ('zh_CN','en_US','fr_FR'):
                result=ai.run(value,'deepseek','test',lang,'fake')
                self.assertEqual(result['status'],'not_needed');self.assertEqual(result['limits']['requests'],0)
        post.assert_not_called();self.assertEqual(value,original)
    def test_missing_unknown_existing_shortages_and_conflicting_comparisons_never_skip(self):
        for field,bad in [('unfilled',None),('unfilled',True),('unfilled','NaN'),('unfilled','0.0000001'),
                          ('delayed_shortage',3),('delayed_shortage',False),('full_at',None),
                          ('full_at','2036-11-03T17:00:01+08:00'),('need_at','2036-11-03T17:00:00')]:
            value=self.covered();value['report']['rows'][0][field]=bad
            self.assertFalse(ai.no_adjustment_needed(value),(field,bad))
        for kind in ('missing','empty','transfers','late','short','residual','unknown_total'):
            value=self.covered();c=value['automatic']['alternatives'][0]['comparison']
            if kind=='missing':del value['report']['rows'][0]['unfilled']
            elif kind=='empty':value['automatic']['alternatives']=[]
            elif kind=='transfers':c['plan']['transfers']=[{'quantity':'1'}]
            elif kind=='late':c['rows'][0]['full_at']='2036-11-04T09:00:00+08:00'
            elif kind=='short':c['rows'][0]['shortage_at_due']='0.000001'
            elif kind=='residual':c['unfilled']='1'
            else:value['report']['unfilled']=None
            self.assertFalse(ai.no_adjustment_needed(value),kind)

if __name__=='__main__':unittest.main()
