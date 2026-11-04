#!/usr/bin/env python3
"""Render caller-supplied routing evidence into a native inline HTML snapshot.

This component does not select models, verify runtime claims, register an
Antigravity artifact, or provide a live connection to either host.
"""

import argparse
import html
import json
import re
import sys
import uuid
from pathlib import Path
from string import Template


MAX_INPUT_BYTES = 16384
HOSTS = ('codex', 'antigravity')
STATUS_COLORS = {
    'recommended': ('blue', '#2563eb', '#60a5fa'),
    'requested': ('yellow', '#a86500', '#f4c44e'),
    'applied': ('purple', '#7c3aed', '#bc9bff'),
    'verified': ('green', '#15803d', '#6ed99c'),
    'unchanged': ('muted-foreground', '#626873', '#a4acb9'),
    'unverified': ('orange', '#b45309', '#ffad66'),
    'error': ('red', '#b91c1c', '#ff8686'),
}
DEFAULT_LABELS = {
    'routing': 'Routing', 'parent': 'Parent', 'worker': 'Worker',
    'external': 'External', 'model': 'Model', 'effort': 'Effort',
    'not_exposed': 'Not exposed', 'evidence': 'Evidence',
    'snapshot': 'Point-in-time receipt',
    'recommended': 'Recommended', 'requested': 'Requested',
    'applied': 'Applied', 'verified': 'Verified', 'unchanged': 'Unchanged',
    'unverified': 'Unverified', 'error': 'Error',
}
FIELDS = frozenset(('status', 'scope', 'model', 'effort', 'reason',
                    'evidence', 'labels'))
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / 'assets' / 'receipt.html'


class ReceiptError(ValueError):
    """Invalid or ambiguous receipt input."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptError('Duplicate receipt field')
        result[key] = value
    return result


def _text(value, field, limit, *, optional=False, multiline=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ReceiptError('Invalid ' + field)
    if value != value.strip():
        raise ReceiptError('Surrounding whitespace in ' + field)
    allowed = '\n\t' if multiline else ''
    if any((ord(c) < 32 and c not in allowed) or ord(c) == 127 for c in value):
        raise ReceiptError('Control characters in ' + field)
    return value


def validate_receipt(data):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ReceiptError('Expected a receipt object with supported fields')
    if not {'status', 'scope', 'model', 'effort'} <= set(data):
        raise ReceiptError('Receipt requires status, scope, model, and effort')
    status = data['status']
    if not isinstance(status, str) or status not in STATUS_COLORS:
        raise ReceiptError('Unsupported receipt status')
    scope = _text(data['scope'], 'scope', 160)
    if scope == 'parent':
        scope_kind, scope_name = 'parent', None
    else:
        scope_kind, separator, scope_name = scope.partition(':')
        if not separator or scope_kind not in ('worker', 'external'):
            raise ReceiptError('Unsupported receipt scope')
        _text(scope_name, 'scope name', 150)
    model = _text(data['model'], 'model', 256, optional=True)
    effort = _text(data['effort'], 'effort', 80, optional=True)
    reason = _text(data.get('reason'), 'reason', 600, optional=True, multiline=True)
    evidence = _text(data.get('evidence'), 'evidence', 900, optional=True, multiline=True)
    if status == 'verified' and (model is None or evidence is None):
        raise ReceiptError('Verified requires a model and explicit runtime evidence')
    overrides = data.get('labels', {})
    if not isinstance(overrides, dict) or set(overrides) - set(DEFAULT_LABELS):
        raise ReceiptError('Unsupported receipt labels')
    labels = dict(DEFAULT_LABELS)
    for name, value in overrides.items():
        labels[name] = _text(value, 'label', 160)
    return {
        'status': status, 'scope_kind': scope_kind, 'scope_name': scope_name,
        'model': model, 'effort': effort, 'reason': reason,
        'evidence': evidence, 'labels': labels,
    }


def render_receipt(data, host, *, root_id=None):
    """Return escaped markup; the caller remains responsible for evidence truth."""
    if host not in HOSTS:
        raise ReceiptError('Unsupported rendering host')
    value = validate_receipt(data)
    root_id = root_id or ('dmr-' + uuid.uuid4().hex)
    if not isinstance(root_id, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', root_id):
        raise ReceiptError('Invalid receipt root identifier')
    labels = value['labels']
    scope = labels[value['scope_kind']]
    if value['scope_name'] is not None:
        scope += ' · ' + value['scope_name']
    color, light_color, dark_color = STATUS_COLORS[value['status']]
    escape = lambda text: html.escape(text, quote=True)
    substitutions = {
        'root_id': root_id, 'status': value['status'], 'color': color,
        'light_color': light_color, 'dark_color': dark_color,
        'accessible_label': escape(labels['routing'] + ' · ' + labels[value['status']]),
        'routing_label': escape(labels['routing']), 'scope_label': escape(scope),
        'status_label': escape(labels[value['status']]),
        'model_label': escape(labels['model']), 'effort_label': escape(labels['effort']),
        'model_value': escape(value['model'] if value['model'] is not None else labels['not_exposed']),
        'effort_value': escape(value['effort'] if value['effort'] is not None else labels['not_exposed']),
        'reason_hidden': 'hidden' if value['reason'] is None else '',
        'reason': escape(value['reason'] or ''),
        'evidence_hidden': 'hidden' if value['evidence'] is None else '',
        'evidence_label': escape(labels['evidence']), 'evidence': escape(value['evidence'] or ''),
        'snapshot_label': escape(labels['snapshot']),
    }
    fragment = Template(TEMPLATE_PATH.read_text(encoding='utf-8')).substitute(substitutions)
    if host == 'codex':
        return fragment
    return ('<!doctype html>\n<html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>' + escape(labels['routing']) + '</title>'
            '<style>html,body{margin:0;padding:0;background:transparent;'
            'font-family:system-ui,sans-serif;}</style></head><body>\n'
            + fragment + '</body></html>\n')


def write_receipt(data, host, output):
    target = Path(output)
    if not target.is_absolute():
        raise ReceiptError('Output must be an absolute task-owned path')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*\.html', target.name):
        raise ReceiptError('Output requires a lowercase kebab-case HTML basename')
    markup = render_receipt(data, host)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(markup)
    if host == 'codex':
        reference = '\ue200visualize\ue202' + json.dumps({'path': str(target)}, ensure_ascii=False) + '\ue201'
    else:
        reference = '<agent-embed src="' + html.escape(target.as_uri(), quote=True) + '"></agent-embed>'
    return {
        'host': host, 'path': str(target), 'reference': reference,
        'snapshot': True, 'runtime_verification_performed': False,
        'artifact_registration_required': host == 'antigravity',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, choices=HOSTS)
    parser.add_argument('--input', required=True, help='Receipt JSON file, or - for stdin')
    parser.add_argument('--output', required=True, help='New absolute HTML snapshot path')
    args = parser.parse_args(argv)
    try:
        if args.input == '-':
            raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        else:
            with Path(args.input).open('rb') as handle:
                raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ReceiptError('Receipt input exceeds the size limit')
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
        metadata = write_receipt(data, args.host, args.output)
    except FileExistsError:
        print('Receipt output already exists; choose a new snapshot path.', file=sys.stderr)
        return 2
    except (ReceiptError, UnicodeError, ValueError, OSError, RecursionError):
        print('Unable to render receipt: invalid input or unavailable output.', file=sys.stderr)
        return 2
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
