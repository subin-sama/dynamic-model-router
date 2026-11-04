"""Offline evidence and injection boundaries for native receipt snapshots."""
import html
import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_receipt import ReceiptError, render_receipt, validate_receipt, write_receipt


class ParsedMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attributes = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


def receipt(**updates):
    value = {'status': 'unchanged', 'scope': 'parent', 'model': None, 'effort': None}
    value.update(updates)
    return value


class NativeReceiptTests(unittest.TestCase):
    def test_codex_fragment_preserves_exact_settings_and_unknown_fields(self):
        markup = render_receipt(receipt(status='requested', scope='external:agy',
                                       model='gemini-4-argon-high', effort='high'), 'codex')
        parsed = ParsedMarkup()
        parsed.feed(markup)
        self.assertNotIn('html', parsed.tags)
        self.assertNotIn('body', parsed.tags)
        self.assertIn('gemini-4-argon-high', markup)
        self.assertIn('External · agy', markup)
        unknown = render_receipt(receipt(), 'codex')
        self.assertEqual(unknown.count('<code>Not exposed</code>'), 2)

    def test_antigravity_is_a_self_contained_document_without_external_resources(self):
        markup = render_receipt(receipt(), 'antigravity')
        parsed = ParsedMarkup()
        parsed.feed(markup)
        self.assertIn('html', parsed.tags)
        self.assertIn('head', parsed.tags)
        self.assertIn('body', parsed.tags)
        self.assertNotIn('script', parsed.tags)
        self.assertFalse(any(key in ('src', 'href') for key, value in parsed.attributes))
        self.assertNotIn('url(', markup)

    def test_untrusted_text_cannot_create_markup_attributes_or_template_expansion(self):
        attack = '\"><img src=x onerror=alert(1)><script>alert(2)</script>${root_id}'
        data = receipt(model=attack, effort=attack[:80], reason=attack,
                       evidence=attack, scope='worker:' + attack[:100],
                       labels={'routing': attack, 'unchanged': attack,
                               'model': attack, 'snapshot': attack})
        markup = render_receipt(data, 'codex', root_id='dmr-safe')
        parsed = ParsedMarkup()
        parsed.feed(markup)
        self.assertNotIn('img', parsed.tags)
        self.assertNotIn('script', parsed.tags)
        self.assertFalse(any(name.startswith('on') for name, value in parsed.attributes))
        self.assertIn(html.escape(attack, quote=True), markup)
        self.assertIn('${root_id}', markup)

    def test_verified_requires_explicit_evidence_and_keeps_partial_qualifier_visible(self):
        for data in (receipt(status='verified'), receipt(status='verified', model='known'),
                     receipt(status='verified', evidence='runtime model matched')):
            with self.subTest(data=data), self.assertRaises(ReceiptError):
                render_receipt(data, 'codex')
        qualifier = 'Model variant verified; effort mapped from catalog, not independently observed.'
        markup = render_receipt(receipt(status='verified', model='known',
                                       effort=None, evidence=qualifier), 'codex')
        self.assertIn(qualifier, markup)
        self.assertIn('<p class="dmr-evidence" >', markup)
        self.assertIn('<code>Not exposed</code>', markup)

    def test_invalid_enums_scopes_types_and_unknown_keys_fail(self):
        invalid = [receipt(status='selected'), receipt(status=[]), receipt(scope='child'),
                   receipt(scope='worker:'), receipt(scope='external: agy'),
                   receipt(model=7), receipt(effort=True), receipt(reason=''),
                   receipt(model='line\nbreak'), receipt(labels={'arbitrary': 'text'}),
                   receipt(labels={'routing': False}), receipt(extra='ignored?')]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ReceiptError):
                validate_receipt(data)
        with self.assertRaises(ReceiptError):
            validate_receipt({'status': 'unchanged'})

    def test_limits_and_root_identifier_reject_oversized_or_injected_values(self):
        for data in (receipt(model='x' * 257), receipt(reason='x' * 601),
                     receipt(evidence='x' * 901), receipt(labels={'routing': 'x' * 161})):
            with self.subTest(data=data), self.assertRaises(ReceiptError):
                render_receipt(data, 'codex')
        with self.assertRaises(ReceiptError):
            render_receipt(receipt(), 'codex', root_id='bad\" onclick=alert(1)')
        with self.assertRaises(ReceiptError):
            render_receipt(receipt(), 'unsupported')

    def test_localized_labels_remain_plain_text_and_unique_roots_do_not_collide(self):
        markup = render_receipt(receipt(labels={'unchanged': 'Inchangé',
                                               'not_exposed': 'Non exposé'}), 'codex')
        self.assertIn('Inchangé', markup)
        self.assertEqual(markup.count('<code>Non exposé</code>'), 2)
        again = render_receipt(receipt(), 'codex')
        first = markup.split('id="', 1)[1].split('"', 1)[0]
        second = again.split('id="', 1)[1].split('"', 1)[0]
        self.assertNotEqual(first, second)

    def test_snapshot_creation_is_exclusive_and_metadata_does_not_claim_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'directory with spaces' / 'new-receipt.html'
            result = write_receipt(receipt(), 'codex', output)
            before = output.read_bytes()
            self.assertIn(str(output), result['reference'])
            self.assertTrue(result['reference'].startswith('\ue200visualize\ue202'))
            self.assertFalse(result['runtime_verification_performed'])
            with self.assertRaises(FileExistsError):
                write_receipt(receipt(status='requested'), 'codex', output)
            self.assertEqual(output.read_bytes(), before)
            with self.assertRaises(ReceiptError):
                write_receipt(receipt(), 'codex', 'relative.html')

    def test_antigravity_reference_requires_native_artifact_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'directory "quote"' / 'receipt.html'
            result = write_receipt(receipt(), 'antigravity', output)
            self.assertTrue(result['artifact_registration_required'])
            self.assertIn('%22quote%22', result['reference'])
            self.assertTrue(result['reference'].startswith('<agent-embed src="file:///'))

    def test_invalid_native_html_basenames_fail_before_output_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            for host in ('codex', 'antigravity'):
                for name in ('Receipt.html', 'receipt.HTML', 'receipt_name.html',
                             'receipt name.html', 'receipt-.html', 'receipt.svg'):
                    output = Path(folder) / 'must-not-create' / name
                    with self.subTest(host=host, name=name), self.assertRaises(ReceiptError):
                        write_receipt(receipt(), host, output)
                    self.assertFalse(output.parent.exists())

    def test_cli_stdin_outputs_public_metadata_and_oversized_input_does_not_write(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'render_receipt.py'
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'receipt.html'
            command = [sys.executable, str(script), '--host', 'codex',
                       '--input', '-', '--output', str(output)]
            result = subprocess.run(command, input=json.dumps(receipt()), text=True,
                                    capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['path'], str(output))
            oversized = Path(folder) / 'oversized.html'
            result = subprocess.run(command[:-1] + [str(oversized)], input=' ' * 16385,
                                    text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertFalse(oversized.exists())

    def test_cli_rejects_ambiguous_duplicate_keys_and_deep_json_without_tracebacks(self):
        script = Path(__file__).resolve().parents[1] / 'scripts' / 'render_receipt.py'
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'receipt.html'
            command = [sys.executable, str(script), '--host', 'codex',
                       '--input', '-', '--output', str(output)]
            invalid = ['{"status":"unchanged","status":"verified","scope":"parent",'
                       '"model":null,"effort":null}', '[' * 1100 + ']' * 1100]
            for raw in invalid:
                with self.subTest(raw=raw[:80]):
                    result = subprocess.run(command, input=raw, text=True,
                                            capture_output=True, check=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, '')
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
