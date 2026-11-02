import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {resolveAdapters, stripJsonComments} from '../cli/adapters.mjs';

function fixture(t) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'router-adapters-'));
  t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  return home;
}
function write(file, text = 'Existing instructions\n') {
  fs.mkdirSync(path.dirname(file), {recursive: true});
  fs.writeFileSync(file, text);
}
function adapter(home, id, env = {}, hasExecutable = () => false) {
  return resolveAdapters({home, env, hasExecutable}).find(item => item.id === id);
}

test('default targets are six documented user-wide instruction files', t => {
  const home = fixture(t);
  const adapters = resolveAdapters({home, env: {}});
  assert.equal(adapters.length, 6);
  assert.deepEqual(adapters.map(item => path.relative(home, item.instructionPath)), [
    '.codex/AGENTS.md', '.claude/CLAUDE.md', '.gemini/GEMINI.md', '.gemini/AGENTS.md',
    '.config/opencode/AGENTS.md', '.copilot/copilot-instructions.md',
  ]);
  assert.ok(adapters.every(item => item.detected === false));
});

test('Antigravity targets common App CLI and IDE locations independently of Gemini CLI home', t => {
  const home = fixture(t);
  const custom = path.join(home, 'gemini-profile');
  const resolved = adapter(home, 'antigravity', {GEMINI_CLI_HOME: custom});
  assert.equal(resolved.instructionPath, path.join(home, '.gemini/AGENTS.md'));
  assert.deepEqual(resolved.skillPaths, [path.join(home, '.gemini/config/skills/dynamic-model-router')]);
  assert.deepEqual(resolved.shadowSkillPaths, [
    '.gemini/antigravity-cli/skills/dynamic-model-router',
    '.gemini/skills/dynamic-model-router',
    '.gemini/antigravity/skills/dynamic-model-router',
  ].map(relative => path.join(home, relative)));
  assert.equal(fs.existsSync(custom), false);
});

test('Antigravity detects current and legacy executables without creating profile files', t => {
  const home = fixture(t);
  for (const executable of ['agy', 'antigravity']) {
    assert.equal(adapter(home, 'antigravity', {}, command => command === executable).detected, true);
  }
  assert.equal(adapter(home, 'antigravity', {}, command => command === 'gemini').detected, false);
  assert.equal(fs.existsSync(path.join(home, '.gemini')), false);
});

test('Antigravity detects specific surface directories but not generic Gemini configuration', t => {
  const home = fixture(t);
  fs.mkdirSync(path.join(home, '.gemini/config'), {recursive: true});
  assert.equal(adapter(home, 'antigravity').detected, false);
  for (const directory of ['antigravity', 'antigravity-cli', 'antigravity-ide']) {
    const specific = path.join(home, '.gemini', directory);
    fs.mkdirSync(specific);
    assert.equal(adapter(home, 'antigravity').detected, true);
    fs.rmdirSync(specific);
  }
});

test('detects config directories and command availability without creating files', t => {
  const home = fixture(t);
  fs.mkdirSync(path.join(home, '.claude'));
  assert.equal(adapter(home, 'claude-code').detected, true);
  assert.equal(adapter(home, 'codex', {}, command => command === 'codex').detected, true);
  assert.equal(fs.existsSync(path.join(home, '.codex')), false);
});

test('Codex chooses a nonempty override but ignores empty or whitespace-only overrides', t => {
  const home = fixture(t);
  const override = path.join(home, '.codex/AGENTS.override.md');
  write(override, ' \n\t');
  assert.equal(adapter(home, 'codex').instructionPath, path.join(home, '.codex/AGENTS.md'));
  write(override, 'Custom override\n');
  assert.equal(adapter(home, 'codex').instructionPath, override);
});

