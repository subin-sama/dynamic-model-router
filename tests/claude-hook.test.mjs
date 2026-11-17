import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {activationHook, compactInventory, loadActivationPolicy, runBounded} from '../scripts/claude_activation_hook.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const hook = path.join(root, 'scripts/claude_activation_hook.mjs');

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'router-claude-hook-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const skill = path.join(directory, 'SKILL.md'), helper = path.join(directory, 'cross_cli_router.py');
  fs.writeFileSync(skill, '<!-- claude-activation:begin -->\nCanonical installed activation policy.\n<!-- claude-activation:end -->');
  fs.writeFileSync(helper, '# fixed discovery helper fixture\n');
  const fake = path.join(directory, 'fake-python');
  fs.writeFileSync(fake, [
    '#!/usr/bin/env node',
    'const fs=require("node:fs");',
    'const args=process.argv.slice(2);',
    'if(args[0]==="--version"){const print=()=>{process.stdout.write(process.env.FAKE_PYTHON_VERSION||"Python 3.11.9");process.exit(0);};if(process.env.FAKE_VERSION_DELAY_MS)setTimeout(print,Number(process.env.FAKE_VERSION_DELAY_MS));else print();}',
    'else {',
    'fs.appendFileSync(process.env.FAKE_CAPTURE,JSON.stringify(args)+"\\n");',
    'if(process.env.FAKE_HELPER_DELAY_MS){setTimeout(()=>process.stdout.write("{}"),Number(process.env.FAKE_HELPER_DELAY_MS));}',
    'else if(process.env.FAKE_HELPER_STDOUT){process.stdout.write(process.env.FAKE_HELPER_STDOUT);}',
    'else{process.stdout.write(fs.readFileSync(process.env.FAKE_INVENTORY,"utf8"));}',
    '}',
  ].join('\n'), {mode: 0o755});
  const inventory = {
    providers: [
      {id: 'claude', available: true, dispatch_ready: true, authentication: {status: 'authenticated', email: 'private@example.test'},
        models: [{id: 'test-model', supported_efforts: ['low', 'high'], description: 'DO NOT INJECT THIS DESCRIPTION'}]},
      {id: 'codex', available: true, dispatch_ready: true, native_capabilities: {status: 'advertised', scope: 'provider', image_generation: true},
        models: [{id: 'test-codex', supported_efforts: ['medium']}]},
      {id: 'agy', available: true, dispatch_ready: true, native_capabilities: {status: 'unknown', image_generation: true}},
      {id: 'gemini', available: false, dispatch_ready: false},
    ],
    api_key: 'never-include-this-secret', machine_key: 'private-machine', onboarding: {question_required: false, answer: 'pending'},
  };
  const invFile = path.join(directory, 'inventory.json'), capture = path.join(directory, 'calls.jsonl');
  fs.writeFileSync(invFile, JSON.stringify(inventory));
  const env = {...process.env, DYNAMIC_MODEL_ROUTER_PYTHON: fake, FAKE_INVENTORY: invFile, FAKE_CAPTURE: capture};
  delete env.DYNAMIC_MODEL_ROUTER_HOOK_AUDIT_FILE;
  return {directory, skill, helper, fake, inventory, invFile, capture, env,
    options: {env, home: directory, skillPath: skill, helperPath: helper,
      cacheFile: path.join(directory, 'state/cache.json'), deadlineMs: 10_000}};
}

function context(result) {
  assert.equal(result.hookSpecificOutput.hookEventName, 'UserPromptSubmit');
  return result.hookSpecificOutput.additionalContext;
}

test('native activation executes only the fixed metadata discovery and injects installed policy', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit', prompt: 'private task'}, f.options));
  assert.match(text, /Canonical installed activation policy/);
  assert.match(text, /installed_skill_marker/);
  assert.match(text, /"provider":"claude"/);
  assert.match(text, /"native_image_generation":true/);
  assert.match(text, /"artifact_dispatch_verified":false/);
  assert.doesNotMatch(text, /private task|private@example|never-include|DO NOT INJECT/);
  assert.deepEqual(fs.readFileSync(f.capture, 'utf8').trim().split('\n').map(JSON.parse), [[f.helper, 'discover', '--models']]);
});

