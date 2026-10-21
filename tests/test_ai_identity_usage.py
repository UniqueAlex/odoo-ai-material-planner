"""Focused regressions for entity identity and actual provider usage; no network."""
import copy
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

pkg = types.ModuleType('mdic_usage_test')
pkg.__path__ = [str(Path(__file__).resolve().parents[1] / 'material_delay_impact')]
sys.modules[pkg.__name__] = pkg
engine = importlib.import_module(pkg.__name__ + '.ai_engine')
tasks = importlib.import_module(pkg.__name__ + '.tasks')


def fixture():
    row = dict(demand_ref='stock.move:4', mo_ref='WH/MO/00001', need_at='2026-11-06T09:00:00+00:00',
               baseline_shortage=0, hypothetical_shortage=2, new_shortage=2,
               material_full_at='2026-11-08T01:00:00+00:00', evidence_ref='calc:test:stock.move:4', unfilled=0)
    task = dict(snapshot_id='test', order_ref='P00001', grade='medium',
                context={'material': '[RESIN-002] Test resin', 'assumed_at': '2026-11-08T01:00:00+00:00'},
                tools={name: [] for name in engine.TOOLS})
    task['tools'].update(read_purchase_line={'order_ref': 'P00001'}, read_data_quality={'source_balances': []},
                         read_calculation_evidence=[row])
    report = dict(headline='Test resin on purchase order P00001 arrives late.', risk_label='medium',
                  impacts=[{**{k: row[k] for k in engine.IMPACT_FIELDS[:-1]},
                            'evidence_refs': ['stock.move:4', 'WH/MO/00001', 'P00001', 'calc:test:stock.move:4']}],
                  explanation='Confirm the receipt timing.', next_checks=[], limitations=['One material in one warehouse.'])
    return task, report


def response(report=None, usage=None, provider='deepseek'):
    if provider == 'deepseek':
        msg = {'content': json.dumps(report)} if report else {'tool_calls': [
            {'id': str(i), 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}
            for i, name in enumerate(engine.TOOLS)]}
        value = {'choices': [{'finish_reason': 'stop' if report else 'tool_calls', 'message': msg}]}
    else:
        output = [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(report)}]}] if report else [
            {'type': 'function_call', 'call_id': str(i), 'name': name, 'arguments': '{}'}
            for i, name in enumerate(engine.TOOLS)]
        value = {'status': 'completed', 'output': output}
    if usage is not None:
        value['usage'] = usage
    return value


class IdentityUsageTests(unittest.TestCase):
    def test_identity_in_initial_final_and_review_context(self):
        task, report = fixture()
        self.assertIn(engine.IDENTITY_POLICY, engine.messages(task, 'en_US')[0]['content'])
        for text in [engine.final_instruction(task), engine.review_instruction(task, json.dumps(report), None, 'en_US')]:
            self.assertIn('[RESIN-002] Test resin', text)
            self.assertIn('purchase_reference_is_not_a_material_identifier', text)

    def test_confused_identity_rejected_across_all_prose_fields(self):
        task, report = fixture()
        for field in ['headline', 'explanation', 'next_checks', 'limitations']:
            for text in ['This covers one material, P00001, in one warehouse.', 'Material P00001 is late.', '物料编号：P00001']:
                bad = copy.deepcopy(report)
                bad[field] = [text] if isinstance(bad[field], list) else text
                with self.subTest(field=field, text=text), self.assertRaises(engine.AnalysisError):
                    engine.validate_business_prose(bad, task)

    def test_document_context_and_real_product_code_are_allowed(self):
        task, report = fixture()
        report['explanation'] = 'Material from purchase order P00001. P00001 contains Test resin.'
        engine.validate_business_prose(report, task)
        task['context']['material'] = '[P00001] Resin'
        report['explanation'] = 'Material P00001 is late.'
        engine.validate_business_prose(report, task)

    def test_both_providers_account_for_tools_final_and_review(self):
        task, report = fixture()
        for provider in ['deepseek', 'openai']:
            usage = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120} if provider == 'deepseek' else {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120}
            with self.subTest(provider=provider), patch.object(engine, 'post', side_effect=[response(x, usage, provider) for x in [None, report, report]]) as post:
                result = engine.run(task, provider, 'test', 'en_US', 'fake-key')
            self.assertEqual(post.call_count, 3)
            self.assertEqual(result['usage'], {'prompt_tokens': 300, 'completion_tokens': 60, 'total_tokens': 360})
            self.assertTrue(result['usage_details']['complete'])
            self.assertEqual(result['report'], report)

    def test_bad_identity_repaired_without_unmetered_retry(self):
        task, report = fixture();bad = copy.deepcopy(report)
        bad['limitations'] = ['One material P00001.']
        usage = {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}
        with patch.object(engine, 'post', side_effect=[response(x, usage) for x in [None, bad, report]]) as post:
            result = engine.run(task, 'deepseek', 'test', 'en_US', 'fake-key')
        self.assertEqual(result['usage']['total_tokens'], 36)
        self.assertEqual(result['report'], report)
        self.assertIn('purchase_reference_used_as_material', post.call_args.args[1]['messages'][-1]['content'])

    def test_missing_or_invalid_usage_never_becomes_zero_total(self):
        task, report = fixture()
        for usage in [None, {}, {'prompt_tokens': True, 'completion_tokens': -1, 'total_tokens': '5'}]:
            with patch.object(engine, 'post', side_effect=[response(None, {'total_tokens': 8}), response(report, usage), response(report, {'total_tokens': 9})]):
                result = engine.run(task, 'deepseek', 'test', 'en_US', 'fake-key')
            self.assertIsNone(result['usage']['total_tokens'])
            self.assertFalse(result['usage_details']['complete'])
            self.assertEqual(result['usage_details']['known_total_tokens'], 17)

    def test_network_failure_preserves_known_usage_and_marks_incomplete(self):
        task, _ = fixture()
        with patch.object(engine, 'post', side_effect=[response(None, {'total_tokens': 8}), engine.AnalysisError('network')]):
            with self.assertRaises(engine.AnalysisError) as caught:
                engine.run(task, 'deepseek', 'test', 'en_US', 'fake-key')
        data = caught.exception.accounting
        self.assertEqual(data['usage_details']['known_total_tokens'], 8)
        self.assertEqual(data['usage_details']['attempted_requests'], 2)
        self.assertIsNone(data['usage']['total_tokens'])

    def test_failure_accounting_persisted_and_cached_without_another_operation(self):
        class MemoryStore(tasks.Store):
            def __init__(self): self.saved = None
            def _claim(self, *args, **kwargs): return ({}, self.saved, None if self.saved else 'claim')
            def _finish(self, key, claim, result): self.saved = result;return result
        error = engine.AnalysisError('validation')
        error.accounting = {'usage': {'total_tokens': 77}, 'usage_details': {'complete': True}}
        store = MemoryStore()
        with patch('builtins.print'), patch.object(engine, 'post') as post:
            def operation(_): raise error
            first = store.run('scope', operation, identity='request')
            second = store.run('scope', lambda _: self.fail('must not call twice'), identity='request')
        self.assertEqual(first['usage']['total_tokens'], 77)
        self.assertEqual(second['usage'], first['usage'])
        self.assertTrue(second['cache_hit'])
        post.assert_not_called()


if __name__ == '__main__': unittest.main()
