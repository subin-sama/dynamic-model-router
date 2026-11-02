import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { install, uninstall, BEGIN, END } from '../cli/install.mjs';

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const skillText = '---\nname: dynamic-model-router\ndescription: Test routing policy\n---\n# Routing\n';

function fixture(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'dmr-install-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const home = path.join(root, 'home');
  const payloadRoot = path.join(root, 'package');
  fs.mkdirSync(home);
  fs.mkdirSync(path.join(payloadRoot, 'scripts'), { recursive: true });
  fs.writeFileSync(path.join(payloadRoot, 'SKILL.md'), skillText);
  fs.writeFileSync(path.join(payloadRoot, 'LICENSE'), 'MIT test fixture\n');
  fs.writeFileSync(path.join(payloadRoot, 'README.md'), 'English documentation\n');
  fs.writeFileSync(path.join(payloadRoot, 'scripts', 'sample.py'), 'print("ready")\n');
  const shared = path.join(home, '.agents', 'skills', 'dynamic-model-router');
  const adapter = (id = 'codex', extra = {}) => ({
    id, label: id, detected: true,
    instructionPath: path.join(home, `.${id}`, 'AGENTS.md'),
    skillPaths: [shared], notes: [], ...extra,
  });
  const options = { home, env: {}, payloadRoot, adapters: [adapter()] };
  return { root, home, payloadRoot, shared, adapter, options };
}

function write(file, value) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, value); }
function bytes(file) { return fs.readFileSync(file); }
function state(home) { return JSON.parse(fs.readFileSync(path.join(home, '.config', 'dynamic-model-router', 'install-state.json'), 'utf8')); }

test('fresh installation enables every task and copies only the embedded skill payload', t => {
  const f = fixture(t);
  const result = install(f.options);
  assert.equal(result.agents[0].status, 'installed');
  assert.equal(fs.readFileSync(path.join(f.shared, 'SKILL.md'), 'utf8'), skillText);
  assert.equal(fs.existsSync(path.join(f.shared, 'cli')), false);
  const instructions = fs.readFileSync(f.options.adapters[0].instructionPath, 'utf8');
  assert.ok(instructions.includes(BEGIN));
  assert.ok(instructions.includes('for every task in every project'));
  assert.ok(instructions.includes(path.join(f.shared, 'SKILL.md')));
  assert.equal(state(f.home).agents.codex.skillPath, f.shared);
});

test('preserves all original bytes including BOM CRLF Unicode invalid UTF-8 and missing final newline', t => {
  const f = fixture(t);
  const original = Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from('Original instructions\r\nUnicode '), Buffer.from([0xe0, 0xb8, 0x81, 0xff])]);
  const target = f.options.adapters[0].instructionPath;
  write(target, original);
  const result = install(f.options);
  assert.ok(bytes(target).subarray(0, original.length).equals(original));
  assert.ok(bytes(target).includes(Buffer.from('\r\n' + BEGIN)));
  assert.equal(result.backups.length, 1);
  assert.ok(bytes(result.backups[0]).equals(original));
  uninstall(f.options);
  assert.ok(bytes(target).equals(original));
});

test('repeat installation is idempotent and does not duplicate routing or backups', t => {
  const f = fixture(t);
  write(f.options.adapters[0].instructionPath, 'Existing\n');
  install(f.options);
  const before = bytes(f.options.adapters[0].instructionPath);
  const second = install(f.options);
  assert.equal(second.changes.length, 0);
  assert.equal(second.backups.length, 0);
  assert.ok(bytes(f.options.adapters[0].instructionPath).equals(before));
  assert.equal(before.toString().split(BEGIN).length - 1, 1);
});