test('tool availability is never fabricated from image flags or model names', () => {
  const result = compactInventory({providers: [
    {id: 'codex', available: true, dispatch_ready: true, models: [{id: 'image-super-model'}], native_capabilities: {status: 'advertised', scope: 'provider', image_generation: true}},
    {id: 'agy', available: true, native_capabilities: {status: 'unknown', scope: 'provider', image_generation: true}},
  ]});
  assert.equal(result.host_image_tools, 'not_observed_by_hook');
  assert.equal(result.providers.find(p => p.provider === 'codex').native_capability_scope, 'provider_metadata_only');
  assert.equal(result.providers.find(p => p.provider === 'codex').artifact_dispatch_verified, false);
  assert.equal(result.providers.find(p => p.provider === 'agy').native_image_generation, null);
  assert.equal(result.inference_sent, false);
});

test('fresh cache avoids a second discovery while retaining native effort data', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, now: 1_000_000});
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, now: 1_000_001}));
  assert.match(text, /"cache":"hit"/);
  assert.match(text, /"efforts":\["low","high"\]/);
  assert.equal(fs.readFileSync(f.capture, 'utf8').trim().split('\n').length, 1);
  assert.equal(fs.statSync(f.options.cacheFile).mode & 0o777, 0o600);
});

test('cache refreshes after TTL, installed policy change, or explicit no-cache', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, now: 1_000_000});
  await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, now: 1_000_002, ttlMs: 1});
  fs.appendFileSync(f.skill, '\nNew policy revision.\n');
  await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, now: 1_000_003});
  await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, now: 1_000_004, noCache: true});
  assert.equal(fs.readFileSync(f.capture, 'utf8').trim().split('\n').length, 4);
});

test('cached unknown fields never leak into prompt context', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, now: 1_000_000});
  const saved = JSON.parse(fs.readFileSync(f.options.cacheFile, 'utf8'));
  saved.snapshot.credentials = 'SHOULD_NOT_APPEAR';
  saved.snapshot.providers[0].password = 'SHOULD_NOT_APPEAR';
  fs.writeFileSync(f.options.cacheFile, JSON.stringify(saved));
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, now: 1_000_001}));
  assert.doesNotMatch(text, /SHOULD_NOT_APPEAR|credentials|password/);
});

test('changing a non-secret provider configuration root refreshes discovery', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  const env = {...f.env};
  for (const name of ['CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'GEMINI_CLI_HOME', 'XDG_CONFIG_HOME']) delete env[name];
  await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, env, now: 1_000_000});
  for (const [index, name] of ['CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'GEMINI_CLI_HOME', 'XDG_CONFIG_HOME'].entries()) {
    env[name] = path.join(f.directory, 'private-profile-' + name);
    const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, {
      ...f.options, env: {...env}, now: 1_000_001 + index,
    }));
    assert.match(text, /"cache":"miss"/);
    assert.doesNotMatch(text, /private-profile-/);
  }
  assert.equal(fs.readFileSync(f.capture, 'utf8').trim().split('\n').length, 5);
});

test('missing or old Python is an explicit prerequisite, without another provider action', async t => {
  const f = fixture(t);
  const result = await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options,
    env: {...f.env, DYNAMIC_MODEL_ROUTER_PYTHON: path.join(f.directory, 'missing-python')}});
  assert.match(context(result), /python_3_9_required/);
  assert.equal(fs.existsSync(f.capture), false);
  if (process.platform !== 'win32') {
    const old = await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options,
      env: {...f.env, FAKE_PYTHON_VERSION: 'Python 3.8.20'}, noCache: true});
    assert.match(context(old), /python_3_9_required/);
    assert.equal(fs.existsSync(f.capture), false);
  }
});

test('malformed helper output remains unavailable rather than no providers installed', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options,
    env: {...f.env, FAKE_HELPER_STDOUT: 'not-json'}}));
  assert.match(text, /"status":"unavailable"/);
  assert.match(text, /invalid_inventory/);
  assert.equal(fs.existsSync(f.options.cacheFile), false);
});

