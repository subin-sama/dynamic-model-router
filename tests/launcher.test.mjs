import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const cli = path.join(root, 'cli/bin.mjs');

test('Antigravity launcher forwards literal arguments and the child exit code', {skip: process.platform === 'win32'}, t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'router-launcher-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const python = path.join(directory, 'fake python');
  const capture = path.join(directory, 'arguments.json');
  const sentinel = path.join(directory, 'must-not-exist');
  fs.writeFileSync(python, `#!/usr/bin/env node
require('node:fs').writeFileSync(process.env.ROUTER_TEST_CAPTURE, JSON.stringify(process.argv.slice(2)));
process.exit(23);
`, {mode: 0o755});
  const task = `Literal task $(touch ${sentinel})`;
  const result = spawnSync(process.execPath, [cli, 'antigravity', '--task', task, '--help'], {
    env: {...process.env, DYNAMIC_MODEL_ROUTER_PYTHON: python, ROUTER_TEST_CAPTURE: capture}, encoding: 'utf8',
  });
  assert.equal(result.status, 23, result.stderr);
  assert.deepEqual(JSON.parse(fs.readFileSync(capture, 'utf8')), [
    path.join(root, 'scripts/antigravity_parent_router.py'), '--task', task, '--help',
  ]);
  assert.equal(fs.existsSync(sentinel), false);
});

test('missing Python yields an actionable error without attempting installation', () => {
  const result = spawnSync(process.execPath, [cli, 'antigravity', '--help'], {
    env: {...process.env, DYNAMIC_MODEL_ROUTER_PYTHON: path.join(os.tmpdir(), 'missing-router-python', 'python3')}, encoding: 'utf8',
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /requires Python 3\.9\+/);
  assert.match(result.stderr, /DYNAMIC_MODEL_ROUTER_PYTHON/);
});

test('installer help remains independent of the optional Python launcher', () => {
  const result = spawnSync(process.execPath, [cli, '--help'], {
    env: {...process.env, DYNAMIC_MODEL_ROUTER_PYTHON: 'missing-router-python'}, encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /install\|uninstall/);
  assert.match(result.stdout, /antigravity \[router options\]/);
});