test('reuses a valid manual legacy skill without creating a duplicate or claiming ownership', t => {
  const f = fixture(t);
  const legacy = path.join(f.home, '.codex', 'skills', 'dynamic-model-router');
  write(path.join(legacy, 'SKILL.md'), skillText + 'User customization\n');
  f.options.adapters[0].skillPaths.push(legacy);
  const result = install(f.options);
  assert.equal(result.agents[0].status, 'reused-existing');
  assert.equal(result.agents[0].skillPath, legacy);
  assert.equal(fs.existsSync(f.shared), false);
  assert.equal(Object.keys(state(f.home).skills).length, 0);
  uninstall(f.options);
  assert.ok(fs.readFileSync(path.join(legacy, 'SKILL.md'), 'utf8').includes('User customization'));
});

test('an invalid existing skill destination is preserved and fails before instructions change', t => {
  const f = fixture(t);
  write(path.join(f.shared, 'SKILL.md'), 'Different user content');
  assert.throws(() => install(f.options), /not a valid/);
  assert.equal(fs.existsSync(f.options.adapters[0].instructionPath), false);
  assert.equal(fs.readFileSync(path.join(f.shared, 'SKILL.md'), 'utf8'), 'Different user content');
});

test('a name appearing only in the body does not establish skill identity', t => {
  const f = fixture(t);
  const unrelated = '---\nname: other-skill\n---\nname: dynamic-model-router\n';
  write(path.join(f.shared, 'SKILL.md'), unrelated);
  assert.throws(() => install(f.options), /not a valid/);
  assert.equal(fs.readFileSync(path.join(f.shared, 'SKILL.md'), 'utf8'), unrelated);
});

test('all instruction targets are preflighted before any mutation', t => {
  const f = fixture(t);
  const first = f.options.adapters[0];
  const second = f.adapter('claude-code');
  f.options.adapters.push(second);
  write(first.instructionPath, 'Keep first instructions');
  write(second.instructionPath, BEGIN + '\nIncomplete marker');
  assert.throws(() => install(f.options), /Malformed or duplicate/);
  assert.equal(fs.readFileSync(first.instructionPath, 'utf8'), 'Keep first instructions');
  assert.equal(fs.existsSync(f.shared), false);
  assert.equal(fs.existsSync(path.join(f.home, '.config')), false);
});

test('duplicate managed markers are rejected without changing the file', t => {
  const f = fixture(t);
  const original = `${BEGIN}\nfirst\n${END}\n${BEGIN}\nsecond\n${END}\n`;
  write(f.options.adapters[0].instructionPath, original);
  assert.throws(() => install(f.options), /Malformed or duplicate/);
  assert.equal(fs.readFileSync(f.options.adapters[0].instructionPath, 'utf8'), original);
});

test('a preexisting marked block without installer metadata is not adopted or overwritten', t => {
  const f = fixture(t);
  const original = `${BEGIN}\nUse the installed dynamic-model-router skill for every task in every project.\nUser customization\n${END}\n`;
  write(f.options.adapters[0].instructionPath, original);
  assert.throws(() => install(f.options), /without installer ownership metadata/);
  assert.equal(fs.readFileSync(f.options.adapters[0].instructionPath, 'utf8'), original);
  assert.equal(fs.existsSync(f.shared), false);
});

test('deleted installer state does not permit replacing a user-edited marked block', t => {
  const f = fixture(t);
  install(f.options);
  const target = f.options.adapters[0].instructionPath;
  const changed = fs.readFileSync(target, 'utf8').replace(END, 'Keep this custom command\n' + END);
  fs.writeFileSync(target, changed);
  fs.unlinkSync(path.join(f.home, '.config', 'dynamic-model-router', 'install-state.json'));
  assert.throws(() => install(f.options), /without installer ownership metadata/);
  assert.equal(fs.readFileSync(target, 'utf8'), changed);
});

test('retains an instruction file symlink and updates/backups its actual target', t => {
  const f = fixture(t);
  const target = path.join(f.home, 'dotfiles', 'global-rules.md');
  write(target, 'Dotfile instructions\n');
  const link = f.options.adapters[0].instructionPath;
  fs.mkdirSync(path.dirname(link), { recursive: true });
  fs.symlinkSync(target, link);
  const result = install(f.options);
  assert.ok(fs.lstatSync(link).isSymbolicLink());
  assert.equal(result.agents[0].instructionPath, target);
  assert.ok(fs.readFileSync(target, 'utf8').startsWith('Dotfile instructions\n'));
  uninstall(f.options);
  assert.ok(fs.lstatSync(link).isSymbolicLink());
  assert.equal(fs.readFileSync(target, 'utf8'), 'Dotfile instructions\n');
});