test('helper deadline is bounded and reported without raw diagnostics', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  const started = Date.now();
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, deadlineMs: 500,
    env: {...f.env, FAKE_HELPER_DELAY_MS: '10000'}}));
  assert.match(text, /metadata_timeout/);
  assert.ok(Date.now() - started < 3_000);
  assert.equal(fs.existsSync(f.options.cacheFile), false);
});

test('metadata child uses UTF-8 even when the parent terminal requests ASCII', async t => {
  const version = spawnSync('python3', ['--version'], {encoding: 'utf8'});
  if (version.status !== 0) { t.skip('Local Python 3 is unavailable'); return; }
  const f = fixture(t), parentEncoding = process.env.PYTHONIOENCODING;
  fs.writeFileSync(f.helper, [
    'import json',
    'print(json.dumps({"providers": [{"id": "codex", "available": True, "dispatch_ready": True}], "onboarding": {"question_required": False, "question_th": "ตัวอย่างภาษาไทย"}}, ensure_ascii=False))',
  ].join('\n'));
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options,
    env: {...f.env, DYNAMIC_MODEL_ROUTER_PYTHON: 'python3', PYTHONIOENCODING: 'ascii', PYTHONUTF8: '0'}}));
  assert.match(text, /"status":"available"/);
  assert.match(text, /"provider":"codex"/);
  assert.equal(process.env.PYTHONIOENCODING, parentEncoding);
});

test('a timed-out Python version probe is not mislabeled as missing Python', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, {...f.options, deadlineMs: 300,
    env: {...f.env, FAKE_VERSION_DELAY_MS: '10000'}}));
  assert.match(text, /metadata_timeout/);
  assert.doesNotMatch(text, /python_3_9_required/);
  assert.equal(fs.existsSync(f.capture), false);
});

test('timeout kills a nested-session descendant even after the metadata parent closes', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t), childFile = path.join(f.directory, 'detached-child.cjs');
  const parentFile = path.join(f.directory, 'metadata-parent.cjs');
  const heartbeat = path.join(f.directory, 'heartbeat.txt'), identity = path.join(f.directory, 'child-pid.txt');
  fs.writeFileSync(childFile, [
    'const fs=require("node:fs");',
    'fs.writeFileSync(process.argv[3],String(process.pid));',
    'process.on("SIGTERM",()=>{});',
    'setInterval(()=>fs.appendFileSync(process.argv[2],"x"),20);',
  ].join('\n'));
  fs.writeFileSync(parentFile, [
    'const {spawn}=require("node:child_process");',
    'spawn(process.execPath,[process.argv[2],process.argv[3],process.argv[4]],{detached:true,stdio:"ignore"}).unref();',
    'setInterval(()=>{},1000);',
  ].join('\n'));
  let pid;
  try {
    const result = await runBounded(process.execPath, [parentFile, childFile, heartbeat, identity],
      {timeoutMs: 500, env: process.env, cwd: f.directory});
    assert.equal(result.reason, 'metadata_timeout');
    pid = Number(fs.readFileSync(identity, 'utf8'));
    const atReturn = fs.readFileSync(heartbeat, 'utf8').length;
    await new Promise(resolve => setTimeout(resolve, 300));
    assert.equal(fs.readFileSync(heartbeat, 'utf8').length, atReturn);
  } finally {
    if (!pid && fs.existsSync(identity)) pid = Number(fs.readFileSync(identity, 'utf8'));
    if (Number.isInteger(pid) && pid > 0) try { process.kill(-pid, 'SIGKILL'); } catch {}
  }
});

test('parallel discovery uses a live lock without duplicate metadata requests', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  fs.mkdirSync(path.dirname(f.options.cacheFile), {recursive: true});
  fs.writeFileSync(f.options.cacheFile + '.lock', JSON.stringify({pid: process.pid, created_at: Date.now(), token: 'other'}));
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, f.options));
  assert.match(text, /discovery_in_progress/);
  assert.equal(fs.existsSync(f.capture), false);
  assert.equal(JSON.parse(fs.readFileSync(f.options.cacheFile + '.lock')).token, 'other');
});

