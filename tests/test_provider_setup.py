"""No-network regressions for native providers and first-use validation state."""
import copy
import importlib
import json
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
from test_ai_identity_usage import engine, fixture

transport = engine.provider_transport
secure = importlib.import_module(engine.__package__ + '.secure_config')
KEY = 'synthetic-test-key-not-a-secret'


def native(provider, report=None):
    if provider == 'gemini':
        parts = [{'text': json.dumps(report)}] if report else [
            {'functionCall': {'name': n, 'args': {}}, 'thoughtSignature': 'opaque-signed-block'} for n in engine.TOOLS]
        return {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model', 'parts': parts}}],
                'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 20, 'thoughtsTokenCount': 5, 'totalTokenCount': 125}}
    parts = [{'type': 'text', 'text': json.dumps(report)}] if report else [
        {'type': 'tool_use', 'id': 'call_'+str(i), 'name': n, 'input': {}} for i,n in enumerate(engine.TOOLS)]
    return {'stop_reason': 'end_turn' if report else 'tool_use', 'content': parts,
            'usage': {'input_tokens': 90, 'cache_read_input_tokens': 10, 'output_tokens': 25}}


class ProviderTests(unittest.TestCase):
    def test_native_tool_roundtrip_and_all_usage(self):
        task, report = fixture()
        for provider in ('gemini', 'claude'):
            responses = [Mock(status_code=200, json=Mock(return_value=native(provider, v))) for v in (None, report, report)]
            with self.subTest(provider=provider), patch.object(engine.requests, 'post', side_effect=responses) as post:
                result = engine.run(task,provider,engine.PROVIDERS[provider]['model'],'en_US',KEY)
            self.assertEqual(result['report'], report)
            self.assertEqual(result['usage']['total_tokens'],375)
            self.assertTrue(result['usage_details']['complete'])
            self.assertEqual(len(result['tool_log']),7)
            first = post.call_args_list[0].kwargs
            second = post.call_args_list[1].kwargs
            self.assertFalse(first['allow_redirects'])
            self.assertNotIn(KEY, post.call_args_list[0].args[0])
            self.assertNotIn(KEY,json.dumps(first['json']))
            if provider == 'gemini':
                self.assertIn('opaque-signed-block',json.dumps(second['json']['contents']))
                self.assertEqual(len(second['json']['contents'][2]['parts']),8)  # 7 results + final instruction
                self.assertIn('responseJsonSchema',second['json']['generationConfig'])
            else:
                self.assertEqual(len(second['json']['messages'][2]['content']),8)  # 7 results + final instruction
                self.assertIn('output_config',second['json'])

    def test_truncated_and_refused_outputs_not_accepted(self):
        for provider in ('gemini','claude'):
            value=native(provider,{'irrelevant':True})
            if provider=='gemini':value['candidates'][0]['finishReason']='MAX_TOKENS'
            else:value['stop_reason']='refusal'
            result=transport.response(provider,value)
            self.assertEqual(result['status'],'incomplete')
            self.assertEqual(result['usage']['total_tokens'],125)

    def test_credential_error_messages_are_not_exposed(self):
        response=Mock(status_code=400,json=Mock(return_value={'error':{'message':'API key not valid '+KEY}}))
        with patch.object(engine.requests,'post',return_value=response), self.assertRaises(engine.AnalysisError) as caught:
            engine.post('gemini',{'model':'gemini-3.1-flash-lite','input':'hi'},KEY,time.monotonic()+10)
        self.assertEqual(str(caught.exception),'key')
        self.assertNotIn(KEY,str(caught.exception))

    def test_invalid_model_never_reaches_network(self):
        with patch.object(engine.requests,'post') as post, self.assertRaises(engine.AnalysisError):
            engine.post('gemini',{'model':'../../evil?key=x','input':'hi'},KEY,time.monotonic()+10)
        post.assert_not_called()

    def test_missing_usage_is_not_fabricated(self):
        self.assertEqual(transport.gemini_usage({}),{})
        result=transport.response('claude',{'content':[],'stop_reason':'end_turn'})
        self.assertNotIn('total_tokens',result['usage'])

    def test_connection_is_metered(self):
        value=native('claude',{'ok':True})
        with patch.object(engine.requests,'post',return_value=Mock(status_code=200,json=Mock(return_value=value))):
            result=engine.test_connection('claude','claude-haiku-5-5',KEY)
        self.assertEqual(result['usage']['total_tokens'],125)
        self.assertEqual(result['usage_details']['attempted_requests'],1)

    def test_capability_requires_actual_tool_value_and_never_retries(self):
        for provider in engine.PROVIDERS:
            def fake(provider,payload,key,deadline):
                first = bool(payload.get('tools'))
                if provider=='deepseek':
                    content = {'tool_calls':[{'type':'function','id':'probe','function':{'name':'read_test_value','arguments':'{}'}}]} if first else {'content':'{"value":"wrong-value"}'}
                    return {'choices':[{'finish_reason':'tool_calls' if first else 'stop','message':content}], 'usage':{'total_tokens':10}}
                return {'status':'completed','output':[{'type':'function_call','call_id':'probe','name':'read_test_value','arguments':'{}'}] if first else
                    [{'type':'message','content':[{'type':'output_text','text':'{"value":"wrong-value"}'}]}], 'usage':{'total_tokens':10}}
            with self.subTest(provider=provider),patch.object(engine,'post',side_effect=fake) as post, self.assertRaises(engine.AnalysisError) as caught:
                engine.test_capability(provider,'test',KEY)
            self.assertEqual(caught.exception.code,'capability')
            self.assertEqual(post.call_count,2)
            self.assertEqual(caught.exception.accounting['usage']['total_tokens'],20)


class ValidationStateTests(unittest.TestCase):
    def test_state_is_scoped_and_never_applied_after_save_or_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            store=secure.Store(directory,'setup-test',1)
            store.save('openai','gpt-4.1-mini',KEY)
            first=store.read()
            self.assertEqual(first['validation'],{})
            self.assertTrue(store.mark_validation(secure.revision(first),'connected'))
            self.assertTrue(store.mark_validation(secure.revision(first),'capable'))
            self.assertEqual(set(store.read()['validation']),{'connected','capable'})
            # Even saving the same values starts a new validation revision.
            store.save('openai','gpt-4.1-mini',KEY)
            self.assertFalse(store.mark_validation(secure.revision(first),'capable'))
            self.assertEqual(store.read()['validation'],{})
            current=store.read();store.remove()
            self.assertFalse(store.mark_validation(secure.revision(current),'capable'))
            self.assertIsNone(store.read())
            self.assertIsNone(secure.Store(directory,'setup-test',2).read())


if __name__=='__main__':unittest.main()
