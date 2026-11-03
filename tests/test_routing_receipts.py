"""Offline coverage for the public routing receipt format."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from routing_receipts import format_receipt


class RoutingReceiptTests(unittest.TestCase):
    def test_format_keeps_unknown_runtime_values_and_public_reason_on_one_line(self):
        self.assertEqual(
            format_receipt('unverified', {'model': 'known-model', 'effort': None},
                           'Runtime evidence\n is incomplete.'),
            '[Routing][unverified][parent] model=known-model; effort=unknown — Runtime evidence is incomplete.')
        self.assertEqual(
            format_receipt('error', reason='Dispatch failed.'),
            '[Routing][error][parent] model=unknown; effort=unknown — Dispatch failed.')

    def test_unsupported_status_cannot_be_mistaken_for_a_native_acknowledgment(self):
        with self.assertRaises(ValueError):
            format_receipt('selected', {'model': 'known-model', 'effort': 'low'})


if __name__ == '__main__':
    unittest.main()