test('deduplicates a shared instruction target across adapters', t => {
  const f = fixture(t);
  const original = path.join(f.home, 'shared-rules.md');
  write(original, 'Shared instructions\n');
  const a = f.options.adapters[0];
  const b = f.adapter('claude-code');
  for (const item of [a, b]) {
    fs.mkdirSync(path.dirname(item.instructionPath), { recursive: true });
    fs.symlinkSync(original, item.instructionPath);
  }
  f.options.adapters.push(b);
  const result = install(f.options);
  assert.equal(result.changes.filter(item => item.kind === 'instruction').length, 1);
  assert.equal(fs.readFileSync(original, 'utf8').split(BEGIN).length - 1, 1);
  assert.equal(Object.keys(state(f.home).skills).length, 1);
});

test('uninstalling one adapter keeps a shared skill needed by another', t => {
  const f = fixture(t);
  f.options.adapters.push(f.adapter('claude-code'));
  install(f.options);
  uninstall({ ...f.options, agents: ['codex'] });
  assert.ok(fs.existsSync(path.join(f.shared, 'SKILL.md')));
  assert.ok(fs.readFileSync(f.options.adapters[1].instructionPath, 'utf8').includes(BEGIN));
  assert.equal(state(f.home).agents.codex, undefined);
  uninstall({ ...f.options, agents: ['claude-code'] });
  assert.equal(fs.existsSync(path.join(f.shared, 'SKILL.md')), false);
});

test('fresh adapters reuse one already planned shared payload', t => {
  const f = fixture(t);
  const native = path.join(f.home, '.claude', 'skills', 'dynamic-model-router');
  f.options.adapters.push(f.adapter('claude-code', { skillPaths: [native, f.shared] }));
  const result = install(f.options);
  assert.equal(result.agents[0].skillPath, result.agents[1].skillPath);
  assert.equal(Object.keys(state(f.home).skills).length, 1);
  assert.equal(fs.existsSync(native), false);
});

test('installing another host alone does not create a duplicate visible to a legacy Codex installation', t => {
  const f = fixture(t);
  const legacy = path.join(f.home, '.codex', 'skills', 'dynamic-model-router');
  const native = path.join(f.home, '.gemini', 'skills', 'dynamic-model-router');
  write(path.join(legacy, 'SKILL.md'), skillText);
  f.options.adapters[0].skillPaths.push(legacy);
  f.options.adapters.push(f.adapter('gemini-cli', { skillPaths: [f.shared, native] }));
  const result = install({ ...f.options, agents: ['gemini-cli'] });
  assert.equal(result.agents[0].skillPath, native);
  assert.equal(fs.existsSync(f.shared), false);
  assert.equal(fs.existsSync(f.options.adapters[0].instructionPath), false);
  assert.equal(fs.readFileSync(path.join(legacy, 'SKILL.md'), 'utf8'), skillText);
});

test('preserves newer user edits outside the managed block during uninstall', t => {
  const f = fixture(t);
  const target = f.options.adapters[0].instructionPath;
  write(target, 'Original without final newline');
  install(f.options);
  fs.appendFileSync(target, '\nNew user instruction\n');
  uninstall(f.options);
  assert.equal(fs.readFileSync(target, 'utf8'), 'Original without final newline\nNew user instruction\n');
});

test('edited managed block fails closed without deleting skill files', t => {
  const f = fixture(t);
  install(f.options);
  const target = f.options.adapters[0].instructionPath;
  const changed = fs.readFileSync(target, 'utf8').replace('Preserve explicit', 'User changed: preserve explicit');
  fs.writeFileSync(target, changed);
  assert.throws(() => uninstall(f.options), /was edited/);
  assert.equal(fs.readFileSync(target, 'utf8'), changed);
  assert.ok(fs.existsSync(path.join(f.shared, 'SKILL.md')));
});