test('a dead stale discovery lock recovers instead of disabling activation permanently', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  fs.mkdirSync(path.dirname(f.options.cacheFile), {recursive: true});
  fs.writeFileSync(f.options.cacheFile + '.lock', JSON.stringify({pid: 2_000_000_000, created_at: Date.now() - 120_000, token: 'stale'}));
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, f.options));
  assert.match(text, /"status":"available"/);
  assert.equal(fs.existsSync(f.options.cacheFile + '.lock'), false);
});

test('opt-in audit contains only fixed provenance metadata and owner-only permissions', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t), audit = path.join(f.directory, 'audit/log.jsonl');
  await activationHook({hook_event_name: 'UserPromptSubmit', prompt: 'PRIVATE REQUEST', cwd: 'PRIVATE PATH'},
    {...f.options, env: {...f.env, DYNAMIC_MODEL_ROUTER_HOOK_AUDIT_FILE: audit}});
  const row = JSON.parse(fs.readFileSync(audit, 'utf8'));
  assert.deepEqual(Object.keys(row).sort(), ['cache', 'event', 'policy_source', 'skill_sha256', 'snapshot_sha256', 'status']);
  assert.match(row.skill_sha256, /^[a-f0-9]{64}$/);
  assert.match(row.snapshot_sha256, /^[a-f0-9]{64}$/);
  assert.doesNotMatch(JSON.stringify(row), /PRIVATE|private@example|never-include/);
  assert.equal(fs.statSync(audit).mode & 0o777, 0o600);
});

test('non-prompt events do not discover or change anything', async t => {
  const f = fixture(t);
  assert.deepEqual(await activationHook({hook_event_name: 'PreToolUse'}, f.options), {});
  assert.equal(fs.existsSync(f.capture), false);
});

test('oversized or missing canonical fragment uses bounded fallback, never arbitrary remainder', t => {
  const f = fixture(t);
  fs.writeFileSync(f.skill, '<!-- claude-activation:begin -->' + 'x'.repeat(4_001) + '<!-- claude-activation:end -->PRIVATE REST');
  const result = loadActivationPolicy(f.skill);
  assert.equal(result.source, 'fallback');
  assert.doesNotMatch(result.text, /PRIVATE REST|xxxx/);
  assert.match(result.sha256, /^[a-f0-9]{64}$/);
});

test('large model catalogs keep exact IDs or omit them within a compact output bound', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t);
  const large = structuredClone(f.inventory);
  for (const provider of large.providers) provider.models = Array.from({length: 50}, (_, i) => ({id: 'model-' + i + '-' + 'x'.repeat(220), supported_efforts: ['low', 'high']}));
  fs.writeFileSync(f.invFile, JSON.stringify(large));
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, f.options));
  assert.ok(text.length <= 9_500);
  assert.match(text, /"advertised_model_count":50/);
});

test('bounded runner rejects output floods before unbounded buffering', async () => {
  const result = await runBounded(process.execPath, ['-e', 'process.stdout.write("x".repeat(10000))'],
    {timeoutMs: 1_000, maxOutput: 1_000, env: process.env, cwd: root});
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'metadata_output_limit');
});

test('native CLI emits a supported fallback for malformed stdin and never logs its text', t => {
  const f = fixture(t);
  const result = spawnSync(process.execPath, [hook], {input: 'PRIVATE malformed hook input', encoding: 'utf8',
    env: {...f.env, XDG_STATE_HOME: path.join(f.directory, 'xdg')}});
  assert.equal(result.status, 0, result.stderr);
  const text = context(JSON.parse(result.stdout));
  assert.match(text, /discovery is unavailable/);
  assert.doesNotMatch(text, /PRIVATE malformed/);
});

test('hook refuses a symlink cache without reading or replacing its target', {skip: process.platform === 'win32'}, async t => {
  const f = fixture(t), target = path.join(f.directory, 'target.json');
  fs.writeFileSync(target, 'PRIVATE TARGET');
  fs.mkdirSync(path.dirname(f.options.cacheFile), {recursive: true});
  fs.symlinkSync(target, f.options.cacheFile);
  const text = context(await activationHook({hook_event_name: 'UserPromptSubmit'}, f.options));
  assert.match(text, /"status":"available"/);
  assert.equal(fs.readFileSync(target, 'utf8'), 'PRIVATE TARGET');
  assert.equal(fs.lstatSync(f.options.cacheFile).isSymbolicLink(), true);
});

