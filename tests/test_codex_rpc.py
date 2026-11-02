"""Offline protocol tests. No Codex executable or provider is invoked."""
import concurrent.futures
import json
import os
import signal
import sys
import threading
import time
import unittest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from codex_rpc import RpcClient, RpcClosedError, RpcError, RpcTimeoutError


FAKE_SERVER = r'''
import json, os, signal, subprocess, sys, threading, time
lock = threading.Lock()
def send(value):
    with lock:
        print(json.dumps(value), flush=True)
waiting = {}
for line in sys.stdin:
    value = json.loads(line)
    if 'method' not in value:
        original = waiting.pop(value['id'])
        send({'id': original, 'result': value})
        continue
    method = value['method']
    if 'id' not in value:
        send({'method':'saw-notification','params':value.get('params')})
        continue
    request_id = value['id']
    if method == 'event-first':
        send({'method':'before','params':{'value':'คะ'}})
        send({'method':'unrelated','params':{}})
        send({'id':request_id,'result':{'ok':True}})
    elif method == 'echo':
        send({'id':request_id,'result':value.get('params')})
    elif method == 'slow':
        threading.Timer(0.15, lambda rid=request_id: send({'id':rid,'result':'slow'})).start()
    elif method == 'never':
        continue
    elif method == 'error':
        send({'id':request_id,'error':{'code':-32602,'message':'SECRET-RAW-CONFIG'}})
    elif method == 'eof':
        sys.exit(0)
    elif method == 'invalid-json':
        print('SECRET-MALFORMED', flush=True)
    elif method == 'stderr':
        sys.stderr.write('x'*70000)
        sys.stderr.flush()
        send({'id':request_id,'result':True})
    elif method == 'server-request':
        server_id = 'server-' + str(request_id)
        waiting[server_id] = request_id
        send({'id':server_id,'method':value['params']['method'],'params':{'secret':'PRIVATE'}})
    elif method == 'spawn-child':
        code = 'import signal,time; signal.signal(signal.SIGINT,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'
        child = subprocess.Popen([sys.executable,'-u','-c',code])
        send({'id':request_id,'result':{'child_pid':child.pid}})
'''


def client():
    return RpcClient([sys.executable, '-u', '-c', FAKE_SERVER])


class RpcTests(unittest.TestCase):
    def test_event_before_response_preserved_and_unrelated_event_retained(self):
        with client() as rpc:
            self.assertEqual(rpc.request('event-first', {}), {'ok': True})
            first = rpc.wait_notification(lambda n: n['method'] == 'before')
            self.assertEqual(first['params']['value'], 'คะ')
            second = rpc.wait_notification(lambda n: n['method'] == 'unrelated')
            self.assertEqual(second['params'], {})

    def test_concurrent_out_of_order_responses_are_matched_by_id(self):
        with client() as rpc, concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(rpc.request, 'slow', {})
            time.sleep(0.02)
            fast = pool.submit(rpc.request, 'echo', {'value': 'fast'})
            self.assertEqual(fast.result(timeout=2), {'value': 'fast'})
            self.assertEqual(slow.result(timeout=2), 'slow')

    def test_rpc_error_does_not_echo_server_payload(self):
        with client() as rpc:
            with self.assertRaises(RpcError) as raised:
                rpc.request('error', {})
            self.assertEqual(raised.exception.code, -32602)
            self.assertNotIn('SECRET', str(raised.exception))
            self.assertEqual(rpc.request('echo', 7), 7)

    def test_eof_unblocks_response_wait(self):
        with client() as rpc:
            with self.assertRaises(RpcClosedError):
                rpc.request('eof', {}, timeout=2)

    def test_malformed_output_fails_without_echoing_raw_input(self):
        with client() as rpc:
            with self.assertRaises(RpcClosedError) as raised:
                rpc.request('invalid-json', {}, timeout=2)
            self.assertNotIn('SECRET', str(raised.exception))

    def test_response_timeout_does_not_break_later_requests(self):
        with client() as rpc:
            with self.assertRaises(RpcTimeoutError):
                rpc.request('never', {}, timeout=0.03)
            self.assertEqual(rpc.request('echo', {'next': True}), {'next': True})

    def test_notification_timeout_and_notify(self):
        with client() as rpc:
            with self.assertRaises(RpcTimeoutError):
                rpc.wait_notification(lambda n: False, timeout=0.02)
            rpc.notify('initialized', {'value': 'notification'})
            notice = rpc.wait_notification(lambda n: n['method'] == 'saw-notification')
            self.assertEqual(notice['params']['value'], 'notification')

    def test_server_requests_declined_without_hanging(self):
        expected = {
            'item/commandExecution/requestApproval': {'decision': 'decline'},
            'item/fileChange/requestApproval': {'decision': 'decline'},
            'item/permissions/requestApproval': {'permissions': {}, 'scope': 'turn'},
            'item/tool/requestUserInput': {'answers': {}},
        }
        with client() as rpc:
            for method, result in expected.items():
                reply = rpc.request('server-request', {'method': method})
                self.assertEqual(reply['result'], result)
            unsupported = rpc.request('server-request', {'method': 'unknown/serverRequest'})
            self.assertEqual(unsupported['error']['code'], -32601)
            notice = rpc.wait_notification(lambda n: n['method'] == 'client/serverRequestDeclined')
            self.assertNotIn('PRIVATE', json.dumps(notice))

    def test_stderr_tail_is_bounded(self):
        with client() as rpc:
            self.assertTrue(rpc.request('stderr', {}))
            deadline = time.monotonic() + 2
            while len(rpc.stderr_tail) < rpc.STDERR_LIMIT and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(rpc.stderr_tail), rpc.STDERR_LIMIT)

    def test_close_is_bounded_idempotent_and_unblocks_waiters(self):
        rpc = client().__enter__()
        process = rpc.process
        observed = []
        def wait():
            try:
                rpc.wait_notification(lambda n: False, timeout=10)
            except RpcClosedError:
                observed.append('closed')
        thread = threading.Thread(target=wait)
        thread.start()
        started = time.monotonic()
        rpc.close()
        rpc.close()
        thread.join(timeout=2)
        self.assertEqual(observed, ['closed'])
        self.assertIsNotNone(process.poll())
        self.assertLess(time.monotonic() - started, 3)

    @unittest.skipUnless(os.name == 'posix', 'Process-group cleanup is POSIX-specific')
    def test_close_kills_descendants_in_its_own_process_group(self):
        rpc = client().__enter__()
        child_pid = rpc.request('spawn-child', {})['child_pid']
        group_id = rpc.process.pid
        self.assertEqual(os.getpgid(child_pid), group_id)
        # Give the child time to install its ignored-signal handlers.
        time.sleep(0.08)
        rpc.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            # Linux can retain a defunct orphan briefly; a zombie is no longer
            # executing and cannot keep the model process alive.
            stat = '/proc/{}/stat'.format(child_pid)
            if os.path.exists(stat):
                with open(stat) as stream:
                    self.assertEqual(stream.read().split()[2], 'Z')
            else:
                self.fail('Descendant remains alive after process-group cleanup')

    def test_unentered_client_rejects_use(self):
        rpc = client()
        with self.assertRaises(RpcClosedError):
            rpc.request('echo', {})
        rpc.close()

    def test_invalid_deadlines_rejected(self):
        for value in [float('nan'), float('inf'), -1, None]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    RpcClient._deadline(value)


if __name__ == '__main__':
    unittest.main()
