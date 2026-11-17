import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { install, uninstall } from '../cli/install.mjs';
import { claudeHook, changeClaudeHook } from '../cli/claude-hooks.mjs';

const skill = '---\nname: dynamic-model-router\ndescription: Fixture\n---\n# Routing\n';
const runtime = 'console.log(JSON.stringify({called:true,args:process.argv.slice(2)}));\n';
const write = (file, value) => { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, value); };
const read = file => fs.readFileSync(file);
const json = file => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));

function fixture(t, name = 'home') {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'dmr-claude-hook-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const home = path.join(root, name), payloadRoot = path.join(root, 'package');
  fs.mkdirSync(home);
  write(path.join(payloadRoot, 'SKILL.md'), skill);
  write(path.join(payloadRoot, 'LICENSE'), 'MIT\n');
  write(path.join(payloadRoot, 'scripts/claude_activation_hook.mjs'), runtime);
  const options = { home, env: {}, payloadRoot, agents: 'claude-code' };
  const settings = path.join(home, '.claude/settings.json');
  const instructions = path.join(home, '.claude/CLAUDE.md');
  const statePath = path.join(home, '.config/dynamic-model-router/install-state.json');
  return { root, home, payloadRoot, options, settings, instructions, statePath };
}
const leaves = settings => (settings.hooks?.UserPromptSubmit || []).flatMap(entry => entry.hooks);

test('Claude installation registers one native metadata hook and tracks ownership without settings values', t => {
  const f = fixture(t);
  const result = install(f.options);
  const values = json(f.settings);
  assert.equal(leaves(values).length, 1);
  assert.equal(leaves(values)[0].timeout, 45);
  assert.equal(result.agents[0].nativeHookStatus, 'configured');
  assert.ok(result.changes.some(change => change.kind === 'settings'));
  const metadata = json(f.statePath).nativeHooks[f.settings];
  assert.equal(metadata.adapterId, 'claude-code');
  assert.equal(metadata.event, 'UserPromptSubmit');
  assert.equal(metadata.originalHash, null);
  assert.ok(metadata.runtimeHash.match(/^[a-f0-9]{64}$/));
  assert.equal(fs.statSync(f.settings).mode & 0o777, 0o600);
});

test('existing JSON settings, permissions, env and hooks survive with exact backup and unchanged uninstall restoration', t => {
  const f = fixture(t);
  const original = Buffer.from('\uFEFF{\r\n\t"env": {"PRIVATE_VALUE": "secret-do-not-copy-to-state"},\r\n\t"permissions": {"allow": ["Bash(npm test)"]},\r\n\t"hooks": {"Stop": [{"hooks": [{"type":"command","command":"user stop"}]}], "UserPromptSubmit": [{"matcher":"user","hooks":[{"type":"command","command":"user prompt"}]}]}\r\n}');
  write(f.settings, original); fs.chmodSync(f.settings, 0o640);
  write(f.instructions, 'User instructions');
  const before = json(f.settings);
  const result = install(f.options), after = json(f.settings);
  assert.deepEqual(after.env, before.env);
  assert.deepEqual(after.permissions, before.permissions);
  assert.deepEqual(after.hooks.Stop, before.hooks.Stop);
  assert.deepEqual(after.hooks.UserPromptSubmit[0], before.hooks.UserPromptSubmit[0]);
  assert.ok(result.backups.some(file => read(file).equals(original)));
  assert.ok(result.backups.every(file => (fs.statSync(file).mode & 0o777) === 0o600));
  assert.equal(fs.statSync(f.settings).mode & 0o777, 0o640);
  assert.equal(fs.readFileSync(f.statePath, 'utf8').includes('secret-do-not-copy-to-state'), false);
  uninstall(f.options);
  assert.ok(read(f.settings).equals(original));
  assert.equal(fs.readFileSync(f.instructions, 'utf8'), 'User instructions');
});

test('repeat setup produces no settings changes, duplicate hooks or backups', t => {
  const f = fixture(t);
  install(f.options);
  const before = read(f.settings);
  const result = install(f.options);
  assert.deepEqual(result.changes, []);
  assert.deepEqual(result.backups, []);
  assert.ok(read(f.settings).equals(before));
  assert.equal(leaves(json(f.settings)).length, 1);
});

test('uninstall keeps later settings and companion commands added to the same hook entry', t => {
  const f = fixture(t);
  install(f.options);
  const updated = json(f.settings);
  updated.model = 'user-model';
  updated.permissions = { deny: ['Bash(rm *)'] };
  updated.hooks.UserPromptSubmit[0].hooks.push({ type: 'command', command: 'new user prompt hook' });
  write(f.settings, JSON.stringify(updated, null, 4));
  uninstall(f.options);
  const after = json(f.settings);
  assert.equal(after.model, 'user-model');
  assert.deepEqual(after.permissions, updated.permissions);
  assert.deepEqual(leaves(after), [{ type: 'command', command: 'new user prompt hook' }]);
  assert.equal(fs.existsSync(f.statePath), false);
});

