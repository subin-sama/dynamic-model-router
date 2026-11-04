"""Independent checks, checker failures, and local command boundaries."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from answer_validation import (AnswerValidationError, command_validator,
                               parse_validator_command, validate_answer,
                               validate_max_repair_routes)


class AnswerValidationTests(unittest.TestCase):
    def test_unavailable_is_not_a_pass_and_pass_fail_are_separate(self):
        self.assertEqual(validate_answer(None, 'task', 'answer')['status'], 'unavailable')
        received = []
        def checker(task, answer):
            received.append((task, answer))
            return {'passed': False, 'feedback': ['wrong count']}
        self.assertEqual(validate_answer(checker, 'task', 'candidate'),
                         {'status': 'failed', 'feedback': ['wrong count']})
        self.assertEqual(received, [('task', 'candidate')])
        self.assertEqual(validate_answer(lambda *_: {'passed': True}, '', ''),
                         {'status': 'passed', 'feedback': []})
        self.assertEqual(validate_answer(lambda *_: {'passed': True, 'feedback': ''}, '', ''),
                         {'status': 'passed', 'feedback': []})

    def test_checker_error_does_not_become_answer_failure_or_expose_private_data(self):
        def broken(*_):
            raise ValueError('SECRET-CHECKER-DETAIL')
        result = validate_answer(broken, 'task', 'answer')
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('SECRET', json.dumps(result))
        for malformed in (None, {'passed': 'yes'}, {'passed': 1},
                          {'passed': True, 'extra': 'ignored?'},
                          {'passed': False, 'feedback': ['']},
                          {'passed': False, 'feedback': 'x' * 2001}):
            with self.subTest(malformed=malformed):
                self.assertEqual(validate_answer(lambda *_: malformed, '', '')['status'], 'error')

    def test_configuration_rejects_invalid_limits_and_argument_arrays(self):
        for value in (-1, 3, True, '2', None):
            with self.subTest(value=value), self.assertRaises(AnswerValidationError):
                validate_max_repair_routes(value)
        self.assertEqual(validate_max_repair_routes(2), 2)
        for text in ('null', '"python"', '[]', '[1]', '[""]', '["python","\\u0000"]'):
            with self.subTest(text=text), self.assertRaises(AnswerValidationError):
                parse_validator_command(text)
        for timeout in (0, -1, True, float('nan'), 301):
            with self.subTest(timeout=timeout), self.assertRaises(AnswerValidationError):
                command_validator([sys.executable], timeout)

    def test_external_checker_receives_literal_arguments_and_json_input(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'must-not-exist'
            literal = '$(touch ' + str(marker) + ')'
            code = ('import json,sys; p=json.load(sys.stdin); '
                    'print(json.dumps({"passed":p=={"task":"t","answer":"a"} '
                    'and sys.argv[1]=='+repr(literal)+'}))')
            checker = command_validator([sys.executable, '-c', code, literal])
            self.assertEqual(validate_answer(checker, 't', 'a')['status'], 'passed')
            self.assertFalse(marker.exists())

    def test_nonzero_malformed_or_duplicate_checker_output_stops_as_error(self):
        programs = [
            'import sys; print("SECRET",file=sys.stderr); sys.exit(1)',
            'print("not json")',
            'print(\'{"passed":true,"passed":false}\')',
        ]
        for code in programs:
            with self.subTest(code=code):
                result = validate_answer(command_validator([sys.executable, '-c', code]), 't', 'a')
                self.assertEqual(result['status'], 'error')
                self.assertNotIn('SECRET', json.dumps(result))

    def test_failed_answer_is_a_successful_checker_process_not_an_infrastructure_error(self):
        code = 'import json,sys; json.load(sys.stdin); print(json.dumps({"passed":False,"feedback":["valid_rows"]}))'
        result = validate_answer(command_validator([sys.executable, '-c', code]), 't', 'a')
        self.assertEqual(result, {'status': 'failed', 'feedback': ['valid_rows']})

    def test_timeout_and_excessive_output_are_bounded_checker_errors(self):
        programs = [
            'import time; time.sleep(20)',
            'import sys; sys.stdout.write("x"*1000000); sys.stdout.flush()',
            'import sys; sys.stderr.write("x"*1000000); sys.stderr.flush()',
        ]
        for code in programs:
            started = time.monotonic()
            result = validate_answer(command_validator([sys.executable, '-c', code], timeout=.3), 't', 'a')
            self.assertEqual(result['status'], 'error')
            self.assertLess(time.monotonic() - started, 3)

    def test_oversized_input_does_not_start_a_checker(self):
        checker = command_validator(['/no/such/checker'])
        result = validate_answer(checker, 'x' * (1024 * 1024), 'a')
        self.assertEqual(result['status'], 'error')


if __name__ == '__main__':
    unittest.main()
