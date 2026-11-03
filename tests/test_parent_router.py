"""Offline tests of native route validation and same-parent sequencing.

These tests use fake RPC messages. They do not invoke Codex or any provider.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_parent_router as module


def advertised(model='fast', efforts=('low', 'high'), default='low', **extra):
    value = {'model': model, 'hidden': False, 'description': 'Test model',
             'supportedReasoningEfforts': [{'reasoningEffort': e} for e in efforts],
             'defaultReasoningEffort': default, 'isDefault': model == 'fast',
             'inputModalities': ['text']}
    value.update(extra)
    return value


def route(model='fast', effort='low'):
    return {'model': model, 'effort': effort, 'reason': 'Suitable for the next bounded task.'}


def item_event(turn_id='turn-1', text='final', *, thread='parent', item_id='message', kind='agentMessage'):
    return {'method': 'item/completed', 'params': {
        'threadId': thread, 'turnId': turn_id,
        'item': {'id': item_id, 'type': kind, 'text': text}}}


def complete_event(turn_id='turn-1', status='completed', items=None, *, thread='parent'):
    return {'method': 'turn/completed', 'params': {
        'threadId': thread, 'turn': {'id': turn_id, 'status': status, 'items': items or []}}}


class TurnRpc:
    def __init__(self, notifications):
        self.notifications = deepcopy(notifications)
        self.calls = []

    def request(self, method, params, timeout=60):
        self.calls.append((method, deepcopy(params)))
        if method == 'turn/start':
            return {'turn': {'id': 'turn-1'}}
        if method == 'turn/interrupt':
            return {}
        raise AssertionError('Unexpected offline request: ' + method)

    def wait_notification(self, predicate, timeout=60):
        for index, notification in enumerate(self.notifications):
            if predicate(notification):
                return self.notifications.pop(index)
        raise TimeoutError('No matching fake notification')


class ControllerRpc:
    def __init__(self, catalog=None):
        self.catalog = catalog or [advertised(), advertised('deep', default='high')]
        self.calls = []
        self.events = []
        self.snapshot = {'model': 'fast', 'reasoningEffort': 'low'}

    def request(self, method, params, timeout=60):
        self.calls.append((method, deepcopy(params)))
        self.events.append(method)
        if method == 'model/list':
            return {'data': self.catalog, 'nextCursor': None}
        if method == 'thread/start':
            return {'model': params['model'], 'reasoningEffort': 'low',
                    'thread': {'id': 'same-parent', 'path': None}}
        if method == 'thread/settings/update':
            self.snapshot = {'model': params['model'], 'reasoningEffort': params.get('effort')}
            return {}
        if method == 'thread/read':
            return {'thread': self.snapshot}
        raise AssertionError('Unexpected offline request: ' + method)


class RouteValidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = module.normalize_catalog([
            advertised(), advertised('deep', efforts=('medium', 'high'), default='medium'),
        ])

    def test_exact_native_sparse_efforts_are_not_inferred(self):
        self.assertEqual(module.validate_route(route('fast', 'high'), self.catalog)['effort'], 'high')
        for effort in ['medium', 'HIGH', 'high ', 'auto', None]:
            with self.subTest(effort=effort), self.assertRaises(module.RouteError):
                module.validate_route(route('fast', effort), self.catalog)

    def test_model_and_effort_locks_are_independent_and_exact(self):
        self.assertEqual(module.validate_route(route(), self.catalog, model_lock='fast'), route())
        self.assertEqual(module.validate_route(route('deep', 'high'), self.catalog, effort_lock='high')['model'], 'deep')
        for chosen, locks in [
            (route('deep', 'high'), {'model_lock': 'fast'}),
            (route('fast', 'high'), {'effort_lock': 'low'}),
            (route('fast', 'low'), {'model_lock': 'fast', 'effort_lock': 'high'}),
        ]:
            with self.subTest(chosen=chosen, locks=locks), self.assertRaises(module.RouteError):
                module.validate_route(chosen, self.catalog, **locks)

    def test_default_only_model_requires_null_instead_of_invented_effort(self):
        # The standalone validator can represent a host's default-only model.
        # The parent controller separately excludes it when an effort reset
        # cannot be guaranteed by the same-thread native settings API.
        catalog = self.catalog + [{'model': 'default-only', 'efforts': []}]
        self.assertIsNone(module.validate_route(route('default-only', None), catalog)['effort'])
        with self.assertRaises(module.RouteError):
            module.validate_route(route('default-only', 'low'), catalog)

    def test_parent_catalog_excludes_default_only_models_without_a_native_reset(self):
        values = module.normalize_catalog([advertised(), advertised('default-only', efforts=(), default=None)])
        self.assertEqual([item['model'] for item in values], ['fast'])
        with self.assertRaises(module.RouteError):
            module.normalize_catalog([advertised('default-only', efforts=(), default=None)])

    def test_exact_shape_model_and_reason_are_validated(self):
        candidates = [[], {'model': 'fast'}, dict(route(), extra='not allowed'),
                      route('absent', 'low'), dict(route(), reason='  '),
                      dict(route(), reason=7), dict(route(), reason='x' * 601)]
        for chosen in candidates:
            with self.subTest(chosen=chosen), self.assertRaises(module.RouteError):
                module.validate_route(chosen, self.catalog)

    def test_visible_duplicates_and_duplicate_efforts_fail_closed(self):
        for values in [[advertised(), advertised()],
                       [advertised(efforts=('low', 'low'))],
                       [advertised(default='ultra')]]:
            with self.subTest(values=values), self.assertRaises(module.RouteError):
                module.normalize_catalog(values)
        visible = module.normalize_catalog([advertised(), advertised('hidden', hidden=True)])
        self.assertEqual([x['model'] for x in visible], ['fast'])

    def test_catalog_pagination_cycle_is_bounded(self):
        class Pages:
            def __init__(self):
                self.calls = []
            def request(self, method, params):
                self.calls.append(deepcopy(params))
                return {'data': [], 'nextCursor': 'same-cursor'}
        rpc = Pages()
        with self.assertRaises(module.RouteError):
            module.model_list(rpc)
        self.assertEqual(len(rpc.calls), 2)
        self.assertNotIn('cursor', rpc.calls[0])
        self.assertEqual(rpc.calls[1]['cursor'], 'same-cursor')


class TurnTests(unittest.TestCase):
    def test_stream_deltas_do_not_accumulate_across_parent_tasks(self):
        deltas = [{'method': 'item/agentMessage/delta',
                   'params': {'threadId': 'parent', 'turnId': 'turn-1', 'delta': 'x'}}
                  for _ in range(500)]
        rpc = TurnRpc(deltas + [item_event(text='answer'), complete_event()])
        self.assertEqual(module.run_turn(rpc, 'parent', 'Task', 2)['text'], 'answer')
        self.assertEqual(rpc.notifications, [])

    def test_only_current_thread_and_turn_output_is_used(self):
        rpc = TurnRpc([item_event(thread='another'), item_event(turn_id='old', text='old'),
                       complete_event(turn_id='old'),
                       item_event(text='intermediate', item_id='one'),
                       item_event(text='actual final', item_id='two'), complete_event()])
        result = module.run_turn(rpc, 'parent', 'Task', 2)
        self.assertEqual(result, {'turn_id': 'turn-1', 'status': 'completed', 'text': 'actual final'})
        self.assertEqual(rpc.notifications[0]['params']['threadId'], 'another')
        self.assertEqual([call[0] for call in rpc.calls], ['turn/start'])

    def test_completion_items_can_supply_final_output(self):
        rpc = TurnRpc([complete_event(items=[{'id': 'final', 'type': 'agentMessage', 'text': 'answer'}])])
        self.assertEqual(module.run_turn(rpc, 'parent', 'Task', 2)['text'], 'answer')

    def test_schema_is_forwarded_only_for_selection(self):
        rpc = TurnRpc([item_event(), complete_event()])
        schema = {'type': 'object'}
        module.run_turn(rpc, 'parent', 'Select', 2, schema)
        self.assertEqual(rpc.calls[0][1]['outputSchema'], schema)

    def test_failed_or_interrupted_turn_is_not_success_and_is_not_retried(self):
        for status in ['failed', 'interrupted']:
            rpc = TurnRpc([complete_event(status=status)])
            with self.subTest(status=status), self.assertRaises(module.RouteError):
                module.run_turn(rpc, 'parent', 'Task', 2)
            self.assertEqual([x[0] for x in rpc.calls], ['turn/start', 'turn/interrupt'])

    def test_missing_assistant_output_is_an_error(self):
        rpc = TurnRpc([item_event(kind='reasoning'), complete_event()])
        with self.assertRaises(module.RouteError):
            module.run_turn(rpc, 'parent', 'Task', 2)
        self.assertEqual([x[0] for x in rpc.calls], ['turn/start', 'turn/interrupt'])


class SameParentTests(unittest.TestCase):
    def test_startup_without_advertised_default_sets_an_explicit_supported_effort(self):
        model = advertised('fast', efforts=('high', 'low'), default=None)
        model.pop('defaultReasoningEffort')
        rpc = ControllerRpc(catalog=[model])
        module.ParentRouter(rpc, 'Policy', '.')
        started = next(params for method, params in rpc.calls if method == 'thread/start')
        self.assertEqual(started['model'], 'fast')
        self.assertEqual(started['config']['model_reasoning_effort'], 'high')
        self.assertIn(started['config']['model_reasoning_effort'], ['high', 'low'])

    def make_router(self, **kwargs):
        rpc = ControllerRpc()
        router = module.ParentRouter(rpc, 'Test policy', '.', **kwargs)
        rpc.events.clear()
        return rpc, router

    def mocked_turns(self, rpc, chosen):
        values = iter(chosen)
        def run(rpc_arg, thread, text, timeout, schema=None):
            self.assertIs(rpc_arg, rpc)
            self.assertEqual(thread, 'same-parent')
            if schema is not None:
                rpc.events.append('selection')
                return {'turn_id': 'select-' + str(len(rpc.events)), 'status': 'completed',
                        'text': json.dumps(next(values))}
            rpc.events.append('execution')
            return {'turn_id': 'execute-' + str(len(rpc.events)), 'status': 'completed', 'text': 'Work completed'}
        return run

    def test_selection_update_execution_keep_one_parent_thread(self):
        rpc, router = self.make_router()
        with patch.object(module, 'run_turn', side_effect=self.mocked_turns(rpc, [route('deep', 'high'), route()])), \
             patch.object(module, 'resolved_turn', side_effect=[route('deep', 'high'), route()]), \
             contextlib.redirect_stderr(io.StringIO()):
            first = router.execute('Complex task')
            second = router.execute('Mechanical task')
        self.assertEqual(rpc.events, ['selection', 'thread/settings/update', 'execution', 'thread/read'] * 2)
        self.assertEqual(sum(method == 'thread/start' for method, _ in rpc.calls), 1)
        updates = [params for method, params in rpc.calls if method == 'thread/settings/update']
        self.assertEqual(updates, [
            {'threadId': 'same-parent', 'model': 'deep', 'effort': 'high'},
            {'threadId': 'same-parent', 'model': 'fast', 'effort': 'low'},
        ])
        self.assertTrue(all(entry['execution_thread_id'] == 'same-parent' for entry in [first, second]))
        self.assertTrue(all(entry['status'] == 'completed_verified_runtime' for entry in [first, second]))
        self.assertEqual(router.current, {'model': 'fast', 'effort': 'low'})

    def test_visible_requested_receipt_follows_submission_and_runtime_receipt_follows_execution(self):
        rpc, router = self.make_router()
        output = io.StringIO()
        def run(rpc_arg, thread, text, timeout, schema=None):
            if schema is not None:
                self.assertEqual(output.getvalue().splitlines(), [
                    '[Routing][unchanged][parent] model=unknown; effort=unknown — starting task; runtime settings for this task are not yet observed'])
                return {'turn_id': 'selection', 'text': json.dumps(route('deep', 'high'))}
            self.assertEqual(rpc.events[-1], 'thread/settings/update')
            self.assertEqual(output.getvalue().splitlines(), [
                '[Routing][unchanged][parent] model=unknown; effort=unknown — starting task; runtime settings for this task are not yet observed',
                '[Routing][requested][parent] model=deep; effort=high — Suitable for the next bounded task.'])
            return {'turn_id': 'execution', 'text': 'Public answer'}
        with patch.object(module, 'run_turn', side_effect=run), \
             patch.object(module, 'resolved_turn', return_value={'model': 'deep', 'effort': 'high'}), \
             contextlib.redirect_stderr(output):
            entry = router.execute('Task')
        self.assertEqual(entry['status'], 'completed_verified_runtime')
        self.assertEqual(output.getvalue().splitlines()[-1],
                         '[Routing][verified][parent] model=deep; effort=high — execution runtime model and effort match the requested pair')
        self.assertEqual(len(output.getvalue().splitlines()), 3)

    def test_failed_submission_never_reports_requested_or_applied_settings(self):
        rpc, router = self.make_router()
        original_request = rpc.request
        def request(method, params, timeout=60):
            if method == 'thread/settings/update':
                raise module.RouteError('Settings rejected')
            return original_request(method, params, timeout)
        output = io.StringIO()
        with patch.object(module, 'run_turn', side_effect=self.mocked_turns(rpc, [route('deep', 'high')])) as turns, \
             patch.object(rpc, 'request', side_effect=request), contextlib.redirect_stderr(output):
            with self.assertRaises(module.RouteError):
                router.execute('Task')
        self.assertEqual(turns.call_count, 1)
        self.assertEqual(output.getvalue().splitlines(), [
            '[Routing][unchanged][parent] model=unknown; effort=unknown — starting task; runtime settings for this task are not yet observed',
            '[Routing][error][parent] model=unknown; effort=unknown — routing or execution failed; effective runtime settings unknown'])

    def test_invalid_route_does_not_update_settings_or_execute_work(self):
        rpc, router = self.make_router()
        invalid = route('fast', 'medium')
        with patch.object(module, 'run_turn', side_effect=self.mocked_turns(rpc, [invalid])) as turns:
            with self.assertRaises(module.RouteError):
                router.execute('Task')
        self.assertEqual(turns.call_count, 1)
        self.assertEqual(rpc.events, ['selection'])
        self.assertEqual(router.record['tasks'], [])

    def test_runtime_mismatch_records_failure_without_retrying_work(self):
        rpc, router = self.make_router()
        output = io.StringIO()
        with patch.object(module, 'run_turn', side_effect=self.mocked_turns(rpc, [route('deep', 'high')])) as turns, \
             patch.object(module, 'resolved_turn', return_value={'model': 'fast', 'effort': 'low'}), \
             contextlib.redirect_stderr(output):
            with self.assertRaises(module.RouteError):
                router.execute('Task')
        self.assertEqual(turns.call_count, 2)
        self.assertEqual(rpc.events.count('execution'), 1)
        self.assertEqual(router.record['tasks'][0]['status'], 'completed_runtime_mismatch')
        self.assertEqual(output.getvalue().splitlines(), [
            '[Routing][unchanged][parent] model=unknown; effort=unknown — starting task; runtime settings for this task are not yet observed',
            '[Routing][requested][parent] model=deep; effort=high — Suitable for the next bounded task.',
            '[Routing][error][parent] model=fast; effort=low — effective runtime settings differ from the requested pair; no retry'])

    def test_thread_metadata_alone_is_not_verified_execution_evidence(self):
        rpc, router = self.make_router()
        output = io.StringIO()
        with patch.object(module, 'run_turn', side_effect=self.mocked_turns(rpc, [route('deep', 'high')])), \
             patch.object(module, 'resolved_turn', return_value=None), \
             contextlib.redirect_stderr(output):
            entry = router.execute('Task')
        self.assertEqual(entry['thread_settings_after'], {'model': 'deep', 'effort': 'high'})
        self.assertEqual(entry['status'], 'completed_unverified')
        self.assertNotIn('effective', entry)
        self.assertEqual(output.getvalue().splitlines()[-1],
                         '[Routing][unverified][parent] model=unknown; effort=unknown — execution completed; effective runtime settings unavailable or incomplete')
        self.assertEqual(len(output.getvalue().splitlines()), 3)

    def test_unknown_partial_effective_settings_are_not_called_a_verified_mismatch(self):
        rpc, router = self.make_router()
        with patch.object(module, 'run_turn', side_effect=self.mocked_turns(rpc, [route('deep', 'high')])), \
             patch.object(module, 'resolved_turn', return_value={'model': 'deep', 'effort': None}), \
             contextlib.redirect_stderr(io.StringIO()):
            entry = router.execute('Task')
        self.assertEqual(entry['status'], 'completed_unverified')

    def test_unfulfillable_lock_is_rejected_before_starting_a_parent(self):
        rpc = ControllerRpc()
        with self.assertRaises(module.RouteError):
            module.ParentRouter(rpc, 'Policy', '.', model_lock='fast', effort_lock='medium')
        self.assertFalse(any(method == 'thread/start' for method, _ in rpc.calls))


class ResolvedTurnTests(unittest.TestCase):
    def resolve(self, rows, turn='wanted'):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'own-rollout.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
            return module.resolved_turn(path, turn)

    def test_exact_turn_context_match_ignores_copied_or_other_turns(self):
        rows = [
            {'type': 'turn_context', 'payload': {'turn_id': 'copied', 'model': 'fast', 'effort': 'low'}},
            {'type': 'event_msg', 'payload': {'turn_id': 'wanted', 'model': 'wrong', 'effort': 'low'}},
            {'type': 'turn_context', 'payload': {'turn_id': 'wanted', 'model': 'deep', 'effort': 'high'}},
        ]
        self.assertEqual(self.resolve(rows), {'model': 'deep', 'effort': 'high'})
        self.assertIsNone(self.resolve(rows, 'absent'))

    def test_missing_effective_fields_do_not_establish_runtime_values(self):
        rows = [{'type': 'turn_context', 'payload': {'turn_id': 'wanted', 'model': 'deep'}}]
        self.assertIsNone(self.resolve(rows))

    def test_missing_rollout_is_unknown(self):
        self.assertIsNone(module.resolved_turn(None, 'wanted'))
        self.assertIsNone(module.resolved_turn('/no/such/controller-rollout.jsonl', 'wanted'))


if __name__ == '__main__':
    unittest.main()
