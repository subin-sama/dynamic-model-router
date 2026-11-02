"""Small, credential-agnostic stdio client for the Codex App Server protocol."""

import json
import math
import os
import signal
import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Optional, Sequence


class RpcError(RuntimeError):
    """The peer rejected a request; raw server text is not echoed automatically."""

    def __init__(self, method: str, error: Any):
        self.method = method
        self.error = error
        self.code = error.get('code') if isinstance(error, dict) else None
        super().__init__('RPC request failed: {} (code {})'.format(method, self.code))


class RpcClosedError(RuntimeError):
    """The transport is not running or its output closed."""


class RpcTimeoutError(TimeoutError):
    """A response or notification did not arrive before its deadline."""


class RpcClient:
    """Manage one App Server process; initialization is the caller's concern.

    Enter the context before using the transport. Concurrent requests are
    supported, but callers must serialize dependent protocol operations.
    Server-origin approval requests are denied rather than implicitly accepted.
    Unknown server requests receive a protocol error instead of hanging.
    """

    STDERR_LIMIT = 32768

    def __init__(self, argv: Sequence[str], *, cwd: Optional[str] = None):
        if not argv or isinstance(argv, (str, bytes)):
            raise ValueError('argv must be a nonempty argument sequence')
        self.argv = list(argv)
        self.cwd = cwd
        self.process = None
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._notifications = deque()
        self._responses = {}
        self._pending = set()
        self._next_id = 1
        self._terminal = None
        self._closing = False
        self._stderr_tail = ''
        self._threads = []

    @property
    def stderr_tail(self) -> str:
        """Bounded stderr, available to the caller but never printed here."""
        with self._condition:
            return self._stderr_tail

    def __enter__(self):
        if self.process is not None or self._closing:
            raise RuntimeError('RpcClient contexts cannot be restarted')
        self.process = subprocess.Popen(
            self.argv, cwd=self.cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            start_new_session=True,
        )
        for target in (self._read_stdout, self._read_stderr):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _send(self, message: Dict[str, Any]) -> None:
        with self._write_lock:
            if self.process is None or self._closing or self.process.stdin is None:
                raise RpcClosedError('RPC transport is not running')
            try:
                self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                raise RpcClosedError('RPC transport input closed') from None

    def _finish(self, message: str) -> None:
        with self._condition:
            if self._terminal is None:
                self._terminal = message
            self._condition.notify_all()

    def _read_stdout(self) -> None:
        try:
            for line in self.process.stdout:
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    self._finish('RPC peer emitted invalid JSON')
                    return
                if not isinstance(message, dict):
                    self._finish('RPC peer emitted an invalid message')
                    return
                if 'method' in message and 'id' in message:
                    self._decline_server_request(message)
                    continue
                with self._condition:
                    if 'id' in message:
                        # Timed-out/unsolicited replies have no consumer.
                        if message['id'] in self._pending:
                            self._responses[message['id']] = message
                    elif 'method' in message:
                        self._notifications.append(message)
                    self._condition.notify_all()
        except (OSError, ValueError):
            pass
        finally:
            self._finish('RPC peer closed its output')

    def _read_stderr(self) -> None:
        try:
            while True:
                chunk = self.process.stderr.read(4096)
                if not chunk:
                    break
                with self._condition:
                    self._stderr_tail = (self._stderr_tail + chunk)[-self.STDERR_LIMIT:]
        except (OSError, ValueError):
            pass

    def _decline_server_request(self, message: Dict[str, Any]) -> None:
        method = message.get('method')
        reply = {'id': message['id']}
        if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            reply['result'] = {'decision': 'decline'}
        elif method == 'item/permissions/requestApproval':
            reply['result'] = {'permissions': {}, 'scope': 'turn'}
        elif method == 'item/tool/requestUserInput':
            reply['result'] = {'answers': {}}
        elif method == 'item/tool/call':
            reply['result'] = {
                'success': False,
                'contentItems': [{'type': 'inputText', 'text': 'This client has no tool handler.'}],
            }
        else:
            reply['error'] = {'code': -32601, 'message': 'Server request is not supported by this client'}
        try:
            self._send(reply)
        except RpcClosedError:
            return
        # Do not retain the server's potentially sensitive request parameters.
        with self._condition:
            self._notifications.append({
                'method': 'client/serverRequestDeclined',
                'params': {'requestMethod': method},
            })
            self._condition.notify_all()

    @staticmethod
    def _deadline(timeout: float) -> float:
        if timeout is None or not math.isfinite(timeout) or timeout < 0:
            raise ValueError('timeout must be finite and nonnegative')
        return time.monotonic() + timeout

    def request(self, method: str, params: Any, timeout: float = 60) -> Any:
        deadline = self._deadline(timeout)
        with self._condition:
            if self.process is None or self._closing or self._terminal:
                raise RpcClosedError('RPC transport is not running')
            request_id = self._next_id
            self._next_id += 1
            self._pending.add(request_id)
        try:
            self._send({'id': request_id, 'method': method, 'params': params})
            with self._condition:
                while request_id not in self._responses:
                    if self._terminal or self._closing:
                        raise RpcClosedError(self._terminal or 'RPC transport closed')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RpcTimeoutError('Timed out waiting for RPC response: ' + method)
                    self._condition.wait(remaining)
                response = self._responses.pop(request_id)
            if 'error' in response:
                raise RpcError(method, response['error'])
            if 'result' not in response:
                raise RpcError(method, {'code': None})
            return response['result']
        finally:
            with self._condition:
                self._pending.discard(request_id)
                self._responses.pop(request_id, None)

    def notify(self, method: str, params: Any) -> None:
        self._send({'method': method, 'params': params})

    def wait_notification(self, predicate: Callable[[Dict[str, Any]], bool], timeout: float = 60) -> Dict[str, Any]:
        deadline = self._deadline(timeout)
        with self._condition:
            while True:
                for index, message in enumerate(self._notifications):
                    if predicate(message):
                        del self._notifications[index]
                        return message
                if self._terminal or self._closing or self.process is None:
                    raise RpcClosedError(self._terminal or 'RPC transport is not running')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RpcTimeoutError('Timed out waiting for RPC notification')
                self._condition.wait(remaining)

    def _signal_group(self, sig: int) -> None:
        if self.process is None:
            return
        try:
            if os.name == 'posix':
                os.killpg(self.process.pid, sig)
            elif self.process.poll() is None:
                self.process.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._finish('RPC transport closed')
        process = self.process
        if process is None:
            return
        # Signal the group even if the server exited: a descendant can still
        # retain stdout or continue executing after its parent has gone away.
        if os.name == 'posix':
            for sig, grace in ((signal.SIGINT, 0.3), (signal.SIGTERM, 0.3), (signal.SIGKILL, 0.3)):
                self._signal_group(sig)
                try:
                    process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    continue
                # Remaining descendants get TERM/KILL on following iterations.
        elif process.poll() is None:
            # Windows stdlib cannot provide the POSIX process-group guarantee.
            # Terminate the direct server; a host needing strict descendant
            # cleanup on Windows should wrap it in a platform job object.
            process.terminate()
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)
        for thread in self._threads:
            thread.join(timeout=0.5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