test('updates only unchanged owned files and preserves unrelated additions', t => {
  const f = fixture(t);
  install(f.options);
  write(path.join(f.shared, 'user-note.md'), 'Keep me');
  write(path.join(f.payloadRoot, 'scripts', 'sample.py'), 'print("new version")\n');
  install(f.options);
  assert.equal(fs.readFileSync(path.join(f.shared, 'scripts', 'sample.py'), 'utf8'), 'print("new version")\n');
  assert.equal(fs.readFileSync(path.join(f.shared, 'user-note.md'), 'utf8'), 'Keep me');
});

test('refuses to overwrite edited owned skill files', t => {
  const f = fixture(t);
  install(f.options);
  write(path.join(f.shared, 'scripts', 'sample.py'), 'User code');
  const before = bytes(f.options.adapters[0].instructionPath);
  assert.throws(() => install(f.options), /was edited or removed/);
  assert.equal(fs.readFileSync(path.join(f.shared, 'scripts', 'sample.py'), 'utf8'), 'User code');
  assert.ok(bytes(f.options.adapters[0].instructionPath).equals(before));
});

test('owned roots replaced by symlinks are not followed during update or uninstall', t => {
  const f = fixture(t);
  install(f.options);
  const outside = path.join(f.root, 'external-skill');
  fs.renameSync(f.shared, outside);
  fs.symlinkSync(outside, f.shared, 'dir');
  const before = bytes(path.join(outside, 'SKILL.md'));
  assert.throws(() => install(f.options), /owned skill root changed/);
  assert.throws(() => uninstall(f.options), /owned skill root changed/);
  assert.ok(bytes(path.join(outside, 'SKILL.md')).equals(before));
});

test('owned subdirectories replaced by symlinks are preserved instead of traversed', t => {
  const f = fixture(t);
  install(f.options);
  const outside = path.join(f.root, 'external-scripts');
  fs.renameSync(path.join(f.shared, 'scripts'), outside);
  fs.symlinkSync(outside, path.join(f.shared, 'scripts'), 'dir');
  const before = bytes(path.join(outside, 'sample.py'));
  assert.throws(() => install(f.options), /owned skill path was replaced by a symlink/);
  assert.throws(() => uninstall(f.options), /owned skill path was replaced by a symlink/);
  assert.ok(bytes(path.join(outside, 'sample.py')).equals(before));
});

test('uninstall removes unchanged owned files while preserving modified and user-added files', t => {
  const f = fixture(t);
  install(f.options);
  write(path.join(f.shared, 'scripts', 'sample.py'), 'User code');
  write(path.join(f.shared, 'user-note.md'), 'User note');
  const result = uninstall(f.options);
  assert.equal(fs.existsSync(path.join(f.shared, 'SKILL.md')), false);
  assert.equal(fs.readFileSync(path.join(f.shared, 'scripts', 'sample.py'), 'utf8'), 'User code');
  assert.equal(fs.readFileSync(path.join(f.shared, 'user-note.md'), 'utf8'), 'User note');
  assert.deepEqual(result.preservedFiles, [path.join(f.shared, 'scripts', 'sample.py')]);
});

test('new payload files never overwrite an unowned user file', t => {
  const f = fixture(t);
  install(f.options);
  write(path.join(f.shared, 'scripts', 'extra.py'), 'User extra');
  write(path.join(f.payloadRoot, 'scripts', 'extra.py'), 'Package extra');
  assert.throws(() => install(f.options), /user file conflicts/);
  assert.equal(fs.readFileSync(path.join(f.shared, 'scripts', 'extra.py'), 'utf8'), 'User extra');
});

