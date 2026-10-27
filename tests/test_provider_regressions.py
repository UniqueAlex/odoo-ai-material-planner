"""Historical business regressions through each native HTTP response envelope.

Only requests.post is replaced: production transport, parsing, validation,
bounded repair and usage accounting all run. No external model is contacted.
"""
import copy
import importlib
import json
import unittest
from unittest.mock import Mock, patch

from test_ai_identity_usage import engine, fixture, response
from test_provider_setup import native, KEY
import mdic_recommendation_fixtures as recommendations
from mdic_reallocation_fixtures import fixtures, ai as manual

automatic = importlib.import_module(recommendations.calc.__package__ + '.recommendation_ai')
PROVIDERS = tuple(engine.PROVIDERS)


def envelope(provider, report=None):
    if provider in ('gemini', 'claude'):
        return native(provider, report)
    usage = ({'prompt_tokens': 100, 'completion_tokens': 25, 'total_tokens': 125}
             if provider == 'deepseek' else {'input_tokens': 100, 'output_tokens': 25, 'total_tokens': 125})
    return response(report, usage, provider)


def http(value):
    return Mock(status_code=200, json=Mock(return_value=value))


class HistoricalProviderRegressions(unittest.TestCase):
    def run_impact(self, provider, drafts, task=None):
        task = copy.deepcopy(task or fixture()[0])
        with patch.object(engine.requests, 'post', side_effect=[http(envelope(provider, x)) for x in [None, *drafts]]) as post:
            result = engine.run(task, provider, 'synthetic-model', 'en_US', KEY)
        return result, post

    def test_identity_repair_each_prose_field_through_native_formats(self):
        task, good = fixture()
        for provider in PROVIDERS:
            for field in ('headline', 'explanation', 'next_checks', 'limitations'):
                bad = copy.deepcopy(good)
                text = 'Material P00001 is late.'
                bad[field] = [text] if isinstance(bad[field], list) else text
                with self.subTest(provider=provider, field=field):
                    result, post = self.run_impact(provider, [bad, good])
                    self.assertEqual(result['report'], good)
                    self.assertEqual(result['usage']['total_tokens'], 375)
                    self.assertEqual(post.call_count, 3)
                    self.assertIn('purchase_reference_used_as_material', json.dumps(post.call_args.kwargs['json']))

    def test_historical_bad_prose_and_facts_fail_with_bounded_repair(self):
        task, good = fixture()
        task['context']['display_timezone'] = 'Asia/Shanghai'
        variants = []
        for text in ('stock.move:4 is short.', 'hypothetical_shortage is two.',
                     'Material P00001 is late.', 'Arrival is 2026-11-08 01:00.',
                     'Arrival is 2026-12-31 09:00.', 'Close the final gap.',
                     'Shortages cannot be added.', 'Full coverage time is unknown.',
                     'The calculated allocation still exists in the system.'):
            bad = copy.deepcopy(good); bad['explanation'] = text; variants.append(bad)
        for field, value in (('hypothetical_shortage', 999), ('material_full_at', None),
                             ('need_at', '2026-12-31T09:00:00+00:00'), ('evidence_refs', ['invented'])):
            bad = copy.deepcopy(good); bad['impacts'][0][field] = value; variants.append(bad)
        for provider in PROVIDERS:
            for bad in variants:
                with self.subTest(provider=provider, bad=bad), patch.object(engine.requests, 'post',
                        side_effect=[http(envelope(provider, x)) for x in [None, bad, bad, bad]]) as post:
                    with self.assertRaises(engine.AnalysisError) as caught:
                        engine.run(copy.deepcopy(task), provider, 'synthetic-model', 'en_US', KEY)
                    self.assertIn(caught.exception.code, ('validation', 'format'))
                    self.assertEqual(post.call_count, 4)
                    self.assertEqual(caught.exception.accounting['usage']['total_tokens'], 500)

    def test_local_dates_and_unknown_coverage_remain_accepted(self):
        task, good = fixture()
        task['context']['display_timezone'] = 'Asia/Shanghai'
        good['explanation'] = 'Test resin on purchase order P00001 is covered at 2026-11-08 09:00.'
        for provider in PROVIDERS:
            with self.subTest(provider=provider, kind='local'):
                result, _ = self.run_impact(provider, [good, good], task)
                self.assertEqual(result['report'], good)
            unknown = copy.deepcopy(task); report = copy.deepcopy(good)
            unknown['tools']['read_calculation_evidence'][0]['material_full_at'] = None
            unknown['tools']['read_calculation_evidence'][0]['unfilled'] = 2
            report['impacts'][0]['material_full_at'] = None
            report['explanation'] = 'Full coverage time is unknown.'
            with self.subTest(provider=provider, kind='unknown'):
                result, _ = self.run_impact(provider, [report, report], unknown)
                self.assertIsNone(result['report']['impacts'][0]['material_full_at'])

    def test_no_more_tool_calls_after_evidence_is_complete(self):
        task, _ = fixture()
        for provider in PROVIDERS:
            with self.subTest(provider=provider), patch.object(engine.requests, 'post',
                    side_effect=[http(envelope(provider)), http(envelope(provider))]) as post:
                with self.assertRaises(engine.AnalysisError) as caught:
                    engine.run(task, provider, 'synthetic-model', 'en_US', KEY)
                self.assertEqual(caught.exception.code, 'format')
                self.assertEqual(post.call_count, 2)
                self.assertEqual(caught.exception.accounting['usage']['total_tokens'], 250)

    def test_missing_usage_is_unknown_for_every_format(self):
        task, good = fixture()
        for provider in PROVIDERS:
            missing = envelope(provider, good)
            missing.pop('usageMetadata' if provider == 'gemini' else 'usage')
            with self.subTest(provider=provider), patch.object(engine.requests, 'post', side_effect=[
                    http(envelope(provider)), http(missing), http(envelope(provider, good))]):
                result = engine.run(task, provider, 'synthetic-model', 'en_US', KEY)
                self.assertIsNone(result['usage']['total_tokens'])
                self.assertEqual(result['usage_details']['known_total_tokens'], 250)

    def test_malformed_native_blocks_preserve_usage_and_report_format_error(self):
        for provider in ('gemini', 'claude'):
            malformed = envelope(provider, {'x': 1})
            if provider == 'gemini': malformed['candidates'][0]['content']['parts'] = [None]
            else: malformed['content'] = [None]
            with self.subTest(provider=provider), patch.object(engine.requests, 'post', return_value=http(malformed)) as post:
                with self.assertRaises(engine.AnalysisError) as caught:
                    engine.run(fixture()[0], provider, 'synthetic-model', 'en_US', KEY)
                self.assertEqual(caught.exception.code, 'format')
                self.assertEqual(caught.exception.accounting['usage']['total_tokens'], 125)
                self.assertEqual(post.call_count, 1)

    def test_automatic_selection_errors_cannot_bypass_validation(self):
        value = recommendations.make()
        good = {'modules': [{'candidate_id': a['id'], 'fact_ids': ['allocation', 'metrics'], 'checks': []}
                            for a in value['automatic']['alternatives']]}
        variants = []
        for field, wrong in (('candidate_id', 'invented'), ('fact_ids', ['invented']),
                             ('fact_ids', ['metrics', 'metrics']), ('rationale', 'Material TEST/PO/41 is late.'),
                             ('checks', [{'kind': 'confirm_arrival', 'refs': ['early']}])):
            bad = copy.deepcopy(good); bad['modules'][0][field] = wrong; variants.append(bad)
        bad = copy.deepcopy(good); bad['modules'].reverse(); variants.append(bad)
        for provider in PROVIDERS:
            for bad in variants:
                with self.subTest(provider=provider, bad=bad), patch.object(automatic.ai_engine.requests, 'post', return_value=http(envelope(provider, bad))) as post:
                    with self.assertRaises(automatic.ai_engine.AnalysisError) as caught:
                        automatic.run(copy.deepcopy(value), provider, 'synthetic-model', 'en_US', KEY)
                    self.assertIn(caught.exception.code, ('format', 'validation'))
                    self.assertEqual(caught.exception.accounting['usage']['total_tokens'], 125)
                    self.assertEqual(post.call_count, 1)

    def test_automatic_rendering_same_facts_and_empty_checks_all_languages(self):
        value = recommendations.make(True); original = copy.deepcopy(value)
        good = {'modules': [{'candidate_id': a['id'], 'fact_ids': ['allocation', 'metrics'],
                            'checks': [{'kind': 'review_priority', 'refs': []}]} for a in value['automatic']['alternatives']]}
        for language in ('en_US', 'zh_CN', 'fr_FR'):
            expected = None
            for provider in PROVIDERS:
                with self.subTest(provider=provider, language=language), patch.object(automatic.ai_engine.requests, 'post', return_value=http(envelope(provider, good))):
                    result = automatic.run(value, provider, 'synthetic-model', language, KEY, 'Asia/Shanghai')
                    if expected is None: expected = result['modules']
                    self.assertEqual(result['modules'], expected)
                    self.assertTrue(all(m['checks'] == [] for m in result['modules']))
                    self.assertEqual(result['usage']['total_tokens'], 125)
        self.assertEqual(value, original)

    def test_manual_facts_cannot_change_or_hide_unknowns(self):
        # Dormant manual AI stays disabled; validate its adapter without enabling it.
        self.assertFalse(manual.INTERPRETATION_ENABLED)
        value = fixtures()['unknown']['comparisons']['3']; original = copy.deepcopy(value)
        good = {'summary': 'Synthetic example only.', 'tradeoffs': ['Donor waits.'], 'checks': [],
                'checked_facts': manual.contract(value, 'Asia/Shanghai')['checked_facts']}
        variants = [good]
        for field, wrong in (('shortage_after', '999'), ('full_at_after', '2026-12-31T09:00:00+00:00'), ('unfilled_after', '0')):
            bad = copy.deepcopy(good); bad['checked_facts'][-1][field] = wrong; variants.append(bad)
        for provider in PROVIDERS:
            for index, report in enumerate(variants):
                with self.subTest(provider=provider, index=index), patch.object(manual.ai_engine.requests, 'post', return_value=http(envelope(provider, report))) as post:
                    if index == 0:
                        result = manual.run(value, provider, 'synthetic-model', 'en_US', KEY)
                        self.assertEqual(result['report']['checked_facts'], good['checked_facts'])
                    else:
                        with self.assertRaises(manual.ai_engine.AnalysisError):
                            manual.run(value, provider, 'synthetic-model', 'en_US', KEY)
                    self.assertEqual(post.call_count, 1)
        self.assertEqual(value, original)

    def test_truncated_refused_and_non_json_results_fail_in_all_workflows(self):
        value = recommendations.make()
        plan = fixtures()['tradeoff']['comparisons']['3']
        for provider in PROVIDERS:
            for failure in ('truncated', 'refused', 'non_json'):
                raw = envelope(provider, {'not': 'an accepted report'})
                if provider == 'deepseek':
                    raw['choices'][0]['finish_reason'] = 'length' if failure == 'truncated' else 'content_filter' if failure == 'refused' else 'stop'
                    raw['choices'][0]['message']['content'] = 'not JSON'
                elif provider == 'openai':
                    raw['status'] = 'incomplete' if failure == 'truncated' else 'completed'
                    raw['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'No'}] if failure == 'refused' else [{'type': 'output_text', 'text': 'not JSON'}]
                elif provider == 'gemini':
                    raw['candidates'][0]['finishReason'] = 'MAX_TOKENS' if failure == 'truncated' else 'SAFETY' if failure == 'refused' else 'STOP'
                    raw['candidates'][0]['content']['parts'] = [{'text': 'not JSON'}]
                else:
                    raw['stop_reason'] = 'max_tokens' if failure == 'truncated' else 'refusal' if failure == 'refused' else 'end_turn'
                    raw['content'] = [{'type': 'text', 'text': 'not JSON'}]
                operations = [(engine, lambda: engine.run(fixture()[0], provider, 'synthetic-model', 'en_US', KEY)),
                              (automatic.ai_engine, lambda: automatic.run(value, provider, 'synthetic-model', 'en_US', KEY)),
                              (manual.ai_engine, lambda: manual.run(plan, provider, 'synthetic-model', 'en_US', KEY))]
                for runner, operation in operations:
                    with self.subTest(provider=provider, failure=failure, runner=runner.__name__), patch.object(runner.requests, 'post', return_value=http(raw)) as post:
                        with self.assertRaises(runner.AnalysisError) as caught:
                            operation()
                        self.assertEqual(caught.exception.code, 'format')
                        self.assertEqual(post.call_count, 1)
                        self.assertEqual(caught.exception.accounting['usage']['total_tokens'], 125)

    def test_invalid_cache_usage_is_unknown_not_underreported(self):
        task, good = fixture()
        for provider in ('gemini', 'claude'):
            for bad in (True, -1, '10', None):
                raw = envelope(provider, good)
                if provider == 'claude': raw['usage']['cache_read_input_tokens'] = bad
                else:
                    raw['usageMetadata'].pop('totalTokenCount')
                    raw['usageMetadata']['thoughtsTokenCount'] = bad
                with self.subTest(provider=provider, bad=bad), patch.object(engine.requests, 'post', side_effect=[
                        http(envelope(provider)), http(raw), http(envelope(provider, good))]):
                    result = engine.run(task, provider, 'synthetic-model', 'en_US', KEY)
                    self.assertIsNone(result['usage']['total_tokens'])
                    self.assertEqual(result['usage_details']['known_total_tokens'], 250)

    def test_overlapping_shortages_and_wrong_language_rejected_for_all_providers(self):
        task, good = fixture()
        task = copy.deepcopy(task); good = copy.deepcopy(good)
        second = copy.deepcopy(task['tools']['read_calculation_evidence'][0])
        second.update(demand_ref='stock.move:5', mo_ref='WH/MO/00002', evidence_ref='calc:test:stock.move:5')
        task['tools']['read_calculation_evidence'].append(second)
        impact = copy.deepcopy(good['impacts'][0])
        impact.update(demand_ref=second['demand_ref'], mo_ref=second['mo_ref'],
                      evidence_refs=[second['demand_ref'], second['mo_ref'], second['evidence_ref'], task['order_ref']])
        good['impacts'].append(impact)
        for provider in PROVIDERS:
            for text, code in [('There is no concurrent shortage.', 'validation'), ('这两个订单的材料需要等待到货，请采购员核实预计到货时间。', 'language')]:
                bad = copy.deepcopy(good); bad['explanation'] = text
                with self.subTest(provider=provider, text=text), patch.object(engine.requests, 'post', side_effect=[http(envelope(provider, x)) for x in [None, bad, bad, bad]]) as post:
                    with self.assertRaises(engine.AnalysisError) as caught:
                        engine.run(task, provider, 'synthetic-model', 'en_US', KEY)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(post.call_count, 4)


if __name__ == '__main__':
    unittest.main()
