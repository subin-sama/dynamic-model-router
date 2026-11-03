"""Compact public routing receipts; callers supply only supported evidence."""
import sys


STATUSES = frozenset(('recommended', 'requested', 'applied', 'verified',
                      'unchanged', 'unverified', 'error'))


def _single_line(value):
    return ' '.join(value.split())


def format_receipt(status, pair=None, reason='', *, scope='parent'):
    """Format known values without filling unknown runtime fields from a request."""
    if status not in STATUSES:
        raise ValueError('Unsupported routing receipt status')
    pair = pair or {}
    values = {key: _single_line(pair[key])
              if isinstance(pair.get(key), str) and pair[key].strip() else 'unknown'
              for key in ('model', 'effort')}
    return ('[Routing][' + status + '][' + _single_line(scope) + '] model='
            + values['model'] + '; effort=' + values['effort'] + ' — '
            + _single_line(reason))


def emit_receipt(status, pair=None, reason='', *, scope='parent'):
    print(format_receipt(status, pair, reason, scope=scope),
          file=sys.stderr, flush=True)
