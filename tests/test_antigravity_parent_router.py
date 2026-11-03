"""Offline coverage for the optional Antigravity same-parent controller.

Only temporary Python programs and mocked native dispatch are used. These tests
never invoke an installed Antigravity CLI, provider, or user profile.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import antigravity_parent_router as module


CATALOG_TEXT = (
    'gemini-4-argon-low\tGemini 4 Argon (Low)\n'
    'gemini-4-argon-high\tGemini 4 Argon (High)\n'
    'gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n'
)
LOW = 'gemini-4-argon-low'
HIGH = 'gemini-4-argon-high'
SPARSE = 'gpt-oss-120b-medium'


def route(model=LOW, effort='low'):
    return {'model': model, 'effort': effort,
            'reason': 'Suitable for the next bounded task.'}


def init(conversation='same-parent', **overrides):
    value = {'event': 'init', 'conversation_id': conversation,
             'init': {'tools': [], 'model': LOW}}
    value.update(overrides)
    return value


def result(conversation='same-parent', turns=1, response='Public answer', **overrides):
    value = {'conversation_id': conversation, 'status': 'SUCCESS',
             'response': response, 'num_turns': turns, 'usage': {}}
    value.update(overrides)
    return {'event': 'result', 'result': value}


def python_command(events, *, code_after=''):
    # JSON is embedded in Python source as a literal, never interpolated in a shell.
    source = ('import json, sys\n'
              'events = json.loads(' + repr(json.dumps(events)) + ')\n'
              'for event in events:\n'
              '    print(json.dumps(event), flush=True)\n' + code_after)
    return [sys.executable, '-u', '-c', source]


class CatalogAndRouteTests(unittest.TestCase):
    def setUp(self):
        self.catalog = module.normalize_catalog(CATALOG_TEXT)

    def test_catalog_keeps_exact_native_variants_and_sparse_efforts(self):
        self.assertEqual(self.catalog, [
            {'model': LOW, 'label': 'Gemini 4 Argon (Low)', 'effort': 'low'},
            {'model': HIGH, 'label': 'Gemini 4 Argon (High)', 'effort': 'high'},
            {'model': SPARSE, 'label': 'GPT-OSS 120B (Medium)', 'effort': 'medium'},
        ])
        self.assertEqual(module.validate_route(route(HIGH, 'high'), self.catalog),
                         route(HIGH, 'high'))
        for candidate in [route(LOW, 'high'), route(HIGH, 'low'),
                          route(SPARSE, 'low'), route('gemini-4-argon', 'high'),
                          route('gpt-oss-120b-high', 'high')]:
            with self.subTest(candidate=candidate), self.assertRaises(module.RouteError):
                module.validate_route(candidate, self.catalog)

    def test_catalog_rejects_ambiguous_or_unusable_advertisements(self):
        invalid = ['', 'missing-tab-and-label\n', LOW + '\t\n',
                   CATALOG_TEXT + CATALOG_TEXT.splitlines()[0] + '\n',
                   HIGH + '\tGemini 4 Argon (Low)\n']
        for text in invalid:
            with self.subTest(catalog=text), self.assertRaises(module.RouteError):
                module.normalize_catalog(text)

    def test_route_shape_and_native_values_are_exact(self):
        invalid = [[], None, {'model': LOW}, dict(route(), extra='ignored?'),
                   route(LOW, None), route(LOW, 'LOW'), route(LOW, 'low '),
                   route(LOW, 'auto'), route(' ' + LOW, 'low'),
                   dict(route(), reason='  '), dict(route(), reason=5),
                   dict(route(), reason='x' * 601)]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(module.RouteError):
                module.validate_route(candidate, self.catalog)

    def test_model_and_effort_locks_apply_independently(self):
        self.assertEqual(module.validate_route(route(), self.catalog, model_lock=LOW), route())
        self.assertEqual(module.validate_route(route(SPARSE, 'medium'), self.catalog,
                                              effort_lock='medium')['model'], SPARSE)
        for candidate, locks in [
            (route(HIGH, 'high'), {'model_lock': LOW}),
            (route(), {'effort_lock': 'high'}),
            (route(), {'model_lock': LOW, 'effort_lock': 'high'}),
        ]:
            with self.subTest(candidate=candidate, locks=locks), self.assertRaises(module.RouteError):
                module.validate_route(candidate, self.catalog, **locks)


class InvocationProtocolTests(unittest.TestCase):
    def invoke(self, events, **kwargs):
        return module.run_invocation(python_command(events), '.', 2, **kwargs)

    def test_accepts_real_wrapped_result_and_keeps_only_public_response(self):
        secret = 'PRIVATE_REASONING_SHOULD_NEVER_BE_RETURNED'
        events = [init(), {'event': 'thinking', 'text': secret},
                  {'event': 'message', 'role': 'assistant', 'content': secret},
                  result(turns=1, structured_output=route(),
                         usage={'model': 'not-runtime-proof'})]
        value = self.invoke(events)
        self.assertEqual(value['conversation_id'], 'same-parent')
        self.assertEqual(value['turn_count'], 1)
        self.assertEqual(value['text'], 'Public answer')
        self.assertEqual(value['structured_output'], route())
        self.assertEqual(value['tools'], [])
        self.assertNotIn(secret, json.dumps(value))

    def test_resumed_results_require_same_conversation_and_exact_next_turn_count(self):
        value = self.invoke([init(), result(turns=6)],
                            conversation_id='same-parent', previous_turn_count=5)
        self.assertEqual(value['turn_count'], 6)
        invalid = [
            [init('foreign'), result('foreign', turns=6)],
            [init(), result('foreign', turns=6)],
            [init('foreign'), result(turns=6)],
            [init(), result(turns=5)],
            [init(), result(turns=4)],
            [init(), result(turns=7)],
            [init(), result(turns=True)],
        ]
        for events in invalid:
            with self.subTest(events=events), self.assertRaises(module.RouteError):
                self.invoke(events, conversation_id='same-parent', previous_turn_count=5)
        with self.assertRaises(module.RouteError):
            self.invoke([init(), result(turns=2)])

    def test_error_missing_final_and_abnormal_exit_are_not_success(self):
        invalid = [[], [init()], [init(), result(status='ERROR')],
                   [init(), result(response='')], [init(), result(response='   ')],
                   [init(), {'event': 'result', 'result': {'status': 'SUCCESS'}}]]
        for events in invalid:
            with self.subTest(events=events), self.assertRaises(module.RouteError):
                self.invoke(events)
        with self.assertRaises(module.RouteError):
            module.run_invocation(python_command([init(), result()], code_after='sys.exit(9)\n'), '.', 2)

    def test_conflicting_duplicate_results_cannot_replace_a_completed_turn(self):
        with self.assertRaises(module.RouteError):
            self.invoke([init(), result(), result('foreign', turns=2, response='Foreign answer')])

    def test_oversized_output_is_bounded_and_private_stream_is_not_in_error(self):
        secret = 'PRIVATE_STREAM_MARKER'
        command = python_command([init(), {'event': 'thinking', 'text': secret + 'x' * 16384}, result()])
        with patch.object(module, 'MAX_OUTPUT_BYTES', 8192), \
             patch.object(module, 'MAX_LINE_BYTES', 4096):
            with self.assertRaises(module.RouteError) as caught:
                module.run_invocation(command, '.', 2)
        self.assertNotIn(secret, str(caught.exception))

    @unittest.skipUnless(os.name == 'posix', 'Process-group cleanup requires POSIX')
    def test_timeout_is_bounded_and_stops_descendants_holding_pipes(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / 'child.pid'
            stopped_file = Path(directory) / 'child.stopped'
            child = ('import os, signal, time\n'
                     'from pathlib import Path\n'
                     'def stop(signum, frame):\n'
                     '    Path(' + repr(str(stopped_file)) + ').write_text("stopped")\n'
                     '    raise SystemExit(0)\n'
                     'signal.signal(signal.SIGTERM, stop)\n'
                     'Path(' + repr(str(pid_file)) + ').write_text(str(os.getpid()))\n'
                     'time.sleep(30)\n')
            parent = ('import subprocess, sys, time\n'
                      'subprocess.Popen([sys.executable, "-u", "-c", ' + repr(child) + '])\n'
                      'time.sleep(30)\n')
            started = time.monotonic()
            try:
                with self.assertRaises(module.RouteError):
                    module.run_invocation([sys.executable, '-u', '-c', parent], directory, 0.5)
                self.assertLess(time.monotonic() - started, 4)
                self.assertTrue(pid_file.exists(), 'Fixture descendant did not start')
                deadline = time.monotonic() + 1
                while not stopped_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(stopped_file.exists(), 'Timeout left the invocation descendant running')
            finally:
                if pid_file.exists() and not stopped_file.exists():
                    try:
                        os.kill(int(pid_file.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'runtime-observer.jsonl'

    def append(self, *rows):
        with self.path.open('a') as stream:
            for row in rows:
                stream.write(json.dumps(row) + '\n')

    def row(self, conversation='same-parent', model=HIGH, number=2, **extra):
        value = {'conversationId': conversation, 'invocationNum': number,
                 'modelName': model, 'phase': 'execution'}
        value.update(extra)
        return value

    def proof(self, offset, model=HIGH):
        return module.read_telemetry(self.path, offset, 'same-parent', model)

    def test_only_fresh_matching_conversation_can_verify_exact_model(self):
        self.append(self.row())
        before = module.telemetry_offset(self.path)
        self.append(self.row('foreign', LOW), self.row(number=3))
        proof = self.proof(before)
        self.assertEqual(proof['status'], 'verified')
        self.assertEqual(proof['observed_models'], [HIGH])
        self.assertFalse(proof['independent_effort_field'])
        self.assertEqual(proof['effort_evidence'], 'catalog_variant_mapping_only')

    def test_stale_foreign_or_missing_rows_leave_runtime_unknown(self):
        self.append(self.row())
        before = module.telemetry_offset(self.path)
        self.assertEqual(self.proof(before)['status'], 'unverified')
        self.append(self.row('foreign'), {'conversationId': 'same-parent', 'phase': 'execution'})
        self.assertEqual(self.proof(before)['status'], 'unverified')
        absent = Path(self.directory.name) / 'absent.jsonl'
        self.assertEqual(module.read_telemetry(absent, module.telemetry_offset(absent),
                                              'same-parent', HIGH)['status'], 'unverified')

    def test_fresh_wrong_or_mixed_models_are_mismatch(self):
        for models in [(LOW,), (HIGH, LOW)]:
            with self.subTest(models=models):
                before = module.telemetry_offset(self.path)
                self.append(*(self.row(model=model) for model in models))
                self.assertEqual(self.proof(before)['status'], 'mismatch')

    def test_replaced_or_truncated_observer_file_does_not_turn_old_rows_into_proof(self):
        self.append(self.row(number=100))
        before = module.telemetry_offset(self.path)
        replacement = self.path.with_suffix('.replacement')
        replacement.write_text(json.dumps(self.row()) + '\n')
        replacement.replace(self.path)
        self.assertEqual(self.proof(before)['status'], 'unverified')
        before = module.telemetry_offset(self.path)
        self.path.write_text('{}\n')
        self.assertEqual(self.proof(before)['status'], 'unverified')

    def test_partial_preexisting_line_cannot_be_completed_into_fresh_proof(self):
        encoded = json.dumps(self.row())
        self.path.write_text(encoded[:-2])
        before = module.telemetry_offset(self.path)
        with self.path.open('a') as stream:
            stream.write(encoded[-2:] + '\n')
        self.assertEqual(self.proof(before)['status'], 'unverified')


class SameParentControllerTests(unittest.TestCase):
    def make_router(self, **kwargs):
        with patch.object(module, '_process', return_value=CATALOG_TEXT) as catalog:
            router = module.ParentRouter('offline-agy', 'Test policy', '.', **kwargs)
        self.assertEqual(catalog.call_args.args[0], ['offline-agy', 'models'])
        return router

    def parsed(self, turns, *, selected=None, response='Work completed', init_model=None):
        value = {'conversation_id': 'same-parent', 'turn_count': turns,
                 'text': json.dumps(selected) if selected is not None else response,
                 'tools': [], 'permission_mode': 'plan'}
        if selected is not None:
            value['structured_output'] = selected
        if init_model is not None:
            value['init_model'] = init_model
        return value

    def option(self, command, name):
        return command[command.index(name) + 1] if name in command else None

    def test_selection_and_execution_resume_one_parent_with_exact_native_flags(self):
        router = self.make_router()
        responses = [self.parsed(1, selected=route(HIGH, 'high')), self.parsed(2),
                     self.parsed(3, selected=route()), self.parsed(4)]
        with patch.object(module, 'run_invocation', side_effect=responses) as invoke, \
             contextlib.redirect_stderr(io.StringIO()):
            first = router.execute('A difficult task')
            second = router.execute('A mechanical follow-up')
        self.assertEqual(invoke.call_count, 4)
        calls = [call.args for call in invoke.call_args_list]
        commands = [args[0] for args in calls]
        self.assertEqual([args[3:] for args in calls], [
            (None, None), ('same-parent', 1), ('same-parent', 2), ('same-parent', 3)])
        self.assertEqual([self.option(command, '--conversation') for command in commands],
                         [None, 'same-parent', 'same-parent', 'same-parent'])
        self.assertEqual([self.option(command, '--model') for command in commands],
                         [None, HIGH, HIGH, LOW])
        self.assertEqual([self.option(command, '--effort') for command in commands],
                         [None, 'high', 'high', 'low'])
        for index, command in enumerate(commands):
            self.assertEqual(command[:5], ['offline-agy', '--mode', 'plan',
                                           '--output-format', 'stream-json'])
            self.assertEqual(command.count('-p'), 1)
            self.assertEqual('--json-schema' in command, index % 2 == 0)
            for forbidden in ['--profile', '--settings', '--resume', '--permission-mode']:
                self.assertNotIn(forbidden, command)
        self.assertEqual(router.conversation_id, 'same-parent')
        self.assertEqual(router.turn_count, 4)
        self.assertEqual(router.current, {'model': LOW, 'effort': 'low'})
        self.assertEqual(router.record['conversation_id'], 'same-parent')
        self.assertEqual([first['status'], second['status']],
                         ['completed_unverified', 'completed_unverified'])

    def test_visible_recommendation_precedes_invocation_and_unknown_runtime_stays_unverified(self):
        router = self.make_router()
        output = io.StringIO()
        def invoke(command, cwd, timeout, conversation, turns):
            if '--json-schema' in command:
                self.assertEqual(output.getvalue().splitlines(), [
                    '[Routing][unchanged][parent] model=unknown; effort=unknown — starting task; runtime settings for this task are not yet observed'])
                return self.parsed(1, selected=route(HIGH, 'high'))
            self.assertEqual(output.getvalue().splitlines(), [
                '[Routing][unchanged][parent] model=unknown; effort=unknown — starting task; runtime settings for this task are not yet observed',
                '[Routing][recommended][parent] model=' + HIGH + '; effort=high — Suitable for the next bounded task.'])
            return self.parsed(2, init_model=HIGH)
        with patch.object(module, 'run_invocation', side_effect=invoke), \
             contextlib.redirect_stderr(output):
            entry = router.execute('Task')
        self.assertEqual(entry['status'], 'completed_unverified')
        self.assertEqual(output.getvalue().splitlines()[-1],
                         '[Routing][unverified][parent] model=unknown; effort=unknown — execution completed; effective runtime model and effort unknown')
        self.assertEqual(len(output.getvalue().splitlines()), 3)

    def test_invalid_parent_selection_stops_before_native_execution(self):
        for selection in [route(LOW, 'high'), route('unavailable-model-high', 'high'),
                          dict(route(), extra='invalid')]:
            with self.subTest(selection=selection):
                router = self.make_router()
                with patch.object(module, 'run_invocation',
                                  return_value=self.parsed(1, selected=selection)) as invoke:
                    with self.assertRaises(module.RouteError):
                        router.execute('Task')
                    with self.assertRaises(module.RouteError):
                        router.execute('Task again')
                self.assertEqual(invoke.call_count, 1)
                self.assertEqual(len(router.record['tasks']), 1)
                self.assertEqual(router.record['tasks'][0]['status'], 'failed_no_replay')

    def test_locks_reject_conflicting_selection_without_executing_work(self):
        router = self.make_router(model_lock=LOW, effort_lock='low')
        with patch.object(module, 'run_invocation',
                          return_value=self.parsed(1, selected=route(HIGH, 'high'))) as invoke:
            with self.assertRaises(module.RouteError):
                router.execute('Task')
        self.assertEqual(invoke.call_count, 1)

    def test_impossible_lock_fails_before_any_conversation_is_created(self):
        with patch.object(module, '_process', return_value=CATALOG_TEXT), \
             patch.object(module, 'run_invocation') as invoke:
            with self.assertRaises(module.RouteError):
                module.ParentRouter('offline-agy', 'Policy', '.',
                                    model_lock=LOW, effort_lock='high')
        invoke.assert_not_called()

    def test_locks_constrain_the_initial_selection_invocation_as_well_as_execution(self):
        for locks, chosen in [({'model_lock': HIGH}, route(HIGH, 'high')),
                              ({'effort_lock': 'medium'}, route(SPARSE, 'medium'))]:
            with self.subTest(locks=locks):
                router = self.make_router(**locks)
                with patch.object(module, 'run_invocation', side_effect=[
                        self.parsed(1, selected=chosen), self.parsed(2)]) as invoke, \
                     contextlib.redirect_stderr(io.StringIO()):
                    router.execute('Task')
                for call in invoke.call_args_list:
                    self.assertEqual(self.option(call.args[0], '--model'), chosen['model'])
                    self.assertEqual(self.option(call.args[0], '--effort'), chosen['effort'])

    def test_explicit_initial_variant_cannot_bypass_either_lock(self):
        for locks in [{'model_lock': HIGH}, {'effort_lock': 'medium'}]:
            with self.subTest(locks=locks), \
                 patch.object(module, '_process', return_value=CATALOG_TEXT), \
                 patch.object(module, 'run_invocation') as invoke:
                with self.assertRaises(module.RouteError):
                    module.ParentRouter('offline-agy', 'Policy', '.', initial_model=LOW, **locks)
                invoke.assert_not_called()

    def test_failed_execution_is_never_replayed_or_resumed_with_drifted_context(self):
        router = self.make_router(initial_model=LOW)
        output = io.StringIO()
        with patch.object(module, 'run_invocation', side_effect=[
                self.parsed(1, selected=route(HIGH, 'high')),
                module.RouteError('Execution failed after starting')]) as invoke, \
             contextlib.redirect_stderr(output):
            with self.assertRaises(module.RouteError):
                router.execute('Do this once')
            with self.assertRaises(module.RouteError):
                router.execute('Try another task')
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(invoke.call_args_list[-1].args[3:], ('same-parent', 1))
        self.assertEqual(router.turn_count, 1)
        self.assertEqual(router.current, {'model': LOW, 'effort': 'low'})
        self.assertEqual(len(router.record['tasks']), 1)
        self.assertEqual(router.record['tasks'][0]['status'], 'failed_no_replay')
        self.assertEqual(output.getvalue().splitlines()[-1],
                         '[Routing][error][parent] model=unknown; effort=unknown — routing or execution failed; no replay')
        self.assertEqual(len(output.getvalue().splitlines()), 3)

    def test_init_request_metadata_alone_cannot_verify_runtime_settings(self):
        router = self.make_router()
        with patch.object(module, 'run_invocation', side_effect=[
                self.parsed(1, selected=route(HIGH, 'high'), init_model=HIGH),
                self.parsed(2, init_model=HIGH)]), contextlib.redirect_stderr(io.StringIO()):
            entry = router.execute('Task')
        self.assertEqual(entry['status'], 'completed_unverified')
        self.assertEqual(entry['settings_status'], 'requested')
        self.assertNotIn('effective', entry)

    def test_fresh_runtime_model_mismatch_records_failure_without_repeating_execution(self):
        router = self.make_router()
        output = io.StringIO()
        proof = {'status': 'mismatch', 'observed_models': [LOW]}
        with patch.object(module, 'run_invocation', side_effect=[
                self.parsed(1, selected=route(HIGH, 'high')), self.parsed(2)]) as invoke, \
             patch.object(module, 'read_telemetry', return_value=proof), \
             contextlib.redirect_stderr(output):
            with self.assertRaises(module.RouteError):
                router.execute('Task')
            with self.assertRaises(module.RouteError):
                router.execute('Task again')
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(router.record['tasks'][0]['status'], 'completed_runtime_mismatch')
        self.assertEqual(output.getvalue().splitlines()[-1],
                         '[Routing][error][parent] model=' + LOW + '; effort=unknown — execution runtime model differs from the requested variant; no replay')
        self.assertNotIn('[Routing][verified]', output.getvalue())

    def test_verified_variant_preserves_limit_of_independent_effort_evidence(self):
        router = self.make_router()
        output = io.StringIO()
        proof = {'status': 'verified', 'observed_models': [HIGH],
                 'effort_evidence': 'catalog_variant_mapping_only',
                 'independent_effort_field': False}
        with patch.object(module, 'run_invocation', side_effect=[
                self.parsed(1, selected=route(HIGH, 'high')), self.parsed(2)]), \
             patch.object(module, 'read_telemetry', return_value=proof), \
             contextlib.redirect_stderr(output):
            entry = router.execute('Task')
        self.assertEqual(entry['status'], 'completed_verified_model_variant')
        self.assertEqual(entry['effective']['model'], HIGH)
        self.assertEqual(entry['effective']['effort'], 'high')
        self.assertFalse(entry['effective']['independent_effort_field'])
        self.assertEqual(output.getvalue().splitlines(), [
            '[Routing][unchanged][parent] model=unknown; effort=unknown — starting task; runtime settings for this task are not yet observed',
            '[Routing][recommended][parent] model=' + HIGH + '; effort=high — Suitable for the next bounded task.',
            '[Routing][verified][parent] model=' + HIGH + '; effort=high — model variant verified; effort mapped from catalog'])


@unittest.skipUnless(os.name == 'posix', 'The prototype intentionally supports POSIX only')
class OfflineCliIntegrationTests(unittest.TestCase):
    def test_repeated_sigint_cannot_interrupt_cleanup_and_leave_a_descendant_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / 'fake-agy'
            ready = root / 'child.pid'
            invocation_pid = root / 'invocation.pid'
            terminated = root / 'term-received'
            heartbeat = root / 'heartbeat'
            child = ('import os, signal, time\nfrom pathlib import Path\n'
                     'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                     'Path(' + repr(str(ready)) + ').write_text(str(os.getpid()))\n'
                     'while True:\n'
                     '    with Path(' + repr(str(heartbeat)) + ').open("a") as stream:\n'
                     '        stream.write("x")\n'
                     '    time.sleep(0.02)\n')
            cli.write_text(
                '#!' + sys.executable + '\n'
                'import json, os, signal, subprocess, sys, time\nfrom pathlib import Path\n'
                'if sys.argv[1:] == ["models"]:\n'
                '    print(' + repr(CATALOG_TEXT) + ', end="")\n'
                '    raise SystemExit(0)\n'
                'Path(' + repr(str(invocation_pid)) + ').write_text(str(os.getpid()))\n'
                'def ignore_term(signum, frame):\n'
                '    Path(' + repr(str(terminated)) + ').write_text("received")\n'
                'signal.signal(signal.SIGTERM, ignore_term)\n'
                'subprocess.Popen([sys.executable, "-u", "-c", ' + repr(child) + '])\n'
                'time.sleep(30)\n')
            cli.chmod(0o700)
            command = [sys.executable, str(Path(module.__file__).resolve()),
                       '--agy', str(cli), '--cwd', str(root), '--task', 'Task', '--timeout', '10']
            controller = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), 'Fake invocation descendant did not start')
                controller.send_signal(signal.SIGINT)
                deadline = time.monotonic() + 2
                while not terminated.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(terminated.exists(), 'Controller did not enter subprocess cleanup')
                controller.send_signal(signal.SIGINT)
                controller.wait(timeout=4)
                before = heartbeat.stat().st_size
                time.sleep(0.15)
                self.assertEqual(heartbeat.stat().st_size, before,
                                 'Repeated SIGINT interrupted cleanup, leaving a running descendant')
            finally:
                if controller.poll() is None:
                    controller.kill()
                    controller.wait(timeout=2)
                if invocation_pid.exists():
                    try:
                        os.killpg(int(invocation_pid.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_two_tasks_save_public_record_and_resume_the_same_fake_conversation(self):
        secret = 'PRIVATE_REASONING_AND_STDERR_NEVER_PERSIST'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / 'fake-agy'
            state = root / 'count.txt'
            trace = root / 'calls.jsonl'
            saved = root / 'record.json'
            source = (
                '#!' + sys.executable + '\n'
                'import json, sys\nfrom pathlib import Path\n'
                'args = sys.argv[1:]\n'
                'if args == ["models"]:\n'
                '    print(' + repr(CATALOG_TEXT) + ', end="")\n'
                '    raise SystemExit(0)\n'
                'state = Path(' + repr(str(state)) + ')\n'
                'count = int(state.read_text()) + 1 if state.exists() else 1\n'
                'state.write_text(str(count))\n'
                'with Path(' + repr(str(trace)) + ').open("a") as stream:\n'
                '    stream.write(json.dumps(args) + "\\n")\n'
                'if count > 1:\n'
                '    assert args[args.index("--conversation") + 1] == "same-parent"\n'
                'selection = "--json-schema" in args\n'
                'choice = ' + repr(route(HIGH, 'high')) + '\n'
                'response = json.dumps(choice) if selection else "Public answer " + str(count)\n'
                'print(json.dumps({"event":"init", "conversation_id":"same-parent",'
                ' "init":{"tools":[], "model":' + repr(HIGH) + '}}), flush=True)\n'
                'print(json.dumps({"event":"thinking", "text":' + repr(secret) + '}), flush=True)\n'
                'print(' + repr(secret) + ', file=sys.stderr, flush=True)\n'
                'value = {"conversation_id":"same-parent", "status":"SUCCESS",'
                ' "num_turns":count, "response":response, "usage":{}}\n'
                'if selection:\n'
                '    value["structured_output"] = choice\n'
                'print(json.dumps({"event":"result", "result":value}), flush=True)\n'
            )
            cli.write_text(source)
            cli.chmod(0o700)
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = module.main(['--agy', str(cli), '--cwd', str(root),
                                         '--task', 'First task', '--task', 'Follow-up',
                                         '--record', str(saved), '--timeout', '3'])
            self.assertEqual(exit_code, 0, stderr.getvalue())
            record_text = saved.read_text()
            record = json.loads(record_text)
            self.assertEqual(record['conversation_id'], 'same-parent')
            self.assertEqual([entry['response'] for entry in record['tasks']],
                             ['Public answer 2', 'Public answer 4'])
            self.assertEqual([entry['status'] for entry in record['tasks']],
                             ['completed_unverified', 'completed_unverified'])
            self.assertEqual(state.read_text(), '4')
            self.assertEqual(len(trace.read_text().splitlines()), 4)
            self.assertNotIn(secret, record_text)
            self.assertNotIn(secret, stdout.getvalue())
            self.assertNotIn(secret, stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