test('updating an owned command leaf preserves companion commands and user settings', () => {
  const before = Buffer.from('{"permissions":{"deny":["Bash(rm *)"]}}');
  const one = changeClaudeHook(before, claudeHook('/first'), null);
  const current = JSON.parse(one.after);
  current.hooks.UserPromptSubmit[0].hooks.push({ type: 'command', command: 'user companion' });
  const two = changeClaudeHook(Buffer.from(JSON.stringify(current)), claudeHook('/second'), one.record);
  const after = JSON.parse(two.after);
  assert.equal(after.hooks.UserPromptSubmit[0].hooks[1].command, 'user companion');
  assert.ok(after.hooks.UserPromptSubmit[0].hooks[0].command.includes('/second'));
  assert.deepEqual(after.permissions, current.permissions);
});

test('shell quoting executes only the intended runtime for special-character home paths', { skip: process.platform === 'win32' }, t => {
  const f = fixture(t, "home' $HOME `touch unexpected-marker`");
  install(f.options);
  const command = leaves(json(f.settings))[0].command;
  const run = spawnSync('/bin/sh', ['-c', command], { cwd: f.root, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(JSON.parse(run.stdout), { called: true, args: [] });
  assert.equal(fs.existsSync(path.join(f.root, 'unexpected-marker')), false);
});

test('invalid settings reject the whole installation before source or instructions change', t => {
  const f = fixture(t);
  write(f.settings, '{invalid user JSON');
  assert.throws(() => install(f.options), /not valid JSON/);
  assert.equal(fs.readFileSync(f.settings, 'utf8'), '{invalid user JSON');
  assert.equal(fs.existsSync(f.instructions), false);
  assert.equal(fs.existsSync(f.statePath), false);
  assert.equal(fs.existsSync(path.join(f.home, '.claude/skills/dynamic-model-router')), false);
});

test('edited managed command fails closed during update and uninstall', t => {
  const f = fixture(t);
  install(f.options);
  const changed = json(f.settings);
  changed.hooks.UserPromptSubmit[0].hooks[0].timeout = 123;
  write(f.settings, JSON.stringify(changed));
  const before = read(f.settings);
  assert.throws(() => install(f.options), /activation hook was edited/);
  assert.throws(() => uninstall(f.options), /activation hook was edited/);
  assert.ok(read(f.settings).equals(before));
  assert.ok(fs.existsSync(path.join(f.home, '.claude/skills/dynamic-model-router/scripts/claude_activation_hook.mjs')));
});

test('a matching hook without ownership is preserved instead of adopted or duplicated', t => {
  const f = fixture(t);
  write(f.settings, JSON.stringify({ hooks: { UserPromptSubmit: [{ hooks: [claudeHook('/manual')] }] } }));
  const before = read(f.settings);
  assert.throws(() => install(f.options), /without installer ownership/);
  assert.ok(read(f.settings).equals(before));
  assert.equal(fs.existsSync(f.instructions), false);
});

test('duplicate owned hooks fail closed without deleting their runtime', t => {
  const f = fixture(t);
  install(f.options);
  const duplicated = json(f.settings);
  duplicated.hooks.UserPromptSubmit.push(structuredClone(duplicated.hooks.UserPromptSubmit[0]));
  write(f.settings, JSON.stringify(duplicated));
  assert.throws(() => uninstall(f.options), /duplicated/);
  assert.ok(fs.existsSync(path.join(f.home, '.claude/skills/dynamic-model-router/scripts/claude_activation_hook.mjs')));
});

test('uninstall retains settings when the user already removed the owned hook', t => {
  const f = fixture(t);
  install(f.options);
  write(f.settings, '{"model":"user-model"}');
  uninstall(f.options);
  assert.equal(fs.readFileSync(f.settings, 'utf8'), '{"model":"user-model"}');
});

test('a concurrent settings edit is preserved while all earlier writes roll back', t => {
  const f = fixture(t);
  write(f.settings, '{"model":"before"}');
  write(f.instructions, 'Original user instructions');
  assert.throws(() => install({ ...f.options, beforeWrite(operation) {
    if (operation.kind === 'settings') fs.writeFileSync(f.settings, '{"model":"concurrent"}');
  } }), /destination changed during installation/);
  assert.equal(fs.readFileSync(f.settings, 'utf8'), '{"model":"concurrent"}');
  assert.equal(fs.readFileSync(f.instructions, 'utf8'), 'Original user instructions');
  assert.equal(fs.existsSync(f.statePath), false);
  assert.equal(fs.existsSync(path.join(f.home, '.claude/skills/dynamic-model-router')), false);
});

test('a later settings write failure restores original settings and instructions exactly', t => {
  const f = fixture(t);
  write(f.settings, '{"model":"original"}\n');
  write(f.instructions, 'Original');
  assert.throws(() => install({ ...f.options, beforeWrite(operation) {
    if (operation.kind === 'state') throw new Error('Simulated state failure');
  } }), /Simulated state failure/);
  assert.equal(fs.readFileSync(f.settings, 'utf8'), '{"model":"original"}\n');
  assert.equal(fs.readFileSync(f.instructions, 'utf8'), 'Original');
  assert.equal(fs.existsSync(f.statePath), false);
});

test('settings symlinks remain symlinks while actual target is backed up and restored', t => {
  const f = fixture(t);
  const target = path.join(f.root, 'dotfiles/claude-settings.json');
  write(target, '{"model":"dotfile"}\n');
  fs.mkdirSync(path.dirname(f.settings), { recursive: true });
  fs.symlinkSync(target, f.settings);
  const result = install(f.options);
  assert.equal(result.agents[0].nativeHookPath, target);
  assert.equal(fs.lstatSync(f.settings).isSymbolicLink(), true);
  uninstall(f.options);
  assert.equal(fs.lstatSync(f.settings).isSymbolicLink(), true);
  assert.equal(fs.readFileSync(target, 'utf8'), '{"model":"dotfile"}\n');
});

test('custom Claude config root determines settings even when CLAUDE.md is a dotfile symlink', t => {
  const f = fixture(t);
  const config = path.join(f.root, 'custom profile'), instructions = path.join(config, 'CLAUDE.md');
  const target = path.join(f.root, 'dotfiles/rules.md');
  write(target, 'Custom instructions'); fs.mkdirSync(config); fs.symlinkSync(target, instructions);
  install({ ...f.options, env: { CLAUDE_CONFIG_DIR: config } });
  assert.ok(leaves(json(path.join(config, 'settings.json'))).length === 1);
  assert.equal(fs.existsSync(path.join(f.root, 'dotfiles/settings.json')), false);
  assert.equal(fs.existsSync(f.settings), false);
});

test('installing or removing other agents does not alter a configured Claude hook', t => {
  const f = fixture(t);
  install({ ...f.options, agents: 'claude-code,codex' });
  const before = read(f.settings);
  install({ ...f.options, agents: 'codex' });
  uninstall({ ...f.options, agents: 'codex' });
  assert.ok(read(f.settings).equals(before));
  assert.ok(json(f.statePath).nativeHooks[f.settings]);
  uninstall(f.options);
  assert.equal(fs.existsSync(f.settings), false);
});

test('legacy reused manual skill without runtime stays untouched and reports hook unavailable', t => {
  const f = fixture(t);
  const manual = path.join(f.home, '.claude/skills/dynamic-model-router');
  write(path.join(manual, 'SKILL.md'), skill + 'Personal note\n');
  const result = install(f.options);
  assert.equal(result.agents[0].nativeHookStatus, 'runtime-unavailable');
  assert.equal(fs.existsSync(f.settings), false);
  assert.equal(json(f.statePath).skills[manual], undefined);
  assert.ok(fs.readFileSync(path.join(manual, 'SKILL.md'), 'utf8').endsWith('Personal note\n'));
});

test('a reused manual skill with the current runtime gets a hook without being adopted', t => {
  const f = fixture(t);
  const manual = path.join(f.home, '.claude/skills/dynamic-model-router');
  write(path.join(manual, 'SKILL.md'), skill);
  write(path.join(manual, 'scripts/claude_activation_hook.mjs'), runtime);
  install(f.options);
  assert.equal(json(f.statePath).skills[manual], undefined);
  assert.equal(leaves(json(f.settings)).length, 1);
  uninstall(f.options);
  assert.equal(fs.existsSync(f.settings), false);
  assert.equal(fs.readFileSync(path.join(manual, 'scripts/claude_activation_hook.mjs'), 'utf8'), runtime);
});

test('a v1 installation upgrades to native hook ownership without a forced state migration', t => {
  const f = fixture(t);
  fs.unlinkSync(path.join(f.payloadRoot, 'scripts/claude_activation_hook.mjs'));
  install(f.options);
  assert.equal(json(f.statePath).nativeHooks, undefined);
  write(path.join(f.payloadRoot, 'scripts/claude_activation_hook.mjs'), runtime);
  install(f.options);
  assert.equal(json(f.statePath).version, 1);
  assert.equal(leaves(json(f.settings)).length, 1);
});

test('removing hook runtime from an owned payload unregisters it rather than leaving a broken command', t => {
  const f = fixture(t);
  install(f.options);
  fs.unlinkSync(path.join(f.payloadRoot, 'scripts/claude_activation_hook.mjs'));
  install(f.options);
  assert.equal(fs.existsSync(f.settings), false);
  assert.equal(json(f.statePath).nativeHooks, undefined);
});

test('existing disableAllHooks remains in force and is reported rather than silently overridden', t => {
  const f = fixture(t);
  write(f.settings, '{"disableAllHooks":true,"model":"user-model"}');
  const result = install(f.options);
  assert.equal(result.agents[0].nativeHookStatus, 'configured-disabled');
  assert.equal(json(f.settings).disableAllHooks, true);
  assert.equal(json(f.settings).model, 'user-model');
  uninstall(f.options);
  assert.equal(fs.readFileSync(f.settings, 'utf8'), '{"disableAllHooks":true,"model":"user-model"}');
});
