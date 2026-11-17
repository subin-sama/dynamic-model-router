import base64
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('image_bridge_under_test', SCRIPTS / 'codex_image_bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def png(width=2, height=2):
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    raster = b''.join(b'\0' + b'\xff\x80\x00\xff' * width for _ in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raster)) + chunk(b'IEND', b'')


def image_item(data=None, identity='image-1'):
    return {'type': 'imageGeneration', 'id': identity, 'status': 'completed',
            'result': base64.b64encode(data or png()).decode(),
            'savedPath': '/untrusted/existing-file.png', 'revisedPrompt': 'Private prompt detail'}


def event(method, item=None, thread='thread-1', turn='turn-1', status='completed'):
    params = {'threadId': thread, 'turnId': turn}
    if item:
        params['item'] = item
    if method == 'turn/completed':
        params['turn'] = {'id': turn, 'status': status, 'items': []}
    return {'method': method, 'params': params}


class FakeRpc:
    def __init__(self, events=None):
        self.calls = []
        self.events = list(events if events is not None else [event('item/completed', image_item()), event('turn/completed')])
        self.caps = {'imageGeneration': True, 'namespaceTools': True}
        self.account = {'account': {'type': 'chatgpt', 'planType': 'plus', 'email': 'private@example.invalid'}}
        self.models = {'data': [{'id': 'chat-default', 'model': 'chat-default', 'inputModalities': ['text', 'image'],
                                'supportedReasoningEfforts': [{'reasoningEffort': 'low'}, {'reasoningEffort': 'medium'}],
                                'defaultReasoningEffort': 'medium', 'isDefault': True}], 'nextCursor': None}
        self.mcp = {'data': [{'name': 'chrome-devtools'}, {'name': 'server"quoted'}], 'nextCursor': None}
        self.start = {'thread': {'id': 'thread-1'}, 'model': 'chat-default', 'reasoningEffort': 'medium'}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, method, params, timeout=60):
        self.calls.append((method, params, timeout))
        if method == 'initialize':
            return {}
        if method == 'modelProvider/capabilities/read':
            return self.caps
        if method == 'account/read':
            return self.account
        if method == 'model/list':
            return self.models
        if method == 'mcpServerStatus/list':
            if params.get('threadId'):
                return {'data': [{'name': 'chrome-devtools', 'tools': {}}], 'nextCursor': None}
            return self.mcp
        if method == 'thread/start':
            return self.start
        if method == 'turn/start':
            return {'turn': {'id': 'turn-1'}}
        if method == 'turn/interrupt':
            return {}
        raise AssertionError('Unexpected native operation: ' + method)

    def notify(self, method, params):
        self.calls.append((method, params, None))

    def wait_notification(self, predicate, timeout=60):
        for i, value in enumerate(self.events):
            if predicate(value):
                return self.events.pop(i)
        raise TimeoutError('No matching event')


class ImageBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary = self.root / 'codex'
        self.binary.write_bytes(b'fixture executable')
        self.binary.chmod(0o700)
        self.env = patch.dict(os.environ, {'XDG_STATE_HOME': str(self.root / 'state')})
        self.env.start()
        self.executable = patch.object(bridge.shutil, 'which', return_value=str(self.binary))
        self.executable.start()
        original_candidates = bridge._runtime_candidates
        self.candidates = patch.object(bridge, '_runtime_candidates', side_effect=lambda explicit=None:
                                       original_candidates(explicit) if explicit is not None else [('PATH', self.binary)])
        self.candidates.start()
        self.version = patch.object(bridge, '_read_version', return_value='0.146.0')
        self.version.start()
        self.request = self.root / 'request.json'
        self.output = self.root / 'image.png'

    def tearDown(self):
        self.executable.stop()
        self.candidates.stop()
        self.version.stop()
        self.env.stop()
        self.temp.cleanup()

    def prepared(self):
        return bridge.prepare('An orange cat drinking tea in a garden.', self.request)

    def generate(self, rpc, **kwargs):
        return bridge.generate(self.request, bridge.ROUTE, self.output, True,
                               rpc_factory=lambda *a, **k: rpc, **kwargs)

    def assert_code(self, code, callback):
        with self.assertRaises(bridge.BridgeError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_prepare_requires_choice_without_starting_a_provider(self):
        with patch.object(bridge, '_executable', side_effect=AssertionError('Provider must not start')):
            result = self.prepared()
        self.assertEqual(result['status'], 'choice_required')
        self.assertFalse(result['generation_authorized'])
        self.assertFalse(result['inference_sent'])
        self.assertEqual(len(result['routes']), 1)
        self.assertEqual(json.loads(self.request.read_text())['prompt'], 'An orange cat drinking tea in a garden.')
        self.assertFalse(self.output.exists())

    def test_runtime_discovery_prefers_newer_protocol_but_preserves_explicit_executable(self):
        newer = self.root / 'bundled-codex'
        newer.write_bytes(b'new fixture executable')
        newer.chmod(0o700)
        original_candidates = self.candidates.get_original()[0]
        with patch.object(bridge, '_runtime_candidates', side_effect=lambda explicit=None:
                          original_candidates(explicit) if explicit else [('PATH', self.binary), ('macos_app_bundle', newer)]), \
                patch.object(bridge, '_read_version', side_effect=lambda p: '0.169.0-alpha.11.1' if Path(p) == newer.resolve() else '0.146.0'):
            selected = bridge.discover_runtime()
            explicit = bridge.discover_runtime(str(self.binary))
        self.assertEqual(selected['executable'], str(newer.resolve()))
        self.assertEqual(selected['selection_basis'], 'newest_detected_native_protocol')
        self.assertEqual(explicit['executable'], str(self.binary.resolve()))
        self.assertEqual(explicit['selection_basis'], 'explicit')

    def test_prepared_request_binds_runtime_and_rejects_binary_replacement(self):
        result = self.prepared()
        self.assertEqual(result['runtime_discovery']['executable'], str(self.binary.resolve()))
        self.binary.write_bytes(b'replaced executable content')
        with patch.object(bridge, 'BoundedRpcClient', side_effect=AssertionError('RPC must not start')):
            self.assert_code('codex_runtime_changed', lambda: self.generate(FakeRpc()))
        self.assertFalse(self.output.exists())

    def test_explicit_runtime_never_falls_back_to_another_binary(self):
        unavailable = self.root / 'absent-codex'
        self.assert_code('codex_not_executable', lambda: bridge.discover_runtime(str(unavailable)))
        self.assert_code('invalid_codex_path', lambda: bridge.discover_runtime('relative-codex'))

    def test_missing_execute_or_selection_cannot_start_native_generation(self):
        self.prepared()
        with patch.object(bridge, '_executable', side_effect=AssertionError('Provider must not start')):
            a = bridge.generate(self.request, None, self.output, True)
            b = bridge.generate(self.request, bridge.ROUTE, self.output, False)
        self.assertEqual(a['status'], 'choice_required')
        self.assertEqual(b['status'], 'choice_required')

    def test_wrong_route_does_not_dispatch(self):
        self.prepared()
        with patch.object(bridge, '_executable', side_effect=AssertionError('Provider must not start')):
            self.assert_code('wrong_route', lambda: bridge.generate(self.request, 'imaginary-provider', self.output, True))

    def test_cancelled_request_and_copied_ticket_cannot_replay(self):
        self.prepared()
        copied = self.root / 'copy.json'
        copied.write_bytes(self.request.read_bytes())
        self.assertEqual(bridge.cancel(self.request)['status'], 'cancelled')
        with patch.object(bridge, '_executable', side_effect=AssertionError('Provider must not start')):
            self.assert_code('request_consumed', lambda: bridge.generate(copied, bridge.ROUTE, self.output, True))
        self.assertFalse(self.output.exists())

    def test_modified_prompt_is_not_an_issued_ticket(self):
        self.prepared()
        ticket = json.loads(self.request.read_text())
        ticket['prompt'] = 'A different prompt'
        ticket['prompt_sha256'] = bridge.digest(ticket['prompt'].encode())
        self.request.write_text(json.dumps(ticket))
        self.assert_code('request_changed', lambda: bridge.cancel(self.request))

    def test_expired_ticket_is_rejected_without_provider(self):
        with patch.object(bridge.time, 'time', return_value=time.time() - bridge.TICKET_TTL - 1):
            self.prepared()
        self.assert_code('request_expired', lambda: bridge.cancel(self.request))

    def test_existing_output_is_preserved_before_any_provider_operation(self):
        self.prepared()
        self.output.write_bytes(b'Existing user image')
        with patch.object(bridge, '_executable', side_effect=AssertionError('Provider must not start')):
            self.assert_code('destination_exists', lambda: self.generate(FakeRpc()))
        self.assertEqual(self.output.read_bytes(), b'Existing user image')

    def test_symlink_ticket_and_output_are_not_followed(self):
        self.prepared()
        symlink = self.root / 'linked.json'
        symlink.symlink_to(self.request)
        self.assert_code('unsafe_path', lambda: bridge.cancel(symlink))
        target = self.root / 'user.png'
        target.write_bytes(b'original')
        self.output.symlink_to(target)
        self.assert_code('unsafe_path', lambda: self.generate(FakeRpc()))
        self.assertEqual(target.read_bytes(), b'original')

    def test_success_uses_native_image_bytes_and_validates_the_output(self):
        self.prepared()
        rpc = FakeRpc()
        result = self.generate(rpc)
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(self.output.read_bytes(), png())
        self.assertEqual(result['artifact']['sha256'], bridge.digest(png()))
        self.assertEqual(result['artifact']['width'], 2)
        self.assertEqual(result['runtime']['reported_chat_model'], 'chat-default')
        self.assertEqual(result['runtime']['image_backend_model'], 'not_exposed')
        self.assertEqual(sum(c[0] == 'turn/start' for c in rpc.calls), 1)
        self.assertNotIn('/untrusted', json.dumps(result))
        self.assertNotIn('private@example', json.dumps(result))

    def test_generation_claim_prevents_all_later_replays(self):
        self.prepared()
        self.generate(FakeRpc())
        self.assert_code('request_consumed', lambda: self.generate(FakeRpc()))

    def test_concurrent_consumers_can_start_at_most_one_image_turn(self):
        self.prepared()
        barrier = threading.Barrier(2)
        clients = [FakeRpc(), FakeRpc()]
        for rpc in clients:
            original = rpc.request
            def request(method, params, timeout=60, original=original):
                result = original(method, params, timeout)
                if method == 'thread/start':
                    barrier.wait(timeout=5)
                return result
            rpc.request = request
        def run(index):
            try:
                return bridge.generate(self.request, bridge.ROUTE, self.root / ('image-%s.png' % index), True,
                                       rpc_factory=lambda *a, **k: clients[index])['status']
            except bridge.BridgeError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertCountEqual(results, ['generated', 'request_consumed'])
        self.assertEqual(sum(c[0] == 'turn/start' for rpc in clients for c in rpc.calls), 1)

    def test_prose_cannot_substitute_for_an_image_and_failure_is_consumed(self):
        self.prepared()
        rpc = FakeRpc([event('item/completed', {'type': 'agentMessage', 'id': 'text', 'text': 'Here is your image'}), event('turn/completed')])
        self.assert_code('native_image_missing', lambda: self.generate(rpc))
        self.assertFalse(self.output.exists())
        self.assert_code('request_consumed', lambda: self.generate(FakeRpc()))
        self.assertEqual(sum(c[0] == 'turn/start' for c in rpc.calls), 1)

    def test_unrelated_thread_or_turn_cannot_supply_an_image(self):
        self.prepared()
        rpc = FakeRpc([event('item/completed', image_item(), thread='other-thread'),
                       event('item/completed', image_item(), turn='other-turn'), event('turn/completed')])
        self.assert_code('native_image_missing', lambda: self.generate(rpc))
        self.assertFalse(self.output.exists())

    def test_completed_turn_can_supply_the_matching_native_item(self):
        self.prepared()
        complete = event('turn/completed')
        complete['params']['turn']['items'] = [image_item()]
        self.assertEqual(self.generate(FakeRpc([complete]))['status'], 'generated')

    def test_duplicate_publication_of_one_item_is_not_two_generations(self):
        self.prepared()
        complete = event('turn/completed')
        complete['params']['turn']['items'] = [image_item()]
        result = self.generate(FakeRpc([event('item/completed', image_item()), complete]))
        self.assertEqual(result['status'], 'generated')

    def test_multiple_native_image_items_are_not_silently_accepted(self):
        self.prepared()
        rpc = FakeRpc([event('item/completed', image_item()),
                       event('item/completed', image_item(identity='second-image')), event('turn/completed')])
        self.assert_code('unexpected_image_count', lambda: self.generate(rpc))
        self.assertFalse(self.output.exists())

    def test_failed_native_image_is_not_accepted_or_replayed(self):
        self.prepared()
        bad = image_item()
        bad.update(status='failed', result='')
        self.assert_code('native_generation_failed', lambda: self.generate(FakeRpc([event('item/completed', bad)])))
        self.assert_code('request_consumed', lambda: self.generate(FakeRpc()))

    def test_failed_turn_does_not_publish_a_completed_image(self):
        self.prepared()
        rpc = FakeRpc([event('item/completed', image_item()), event('turn/completed', status='failed')])
        self.assert_code('native_turn_failed', lambda: self.generate(rpc))
        self.assertFalse(self.output.exists())

    def test_unexpected_tool_is_rejected_and_interrupted(self):
        self.prepared()
        rpc = FakeRpc([event('item/started', {'type': 'commandExecution', 'id': 'command'})])
        self.assert_code('unexpected_tool', lambda: self.generate(rpc))
        self.assertTrue(any(c[0] == 'turn/interrupt' for c in rpc.calls))
        self.assertFalse(self.output.exists())

    def test_declined_approval_or_client_tool_is_not_hidden(self):
        self.prepared()
        rpc = FakeRpc([{'method': 'client/serverRequestDeclined', 'params': {'requestMethod': 'item/tool/call'}}])
        self.assert_code('unexpected_approval_or_tool', lambda: self.generate(rpc))
        self.assertFalse(self.output.exists())

    def test_timeout_consumes_request_and_interrupts_without_retry(self):
        self.prepared()
        rpc = FakeRpc([])
        with self.assertRaises(TimeoutError):
            self.generate(rpc)
        self.assertTrue(any(c[0] == 'turn/interrupt' for c in rpc.calls))
        self.assert_code('request_consumed', lambda: self.generate(FakeRpc()))

    def test_ineligible_configured_model_stays_unchanged_without_inference(self):
        self.prepared()
        rpc = FakeRpc()
        rpc.models['data'][0]['inputModalities'] = ['text']
        self.assert_code('configured_model_ineligible', lambda: self.generate(rpc))
        self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))
        thread = next(c[1] for c in rpc.calls if c[0] == 'thread/start')
        self.assertNotIn('model', thread)
        self.assertNotIn('model_reasoning_effort', thread['config'])
        self.assertEqual(bridge.cancel(self.request)['status'], 'cancelled')

    def test_unknown_configured_default_reports_real_coordinator_choices(self):
        rpc = FakeRpc()
        rpc.start['model'] = 'unknown-configured-default'
        with self.assertRaises(bridge.BridgeError) as raised:
            bridge.probe(rpc_factory=lambda *a, **k: rpc)
        self.assertEqual(raised.exception.code, 'configured_model_ineligible')
        options = raised.exception.details['eligible_coordinator_models']
        self.assertEqual(options[0]['model'], 'chat-default')
        self.assertEqual(options[0]['supported_efforts'], ['low', 'medium'])
        self.assertEqual(options[0]['role'], 'chat_coordinator_not_image_backend')
        self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))

    def test_explicit_probe_pair_uses_only_supported_native_controls(self):
        rpc = FakeRpc()
        result = bridge.probe(model='chat-default', effort='medium', rpc_factory=lambda *a, **k: rpc)
        self.assertEqual(result['reported_chat_model'], 'chat-default')
        self.assertEqual(result['reported_effort'], 'medium')
        thread = next(c[1] for c in rpc.calls if c[0] == 'thread/start')
        self.assertEqual(thread['model'], 'chat-default')
        self.assertEqual(thread['config']['model_reasoning_effort'], 'medium')
        self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))

    def test_hidden_model_is_not_suggested_but_exact_eligible_selection_is_preserved(self):
        rpc = FakeRpc()
        hidden = dict(rpc.models['data'][0], id='reserved-review', model='reserved-review', hidden=True)
        rpc.models['data'].append(hidden)
        rpc.start['model'] = 'unknown-default'
        with self.assertRaises(bridge.BridgeError) as raised:
            bridge.probe(rpc_factory=lambda *a, **k: rpc)
        self.assertEqual([m['model'] for m in raised.exception.details['eligible_coordinator_models']], ['chat-default'])
        rpc.start['model'] = 'reserved-review'
        result = bridge.probe(model='reserved-review', effort='medium', rpc_factory=lambda *a, **k: rpc)
        self.assertEqual(result['reported_chat_model'], 'reserved-review')
        self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))

    def test_foreign_model_or_effort_is_rejected_before_native_thread(self):
        for model, effort, code in [('invented-model', 'medium', 'requested_model_ineligible'),
                                    ('chat-default', 'FOREIGN_HIGH', 'requested_effort_unsupported')]:
            rpc = FakeRpc()
            self.assert_code(code, lambda: bridge.probe(model=model, effort=effort, rpc_factory=lambda *a, **k: rpc))
            self.assertFalse(any(c[0] in ('thread/start', 'turn/start') for c in rpc.calls))

    def test_request_binds_selected_pair_and_rejects_later_tampering(self):
        result = bridge.prepare('A cat', self.request, 'chat-default', 'medium')
        self.assertEqual(result['bound_coordinator_settings'], {'model': 'chat-default', 'effort': 'medium'})
        rpc = FakeRpc()
        generated = self.generate(rpc)
        self.assertEqual(generated['bound_coordinator_settings'], result['bound_coordinator_settings'])
        thread = next(c[1] for c in rpc.calls if c[0] == 'thread/start')
        self.assertEqual(thread['model'], 'chat-default')
        self.assertEqual(thread['config']['model_reasoning_effort'], 'medium')
        changed = json.loads(self.request.read_text())
        changed['settings']['model'] = 'different-model'
        self.request.write_text(json.dumps(changed))
        self.assert_code('request_changed', lambda: bridge.cancel(self.request))

    def test_native_pair_mismatch_is_rejected_before_image_inference(self):
        bridge.prepare('A cat', self.request, 'chat-default', 'low')
        rpc = FakeRpc()
        self.assert_code('native_settings_mismatch', lambda: self.generate(rpc))
        self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))
        self.assertEqual(bridge.cancel(self.request)['status'], 'cancelled')

    def test_native_prerequisites_fail_before_any_generation(self):
        for variant, code in [('capability', 'native_image_unavailable'), ('auth', 'authentication_required'), ('free', 'account_not_eligible')]:
            with self.subTest(variant=variant):
                rpc = FakeRpc()
                if variant == 'capability':
                    rpc.caps['namespaceTools'] = False
                elif variant == 'auth':
                    rpc.account['account'] = None
                else:
                    rpc.account['account']['planType'] = 'free'
                self.assert_code(code, lambda: bridge.probe(rpc_factory=lambda *a, **k: rpc))
                self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))

    def test_current_native_schema_can_omit_namespace_tools_without_claiming_it_true(self):
        rpc = FakeRpc()
        del rpc.caps['namespaceTools']
        with patch.object(bridge, '_read_version', return_value='0.169.0-alpha.11.1'):
            result = bridge.probe(rpc_factory=lambda *a, **k: rpc)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['provider_capabilities']['namespace_tools'], 'not_exposed')
        thread = next(c[1] for c in rpc.calls if c[0] == 'thread/start')
        self.assertTrue(thread['config']['features.image_generation'])
        self.assertTrue(thread['config']['features.imagegenext'])
        self.assertFalse(thread['config']['features.omit_app_server_notification_media'])
        self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))

    def test_probe_is_metadata_only_and_disables_each_configured_mcp(self):
        rpc = FakeRpc()
        result = bridge.probe(rpc_factory=lambda *a, **k: rpc)
        self.assertEqual(result['status'], 'available')
        self.assertFalse(result['generation_authorized'])
        self.assertFalse(result['artifact_generation_verified'])
        self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))
        thread = next(c[1] for c in rpc.calls if c[0] == 'thread/start')
        self.assertTrue(thread['ephemeral'])
        self.assertEqual(thread['sandbox'], 'read-only')
        self.assertEqual(thread['config']['mcp_servers.chrome-devtools.enabled'], False)
        self.assertEqual(thread['config']['mcp_servers.server"quoted.enabled'], False)
        self.assertFalse(thread['config']['features.shell_tool'])
        self.assertEqual(thread['config']['project_doc_max_bytes'], 0)
        self.assertNotIn('features.imagegenext', thread['config'])

    def test_malformed_mcp_metadata_fails_closed_before_thread(self):
        rpc = FakeRpc()
        rpc.mcp = {'data': [{'noName': True}]}
        self.assert_code('mcp_status_invalid', lambda: bridge.probe(rpc_factory=lambda *a, **k: rpc))
        self.assertFalse(any(c[0] in ('thread/start', 'turn/start') for c in rpc.calls))

    def test_unsupported_dotted_mcp_name_fails_before_thread_or_generation(self):
        rpc = FakeRpc()
        rpc.mcp['data'][0]['name'] = 'server.with.dots'
        self.assert_code('mcp_name_unsupported', lambda: bridge.probe(rpc_factory=lambda *a, **k: rpc))
        self.assertFalse(any(c[0] in ('thread/start', 'turn/start') for c in rpc.calls))

    def test_exposed_worker_mcp_tool_fails_isolation_before_generation(self):
        rpc = FakeRpc()
        original = rpc.request
        def request(method, params, timeout=60):
            if method == 'mcpServerStatus/list' and params.get('threadId'):
                return {'data': [{'name': 'still-active', 'tools': {'tool': {}}}], 'nextCursor': None}
            return original(method, params, timeout)
        rpc.request = request
        self.assert_code('mcp_isolation_unverified', lambda: bridge.probe(rpc_factory=lambda *a, **k: rpc))
        self.assertFalse(any(c[0] == 'turn/start' for c in rpc.calls))

    def test_evidence_records_native_matching_identity_without_payload_or_reasoning(self):
        self.prepared()
        evidence = self.root / 'native-proof.json'
        result = self.generate(FakeRpc(), evidence_file=evidence)
        saved = json.loads(evidence.read_text())
        self.assertEqual(saved['thread_start']['thread_id'], 'thread-1')
        native = next(e for e in saved['native_events'] if e['event'] == 'native_image_item')
        self.assertEqual(native['turn_id'], 'turn-1')
        self.assertEqual(native['item_id'], 'image-1')
        self.assertEqual(saved['decoded_artifact']['sha256'], result['artifact']['sha256'])
        self.assertNotIn(image_item()['result'], evidence.read_text())
        self.assertNotIn('Private prompt detail', evidence.read_text())
        if os.name == 'posix':
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_missing_image_retains_bounded_public_failure_evidence_without_reasoning_or_auth(self):
        self.prepared()
        evidence = self.root / 'failed-native-proof.json'
        public = 'The native image tool is unavailable in this worker. ' + 'ordinary words ' * 1000
        rpc = FakeRpc([
            {'method': 'legacy/event', 'params': {'auth': 'DO_NOT_RETAIN_AUTH', 'private': 'DO_NOT_RETAIN_PRIVATE'}},
            event('item/completed', {'type': 'reasoning', 'id': 'reasoning-1',
                                     'text': 'DO_NOT_RETAIN_REASONING', 'summary': ['DO_NOT_RETAIN_SUMMARY']}),
            event('item/completed', {'type': 'agentMessage', 'id': 'final-1', 'phase': 'final_answer', 'text': public}),
            event('turn/completed')])
        self.assert_code('native_image_missing', lambda: self.generate(rpc, evidence_file=evidence))
        saved = json.loads(evidence.read_text())
        self.assertEqual(saved['status'], 'error')
        self.assertEqual(saved['failure']['code'], 'native_image_missing')
        self.assertTrue(saved['request_claimed'])
        self.assertEqual(saved['thread_start']['thread_id'], 'thread-1')
        messages = [e for e in saved['native_events'] if e['event'] == 'public_agent_message']
        self.assertTrue(messages[0]['text'].startswith('The native image tool is unavailable'))
        self.assertLessEqual(sum(len(e['text']) for e in messages), bridge.MAX_PUBLIC_WORKER_TEXT)
        self.assertTrue(messages[0]['truncated'])
        self.assertTrue(any(e.get('method') == 'legacy/event' for e in saved['native_events']))
        self.assertTrue(any(e.get('type') == 'reasoning' for e in saved['native_events']))
        self.assertTrue(any(e.get('event') == 'turn/completed' and e['status'] == 'completed' for e in saved['native_events']))
        self.assertFalse(self.output.exists())
        for forbidden in ['DO_NOT_RETAIN_AUTH', 'DO_NOT_RETAIN_PRIVATE', 'DO_NOT_RETAIN_REASONING', 'DO_NOT_RETAIN_SUMMARY']:
            self.assertNotIn(forbidden, evidence.read_text())
        self.assert_code('request_consumed', lambda: self.generate(FakeRpc()))

    def test_public_failure_text_does_not_retain_image_payload_or_credential_shapes(self):
        self.prepared()
        evidence = self.root / 'redacted-native-proof.json'
        encoded = image_item()['result']
        public = 'No tool. data:image/png;base64,' + encoded + ' sk-privatecredential123456789 Bearer token123456789012345'
        rpc = FakeRpc([event('item/completed', {'type': 'agentMessage', 'id': 'final', 'text': public}), event('turn/completed')])
        self.assert_code('native_image_missing', lambda: self.generate(rpc, evidence_file=evidence))
        text = evidence.read_text()
        self.assertNotIn(encoded, text)
        self.assertNotIn('sk-privatecredential', text)
        self.assertNotIn('token123456789012345', text)
        self.assertIn('omitted', text)

    def test_corrupt_truncated_or_text_payload_is_rejected_independently(self):
        candidates = [b'<svg>fake</svg>', png()[:-3], png()[:45] + b'x' + png()[46:]]
        for data in candidates:
            with self.subTest(length=len(data)):
                self.assert_code('artifact_invalid', lambda: bridge.validate_png(data))
        item = image_item()
        item['result'] = '/some/file.png'
        self.assert_code('artifact_invalid', lambda: bridge.image_bytes(item))

    def test_current_file_id_item_reads_only_its_native_thread_generated_output(self):
        self.prepared()
        home = (self.root / 'native-home').resolve()
        generated = home / 'generated_images' / 'thread-1' / 'native-call.png'
        generated.parent.mkdir(parents=True)
        generated.write_bytes(png())
        item = {'type': 'imageGeneration', 'id': 'image-file', 'status': 'completed',
                'fileId': 'native-attachment-id', 'result': '', 'savedPath': str(generated)}
        rpc = FakeRpc([event('item/completed', item), event('turn/completed')])
        with patch.dict(os.environ, {'CODEX_HOME': str(home)}):
            result = self.generate(rpc)
        self.assertEqual(result['status'], 'generated')
        self.assertEqual(result['artifact']['payload_source'], 'matching_native_generated_image_file')
        self.assertEqual(self.output.read_bytes(), png())

    def test_native_file_attachment_cannot_read_another_thread_or_user_file(self):
        home = (self.root / 'native-home').resolve()
        user_image = home / 'generated_images' / 'other-thread' / 'existing.png'
        user_image.parent.mkdir(parents=True)
        user_image.write_bytes(png())
        item = {'type': 'imageGeneration', 'id': 'image-file', 'status': 'completed',
                'fileId': 'native-attachment-id', 'savedPath': str(user_image)}
        self.assert_code('artifact_unsafe_path', lambda: bridge.image_bytes(item, 'thread-1', str(home)))
        item['savedPath'] = 'https://example.invalid/image.png'
        self.assert_code('artifact_unsafe_path', lambda: bridge.image_bytes(item, 'thread-1', str(home)))

    def test_native_file_attachment_symlink_is_never_followed(self):
        home = (self.root / 'native-home').resolve()
        generated = home / 'generated_images' / 'thread-1' / 'native.png'
        generated.parent.mkdir(parents=True)
        user_image = self.root / 'private-user.png'
        user_image.write_bytes(png())
        generated.symlink_to(user_image)
        item = {'type': 'imageGeneration', 'id': 'image-file', 'status': 'completed',
                'fileId': 'native-attachment-id', 'savedPath': str(generated)}
        self.assert_code('artifact_unsafe_path', lambda: bridge.image_bytes(item, 'thread-1', str(home)))

    def test_saved_path_without_native_file_identity_is_not_an_artifact(self):
        item = {'type': 'imageGeneration', 'id': 'not-an-image', 'status': 'completed',
                'result': '', 'savedPath': str(self.root / 'some-file.png')}
        self.assert_code('artifact_invalid', lambda: bridge.image_bytes(item, 'thread-1', str(self.root)))

    def test_png_compressed_bomb_or_invalid_raster_cannot_pass(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        header = struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)
        for raster in [b'\0' * 100000, b'\xff' * 5]:
            data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raster)) + chunk(b'IEND', b'')
            self.assert_code('artifact_invalid', lambda: bridge.validate_png(data))

    def test_rpc_wire_reader_stops_at_explicit_line_bound(self):
        client = bridge.BoundedRpcClient(['fixture'])
        client.process = type('Process', (), {'stdout': io.StringIO('x' * 101 + '\n')})()
        with patch.object(bridge, 'MAX_RPC_LINE', 100):
            client._read_stdout()
        self.assertIn('exceeded', client._terminal)

    def test_invalid_timeout_is_rejected(self):
        for value in [0, float('inf'), float('nan'), 601]:
            self.assert_code('invalid_timeout', lambda: bridge.checked_timeout(value))


if __name__ == '__main__':
    unittest.main()
