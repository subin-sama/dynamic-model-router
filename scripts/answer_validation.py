"""Answer-checking boundary shared by the read-only routing clients.

A checker is supplied by the caller, never selected or executed by model output.
It is responsible for the actual task acceptance criteria; this module does not
turn a missing checker or a confidence statement into an independent proof.
"""
import json
import math
import os
import signal
import subprocess
import threading
import time


MAX_INPUT_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 16384
MAX_FEEDBACK_CHARS = 2000


class AnswerValidationError(ValueError):
    pass


def validate_max_repair_routes(value):
    if type(value) is not int or not 0 <= value <= 2:
        raise AnswerValidationError('max_repair_routes must be an integer from 0 to 2')
    return value


def parse_validator_command(text):
    try:
        command = json.loads(text)
    except (TypeError, ValueError):
        raise AnswerValidationError('Validator command must be a JSON argument array') from None
    if (not isinstance(command, list) or not command or len(command) > 128
            or any(not isinstance(arg, str) or '\x00' in arg for arg in command)
            or not command[0] or sum(len(arg) for arg in command) > 32768):
        raise AnswerValidationError('Validator command must be a nonempty JSON argument array')
    return list(command)


def _feedback(value, passed):
    if value is None or (isinstance(value, str) and not value.strip()):
        return [] if passed else ['The configured answer check did not pass.']
    values = [value] if isinstance(value, str) else value
    if (not isinstance(values, list) or len(values) > 16
            or any(not isinstance(item, str) or not item.strip() for item in values)):
        raise AnswerValidationError('Invalid checker feedback')
    values = [item.strip() for item in values]
    if sum(len(item) for item in values) > MAX_FEEDBACK_CHARS:
        raise AnswerValidationError('Checker feedback exceeds its size limit')
    if any(any(ord(char) < 32 and char not in '\n\t' for char in item) for item in values):
        raise AnswerValidationError('Invalid checker feedback')
    return values if values or passed else ['The configured answer check did not pass.']


def validate_answer(validator, task, answer):
    """Normalize a caller's checker without exposing private exception details."""
    if validator is None:
        return {'status': 'unavailable', 'feedback': ['No independent answer checker was configured.']}
    try:
        result = validator(task, answer)
        if (not isinstance(result, dict) or set(result) - {'passed', 'feedback'}
                or type(result.get('passed')) is not bool):
            raise AnswerValidationError('Invalid checker response')
        return {'status': 'passed' if result['passed'] else 'failed',
                'feedback': _feedback(result.get('feedback'), result['passed'])}
    except Exception:
        return {'status': 'error', 'feedback': ['The configured answer checker could not complete reliably.']}


def _terminate(process):
    """Stop only this checker and its owned process group, without raw errors."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            if os.name == 'posix':
                os.killpg(process.pid, sig)
            elif process.poll() is None:
                process.terminate() if sig == signal.SIGTERM else process.kill()
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        try:
            process.wait(timeout=.2)
        except subprocess.TimeoutExpired:
            pass


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AnswerValidationError('Duplicate checker response field')
        value[key] = item
    return value


def command_validator(command, timeout=10):
    """Make a trusted local checker callback; literal argv, bounded I/O, no shell.

    The command receives {task, answer} on stdin and must exit zero with one JSON
    object {passed: bool, feedback?: string | string[]}. Nonzero exits represent
    checker failure, not an answer failure. Local checkers run with the caller's
    permissions, outside the model's read-only tool sandbox.
    """
    command = parse_validator_command(json.dumps(command))
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise AnswerValidationError('Validator timeout must be finite and in (0, 300]')

    def check(task, answer):
        payload = json.dumps({'task': task, 'answer': answer}, ensure_ascii=False).encode('utf-8')
        if len(payload) > MAX_INPUT_BYTES:
            raise AnswerValidationError('Checker input exceeds its size limit')
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=(os.name == 'posix'))
        oversized = threading.Event()
        write_failed = threading.Event()
        captured = bytearray()

        def read(pipe, keep):
            count = 0
            try:
                while True:
                    block = pipe.read(4096)
                    if not block:
                        break
                    count += len(block)
                    if count > MAX_OUTPUT_BYTES:
                        oversized.set()
                        break
                    if keep:
                        captured.extend(block)
            finally:
                pipe.close()

        def write():
            try:
                process.stdin.write(payload)
            except (BrokenPipeError, OSError):
                write_failed.set()
            finally:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    write_failed.set()

        threads = [threading.Thread(target=read, args=(process.stdout, True), daemon=True),
                   threading.Thread(target=read, args=(process.stderr, False), daemon=True),
                   threading.Thread(target=write, daemon=True)]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + timeout
        timed_out = False
        try:
            while process.poll() is None:
                if oversized.is_set() or time.monotonic() >= deadline:
                    timed_out = time.monotonic() >= deadline
                    _terminate(process)
                    break
                try:
                    process.wait(timeout=min(.05, max(.001, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
            for thread in threads:
                thread.join(timeout=.1)
            if any(thread.is_alive() for thread in threads):
                _terminate(process)
                for thread in threads:
                    thread.join(timeout=.2)
            if timed_out or oversized.is_set() or write_failed.is_set() or any(thread.is_alive() for thread in threads) or process.returncode != 0:
                raise AnswerValidationError('The configured answer checker failed')
            return json.loads(bytes(captured).decode('utf-8'), object_pairs_hook=_unique_object)
        finally:
            if process.poll() is None or any(thread.is_alive() for thread in threads):
                _terminate(process)

    return check