test('a multi-target write failure rolls back changed instructions and new payload files', t => {
  const f = fixture(t);
  const second = f.adapter('claude-code');
  f.options.adapters.push(second);
  for (const adapter of f.options.adapters) write(adapter.instructionPath, `Original ${adapter.id}`);
  assert.throws(() => install({ ...f.options, beforeWrite(operation) {
    if (operation.kind === 'instruction' && operation.file === second.instructionPath) throw new Error('Simulated write failure');
  } }), /Simulated write failure/);
  for (const adapter of f.options.adapters) assert.equal(fs.readFileSync(adapter.instructionPath, 'utf8'), `Original ${adapter.id}`);
  assert.equal(fs.existsSync(path.join(f.shared, 'SKILL.md')), false);
  assert.equal(fs.existsSync(path.join(f.home, '.config', 'dynamic-model-router', 'install-state.json')), false);
});

test('a concurrent instruction edit after backup is preserved and other writes roll back', t => {
  const f = fixture(t);
  const target = f.options.adapters[0].instructionPath;
  write(target, 'Original');
  assert.throws(() => install({ ...f.options, beforeWrite(operation) {
    if (operation.kind === 'instruction') fs.writeFileSync(target, 'New concurrent user instruction');
  } }), /destination changed during installation/);
  assert.equal(fs.readFileSync(target, 'utf8'), 'New concurrent user instruction');
  assert.equal(fs.existsSync(path.join(f.shared, 'SKILL.md')), false);
  assert.equal(fs.existsSync(path.join(f.home, '.config', 'dynamic-model-router', 'install-state.json')), false);
});

test('dry run creates no destinations or installer metadata', t => {
  const f = fixture(t);
  const result = install({ ...f.options, dryRun: true });
  assert.ok(result.changes.length > 0);
  assert.equal(fs.existsSync(f.shared), false);
  assert.equal(fs.existsSync(path.join(f.home, '.codex')), false);
  assert.equal(fs.existsSync(path.join(f.home, '.config')), false);
});

test('preserves existing instruction mode', t => {
  const f = fixture(t);
  const target = f.options.adapters[0].instructionPath;
  write(target, 'Keep private'); fs.chmodSync(target, 0o640);
  install(f.options);
  assert.equal(fs.statSync(target).mode & 0o777, 0o640);
});

test('blocked or unknown adapters fail before mutation', t => {
  const f = fixture(t);
  assert.throws(() => install({ ...f.options, agents: ['unsupported'] }), /Unsupported agent/);
  assert.throws(() => install({ ...f.options, adapters: [f.adapter('codex', { blockedReason: 'Custom configuration needs review' })] }), /Custom configuration needs review/);
  assert.equal(fs.existsSync(path.join(f.home, '.config')), false);
});

test('uninstall uses stored targets even if a new adapter configuration blocks activation', t => {
  const f = fixture(t);
  install(f.options);
  const changed = f.adapter('codex', { blockedReason: 'New unsupported activation setting' });
  uninstall({ ...f.options, adapters: [changed] });
  assert.equal(fs.existsSync(path.join(f.shared, 'SKILL.md')), false);
  assert.equal(fs.existsSync(changed.instructionPath), false);
});

test('uninstall on an unconfigured home is a no-op', t => {
  const f = fixture(t);
  const result = uninstall(f.options);
  assert.equal(result.changes.length, 0);
  assert.equal(fs.existsSync(path.join(f.home, '.config')), false);
});

test('CLI staging home ignores real profile overrides and does not use a shell', t => {
  const f = fixture(t);
  const external = path.join(f.root, 'outside-profile');
  const result = spawnSync(process.execPath, [path.join(repository, 'cli', 'bin.mjs'), '--home', f.home, '--agents', 'claude-code', '--json'], {
    encoding: 'utf8', env: { ...process.env, CLAUDE_CONFIG_DIR: external },
  });
  assert.equal(result.status, 0, result.stderr);
  const parsed = JSON.parse(result.stdout);
  assert.ok(parsed.agents[0].instructionPath.startsWith(f.home + path.sep));
  assert.equal(fs.existsSync(external), false);
  const again = spawnSync(process.execPath, [path.join(repository, 'cli', 'bin.mjs'), 'uninstall', '--home', f.home, '--agents', 'claude-code', '--json'], { encoding: 'utf8' });
  assert.equal(again.status, 0, again.stderr);
});
