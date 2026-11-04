#!/usr/bin/env python3
"""Regrade the public pilot answers without contacting a model or service."""
import hashlib
import json
from pathlib import Path

from score_outputs import grade


def main():
    root = Path(__file__).resolve().parent
    results = json.loads((root / 'results.json').read_text())
    for name in ('cases.json', 'score_outputs.py'):
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == results['protocol']['sources'][name], name
    cases = {case['id']: case for case in json.loads((root / 'cases.json').read_text())}
    checked = failed = 0
    for row in results['results']:
        passed = []
        for attempt in row['attempts']:
            actual = grade(cases[row['caseId']], attempt['response'])
            assert actual == attempt['grade'], (row['caseId'], attempt['attempt'])
            status = 'passed' if actual['passed'] else 'failed'
            assert attempt['validation']['status'] == status
            assert attempt['validation']['feedback'] == sorted(name for name, ok in actual['checks'].items() if not ok)
            passed.append(actual['passed'])
            checked += 1
            failed += not actual['passed']
        assert row['firstPassCorrect'] == passed[0]
        assert row['accepted'] == passed[-1]
        assert not any(passed[:-1]), 'No extra attempt should follow a passing answer'
    assert checked == results['independentAudit']['candidateAnswersRegraded']
    print(json.dumps({'passed': True, 'recordedCandidatesRegraded': checked,
                      'failedCandidatesBlocked': failed}, indent=2))


if __name__ == '__main__':
    main()