test('respects direct Codex, Claude, Copilot, and OpenCode custom configuration roots', t => {
  const home = fixture(t);
  const env = {CODEX_HOME: path.join(home, 'codex-profile'),
    CLAUDE_CONFIG_DIR: path.join(home, 'claude-profile'), COPILOT_HOME: path.join(home, 'copilot-profile'),
    OPENCODE_CONFIG_DIR: path.join(home, 'opencode-profile'), XDG_CONFIG_HOME: path.join(home, 'xdg')};
  assert.equal(adapter(home, 'codex', env).instructionPath, path.join(env.CODEX_HOME, 'AGENTS.md'));
  assert.equal(adapter(home, 'claude-code', env).skillPaths[0], path.join(env.CLAUDE_CONFIG_DIR, 'skills/dynamic-model-router'));
  assert.equal(adapter(home, 'github-copilot', env).instructionPath, path.join(env.COPILOT_HOME, 'copilot-instructions.md'));
  assert.equal(adapter(home, 'opencode', env).instructionPath, path.join(env.OPENCODE_CONFIG_DIR, 'AGENTS.md'));
  delete env.OPENCODE_CONFIG_DIR;
  assert.equal(adapter(home, 'opencode', env).instructionPath, path.join(env.XDG_CONFIG_HOME, 'opencode/AGENTS.md'));
});

test('Gemini custom home roots both Gemini config and shared skills under that home', t => {
  const home = fixture(t);
  const custom = path.join(home, 'gemini-profile');
  const resolved = adapter(home, 'gemini-cli', {GEMINI_CLI_HOME: custom});
  assert.equal(resolved.instructionPath, path.join(custom, '.gemini/GEMINI.md'));
  assert.equal(resolved.skillPaths[0], path.join(custom, '.agents/skills/dynamic-model-router'));
});

test('Gemini honors a configured instruction filename or an existing configured candidate', t => {
  const home = fixture(t);
  const settings = path.join(home, '.gemini/settings.json');
  write(settings, JSON.stringify({context: {fileName: 'GLOBAL.md'}}));
  assert.equal(adapter(home, 'gemini-cli').instructionPath, path.join(home, '.gemini/GLOBAL.md'));
  write(settings, JSON.stringify({context: {fileName: ['AGENTS.md', 'GLOBAL.md']}}));
  write(path.join(home, '.gemini/GLOBAL.md'));
  assert.equal(adapter(home, 'gemini-cli').instructionPath, path.join(home, '.gemini/GLOBAL.md'));
});

test('Gemini malformed settings or unsafe filenames are blocked rather than silently ignored', t => {
  const home = fixture(t);
  const settings = path.join(home, '.gemini/settings.json');
  for (const text of ['{invalid', JSON.stringify({context: {fileName: '../elsewhere.md'}}),
    JSON.stringify({context: {fileName: []}})]) {
    write(settings, text);
    assert.ok(adapter(home, 'gemini-cli').blockedReason);
  }
});

test('Gemini permits comments while preserving URLs and escaped strings', t => {
  const home = fixture(t);
  write(path.join(home, '.gemini/settings.json'), `{
    // User instruction filename
    "context": {"fileName": "GLOBAL.md"}, /* Inline comment */
    "endpoint": "https://example.test/a//b",
    "sample": "quote: \\" /* remains text */"
  }`);
  const resolved = adapter(home, 'gemini-cli');
  assert.equal(resolved.blockedReason, undefined);
  assert.equal(resolved.instructionPath, path.join(home, '.gemini/GLOBAL.md'));
  assert.equal(JSON.parse(stripJsonComments('{"url":"https://example.test"}//comment')).url, 'https://example.test');
});

test('Gemini system context filenames override user and system-default choices', t => {
  const home = fixture(t);
  const system = path.join(home, 'system/settings.json');
  const defaults = path.join(home, 'system/system-defaults.json');
  write(defaults, JSON.stringify({context: {fileName: 'DEFAULT.md'}}));
  write(path.join(home, '.gemini/settings.json'), JSON.stringify({context: {fileName: 'USER.md'}}));
  write(system, JSON.stringify({context: {fileName: 'SYSTEM.md'}}));
  const env = {GEMINI_CLI_SYSTEM_SETTINGS_PATH: system, GEMINI_CLI_SYSTEM_DEFAULTS_PATH: defaults};
  assert.equal(adapter(home, 'gemini-cli', env).instructionPath, path.join(home, '.gemini/SYSTEM.md'));
  fs.unlinkSync(system);
  assert.equal(adapter(home, 'gemini-cli', env).instructionPath, path.join(home, '.gemini/USER.md'));
});

test('Gemini trailing commas remain invalid rather than being evaluated as JavaScript', t => {
  const home = fixture(t);
  write(path.join(home, '.gemini/settings.json'), '{"context":{"fileName":"GLOBAL.md",},}');
  assert.ok(adapter(home, 'gemini-cli').blockedReason);
});
