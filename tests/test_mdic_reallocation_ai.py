from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from mdic_reallocation_fixtures import fixtures, ai

class ReallocationAITests(unittest.TestCase):
    def setUp(self):
        self.value=fixtures()['tradeoff']['comparisons']['3']
        self.contract=ai.contract(self.value,'Asia/Shanghai')
        self.report={'summary':'Synthetic example only','tradeoffs':['Target improves; donor waits.'],
            'checks':[],'checked_facts':self.contract['checked_facts']}
    def response(self, report=None):
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(report or self.report)}}],
                'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}}
    def test_one_bounded_request_no_keys_in_payload_and_checked_facts(self):
        with patch.object(ai.ai_engine,'post',return_value=self.response()) as post:
            result=ai.run(self.value,'deepseek','model-test','zh_CN','fake-not-real','Asia/Shanghai')
        self.assertEqual(post.call_count,1)
        payload=post.call_args.args[1]
        self.assertEqual(payload['max_tokens'],1200)
        self.assertEqual(payload['thinking'],{'type':'disabled'})
        self.assertNotIn('fake-not-real',json.dumps(payload))
        self.assertLessEqual(result['limits']['input_bytes'],12000)
        self.assertEqual(result['usage']['total_tokens'],150)
        self.assertTrue(result['prose_requires_review'])
    def test_numbers_dates_omissions_and_extra_fields_are_rejected_without_retry(self):
        variants=[]
        for field,value in [('shortage_after','999'),('full_at_after',None),('unfilled_after','17')]:
            wrong=deepcopy(self.report);wrong['checked_facts'][0][field]=value;variants.append(wrong)
        wrong=deepcopy(self.report);wrong['checked_facts'].pop();variants.append(wrong)
        wrong=deepcopy(self.report);wrong['extra']='bad';variants.append(wrong)
        for value in variants:
            with self.subTest(value=value),patch.object(ai.ai_engine,'post',return_value=self.response(value)) as post:
                with self.assertRaises(ai.ai_engine.AnalysisError):
                    ai.run(self.value,'deepseek','test','en_US','fake')
                self.assertEqual(post.call_count,1)
    def test_truncated_malformed_provider_and_network_errors_have_no_retry(self):
        for response in [{'choices':[]},{'choices':[1]}, {'choices':[{'finish_reason':'length'}]},
                         {'choices':[{'finish_reason':'stop','message':{'content':'not json'}}]}]:
            with self.subTest(response=response),patch.object(ai.ai_engine,'post',return_value=response) as post:
                with self.assertRaises(ai.ai_engine.AnalysisError):
                    ai.run(self.value,'deepseek','test','en_US','fake')
                self.assertEqual(post.call_count,1)
        with patch.object(ai.ai_engine,'post',side_effect=ai.ai_engine.AnalysisError('network')) as post:
            with self.assertRaises(ai.ai_engine.AnalysisError): ai.run(self.value,'deepseek','test','en_US','fake')
            self.assertEqual(post.call_count,1)
    def test_input_size_and_scope_rejected_before_provider(self):
        values=[deepcopy(self.value) for _ in range(3)]
        values[0]['report']['product']='x'*15000
        values[1]['comparison']['rows']*=4
        values[2]['comparison']['plan']['transfers']=[]
        for value in values:
            with patch.object(ai.ai_engine,'post') as post,self.assertRaises(ai.ai_engine.AnalysisError):
                ai.run(value,'deepseek','test','en_US','fake')
            post.assert_not_called()
    def test_unknown_coverage_and_final_gap_preserved(self):
        contract=ai.contract(fixtures()['unknown']['comparisons']['3'],'Asia/Shanghai')
        donor=next(r for r in contract['orders'] if r['order']=='TEST/MO/later-24')
        self.assertIsNone(donor['full_at_after'])
        self.assertEqual(donor['unfilled_after'],'3')
        self.assertIsNone(contract['total_material_wait_after_hours'])
    def test_openai_adapter_same_contract_with_bounded_output(self):
        response={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(self.report)}]}]}
        with patch.object(ai.ai_engine,'post',return_value=response) as post:
            result=ai.run(self.value,'openai','test','fr_FR','fake')
        self.assertEqual(result['status'],'verified')
        self.assertEqual(post.call_args.args[1]['max_output_tokens'],1200)
        self.assertFalse(post.call_args.args[1]['store'])
    def test_invalid_output_budget_rejected_before_provider(self):
        for limit in (0,127,1201,True,'900'):
            with patch.object(ai.ai_engine,'post') as post,self.assertRaises(ai.ai_engine.AnalysisError):
                ai.run(self.value,'deepseek','test','zh_CN','fake',output_token_limit=limit)
            post.assert_not_called()

if __name__=='__main__': unittest.main()
