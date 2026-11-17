#!/usr/bin/env node
/** Native Claude UserPromptSubmit activation. No prompt or inference is sent. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawn, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROVIDERS = ['claude', 'agy', 'codex', 'gemini'];
const ID = /^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$/;
const TTL = 5 * 60_000;
const MAX_INPUT = 256 * 1024;
const MAX_CONTEXT = 9_500;
const HASH = value => crypto.createHash('sha256').update(value).digest('hex');
const FALLBACK_POLICY = [
  'Use the installed dynamic-model-router skill before the first substantive action.',
  'The machine provider snapshot below was collected by read-only discovery; do not search only the current MCP tools and assume other installed providers cannot help.',
  'Identify the task capability, then inspect actual current-host tool schemas. A provider image flag is discovery-only until a callable output interface or supported bridge exists.',
  'For multiple qualified image/tool routes, ask the user to choose before generation. With only discovery-only routes, offer a clearly labeled handoff/setup choice; never invent two ready generators.',
  'Do not recommend unrelated connector installation or claim exhaustive search/account failure without evidence. Preserve model/effort locks. Never send artifact work to the text-only CLI dispatcher.',
].join('\n');

function stateDirectory(env, home, platform = process.platform) {
  if (env.XDG_STATE_HOME) return path.join(env.XDG_STATE_HOME, 'dynamic-model-router');
  if (platform === 'win32' && env.LOCALAPPDATA) return path.join(env.LOCALAPPDATA, 'dynamic-model-router');
  return path.join(home, '.local', 'state', 'dynamic-model-router');
}

function executableFingerprint(name, env, cwd) {
  const suffixes = process.platform === 'win32' ? (env.PATHEXT || '.EXE;.CMD;.BAT').split(';') : [''];
  for (const directory of (env.PATH || '').split(path.delimiter)) {
    for (const suffix of suffixes) {
      const file = path.resolve(cwd, directory || '.', name + suffix);
      try {
        fs.accessSync(file, fs.constants.X_OK);
        const real = fs.realpathSync(file);
        const stat = fs.statSync(real);
        if (stat.isFile()) return [real, stat.size, stat.mtimeMs];
      } catch {}
    }
  }
  return null;
}

function fingerprint(files, env, cwd, stateDir, skillHash) {
  const stat = file => {
    try { const s = fs.statSync(file); return [file, s.size, s.mtimeMs]; }
    catch { return [file, null]; }
  };
  return HASH(JSON.stringify({
    version: 1, skillHash, platform: process.platform,
    sources: files.map(stat),
    python: env.DYNAMIC_MODEL_ROUTER_PYTHON || null,
    configuration_roots: Object.fromEntries(['CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'GEMINI_CLI_HOME', 'XDG_CONFIG_HOME']
      .map(name => [name, typeof env[name] === 'string' ? env[name] : null])),
    executables: ['python3', 'python', 'claude', 'agy', 'codex', 'gemini'].map(name => executableFingerprint(name, env, cwd)),
    onboarding: stat(path.join(stateDir, 'state.json')),
  }));
}

export function loadActivationPolicy(skillPath) {
  try {
    const bytes = fs.readFileSync(skillPath);
    if (bytes.length > 256_000) return {text: FALLBACK_POLICY, source: 'fallback', sha256: null};
    const text = bytes.toString('utf8');
    const begin = '<!-- claude-activation:begin -->', end = '<!-- claude-activation:end -->';
    const start = text.indexOf(begin), finish = text.indexOf(end, start + begin.length);
    const policy = start >= 0 && finish > start ? text.slice(start + begin.length, finish).trim() : '';
    return {
      text: policy && policy.length <= 4_000 ? policy : FALLBACK_POLICY,
      source: policy && policy.length <= 4_000 ? 'installed_skill_marker' : 'fallback',
      sha256: HASH(bytes),
    };
  } catch {
    return {text: FALLBACK_POLICY, source: 'fallback', sha256: null};
  }
}

function validId(value) { return typeof value === 'string' && ID.test(value); }

export function compactInventory(raw) {
  if (!raw || !Array.isArray(raw.providers)) throw new Error('invalid_inventory');
  const providers = [];
  for (const id of PROVIDERS) {
    const record = raw.providers.find(item => item && item.id === id);
    if (!record) continue;
    const models = (Array.isArray(record.models) ? record.models : []).filter(item => item && validId(item.id || item.model));
    const caps = record.native_capabilities;
    const native = caps && caps.status === 'advertised' && caps.scope === 'provider';
    const auth = record.authentication && record.authentication.status;
    providers.push({
      provider: id, cli_detected: record.available === true,
      text_adapter_ready: record.dispatch_ready === true,
      authentication: ['authenticated', 'missing'].includes(auth) ? auth : 'unknown',
      advertised_models: models.slice(0, 4).map(item => ({
        id: item.id || item.model,
        efforts: (Array.isArray(item.supported_efforts) ? item.supported_efforts : []).filter(validId).slice(0, 8),
      })),
      advertised_model_count: models.length,
      native_image_generation: native && typeof caps.image_generation === 'boolean' ? caps.image_generation : null,
      native_capability_scope: native ? 'provider_metadata_only' : 'unknown',
      artifact_dispatch_verified: false,
    });
  }
  const result = {providers, inference_sent: false, host_image_tools: 'not_observed_by_hook'};
  const onboarding = raw.onboarding;
  if (onboarding && typeof onboarding.question_required === 'boolean') {
    result.onboarding_question_required = onboarding.question_required;
    result.onboarding_answer = ['pending', 'additional', 'no-additional', 'not_asked'].includes(onboarding.answer) ? onboarding.answer : 'unknown';
  }
  // Exact IDs are never truncated into invented IDs; omit excess model entries.
  while (JSON.stringify(result).length > 4_500 && providers.some(p => p.advertised_models.length)) {
    for (const provider of [...providers].reverse()) {
      if (provider.advertised_models.length) { provider.advertised_models.pop(); break; }
    }
  }
  return result;
}

export function installedImageBridge(snapshot, scriptPath) {
  const codex = snapshot?.providers?.find(provider => provider.provider === 'codex');
  try {
    const stat = fs.lstatSync(scriptPath);
    if (!stat.isFile() || stat.isSymbolicLink()) return {status: 'unavailable', reason: 'image_bridge_not_installed'};
  } catch { return {status: 'unavailable', reason: 'image_bridge_not_installed'}; }
  return {
    status: 'installed_probe_required', route: 'codex-native-image', provider: 'codex',
    script: scriptPath, capability: 'image_generation', selection_required: true,
    path_cli_detected: codex?.cli_detected === true, runtime_discovery: 'probe_checks_path_and_supported_app_bundles',
    account_access_tested: false, runtime_verified: false, image_backend_model: 'not_exposed',
  };
}

function processSnapshot() {
  try {
    const result = spawnSync('ps', ['-axo', 'pid=,ppid=,pgid=,lstart='], {
      encoding: 'utf8', timeout: 750, maxBuffer: 1_000_000, windowsHide: true,
    });
    if (result.status !== 0) return [];
    return result.stdout.split('\n').flatMap(line => {
      const match = /^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.+?)\s*$/.exec(line);
      return match ? [{pid: Number(match[1]), parent: Number(match[2]), group: Number(match[3]), start: match[4]}] : [];
    });
  } catch { return []; }
}

function ownedDescendants(rootPid) {
  const all = processSnapshot(), owned = new Set([rootPid]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const row of all) {
      if ((owned.has(row.parent) || row.group === rootPid) && !owned.has(row.pid)) {
        owned.add(row.pid); changed = true;
      }
    }
  }
  return all.filter(row => owned.has(row.pid));
}

function signalOwned(rows, signal) {
  const current = new Map(processSnapshot().map(row => [row.pid, row]));
  const alive = rows.flatMap(row => {
    const present = current.get(row.pid);
    // A later recycled PID is not our subprocess. Reparented descendants still
    // match their creation identity, including those in a new session/group.
    return present && present.start === row.start ? [present] : [];
  });
  const aliveIds = new Set(alive.map(row => row.pid)), groups = new Set();
  for (const row of [...alive].reverse()) {
    if (aliveIds.has(row.group) && !groups.has(row.group)) {
      groups.add(row.group);
      try { process.kill(-row.group, signal); } catch {}
    }
    try { process.kill(row.pid, signal); } catch {}
  }
}

export function runBounded(executable, args, {timeoutMs, env, cwd, maxOutput = 2_000_000} = {}) {
  return new Promise(resolve => {
    let child, output = [], length = 0, stderr = [], errorLength = 0, cause = null, escalation, pipeDeadline;
    let finished = false, closed = false, terminationDone = false, exitCode = null, processReason = null;
    const settle = () => {
      if (finished) return;
      finished = true; clearTimeout(timer); clearTimeout(escalation); clearTimeout(pipeDeadline);
      resolve({ok: !cause && exitCode === 0, reason: cause || processReason || (exitCode === 0 ? null : 'metadata_process_error'),
        stdout: Buffer.concat(output).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8')});
    };
    const terminate = reason => {
      if (cause) return;
      cause = reason;
      const owned = process.platform !== 'win32' ? ownedDescendants(child.pid) : [];
      if (process.platform !== 'win32') {
        signalOwned(owned, 'SIGTERM');
        try { process.kill(-child.pid, 'SIGTERM'); } catch {}
      } else {
        // Run tree cleanup while the parent still exists. Killing the parent
        // first prevents taskkill from discovering a new-session descendant.
        try { spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], {stdio: 'ignore', timeout: 1_000, windowsHide: true}); } catch {}
        try { child.kill(); } catch {}
      }
      escalation = setTimeout(() => {
        if (process.platform !== 'win32') signalOwned(owned, 'SIGKILL');
        try { child.kill('SIGKILL'); } catch {}
        terminationDone = true;
        if (closed) settle();
        else pipeDeadline = setTimeout(() => {
          child.stdout.destroy(); child.stderr.destroy(); settle();
        }, 250);
      }, 200);
    };
    try {
      child = spawn(executable, args, {env, cwd, shell: false, detached: process.platform !== 'win32',
        windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
    } catch { resolve({ok: false, reason: 'process_unavailable'}); return; }
    const timer = setTimeout(() => terminate('metadata_timeout'), Math.max(1, timeoutMs || 30_000));
    child.stdout.on('data', bytes => {
      length += bytes.length;
      if (length > maxOutput) { if (!cause) terminate('metadata_output_limit'); }
      else output.push(bytes);
    });
    child.stderr.on('data', bytes => {
      errorLength += bytes.length;
      if (errorLength <= 16_384) stderr.push(bytes);
      else if (!cause) terminate('metadata_output_limit');
    });
    const complete = (code, reason) => {
      closed = true; exitCode = code; processReason = reason;
      clearTimeout(timer);
      // Keep descendant escalation alive even after the metadata parent exits.
      if (!cause || terminationDone) settle();
    };
    child.on('error', () => complete(null, 'process_unavailable'));
    child.on('close', code => complete(code));
  });
}

async function discover(options, remaining) {
  // The fixed helper emits ensure_ascii=False JSON (including localized
  // onboarding text). Do not inherit a terminal's ASCII/legacy output codec.
  const pythonOptions = {...options, env: {...options.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1'}};
  const choices = options.env.DYNAMIC_MODEL_ROUTER_PYTHON ? [options.env.DYNAMIC_MODEL_ROUTER_PYTHON] : ['python3', 'python'];
  let python, versionIssue;
  for (const candidate of choices) {
    const version = await runBounded(candidate, ['--version'], {
      ...pythonOptions, timeoutMs: Math.min(5_000, remaining()), maxOutput: 4_000,
    });
    if (['metadata_timeout', 'metadata_output_limit'].includes(version.reason)) versionIssue = version.reason;
    const match = /Python\s+(\d+)\.(\d+)/.exec((version.stdout || '') + (version.stderr || ''));
    if (version.ok && match && Number(match[1]) === 3 && Number(match[2]) >= 9) { python = candidate; break; }
  }
  if (!python) return {status: 'unavailable', reason: remaining() <= 0 ? 'metadata_timeout' : versionIssue || 'python_3_9_required'};
  if (remaining() <= 0) return {status: 'unavailable', reason: 'metadata_timeout'};
  const raw = await runBounded(python, [options.helperPath, 'discover', '--models'], {
    ...pythonOptions, timeoutMs: remaining(),
  });
  if (!raw.ok) return {status: 'unavailable', reason: raw.reason};
  try { return {status: 'available', snapshot: compactInventory(JSON.parse(raw.stdout))}; }
  catch { return {status: 'unavailable', reason: 'invalid_inventory'}; }
}

function readCache(file, key, now) {
  try {
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 32_000) return null;
    const cached = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (cached.schema_version !== 1 || cached.key !== key || !Number.isFinite(cached.created_at)
        || cached.created_at > now + 5_000 || !cached.snapshot || !Array.isArray(cached.snapshot.providers)) return null;
    const snapshot = cached.snapshot;
    const clean = compactInventory({providers: snapshot.providers.map(p => ({
      id: p.provider, available: p.cli_detected, dispatch_ready: p.text_adapter_ready,
      authentication: {status: p.authentication}, models: Array.isArray(p.advertised_models)
        ? p.advertised_models.map(m => ({id: m.id, supported_efforts: m.efforts})) : [],
      native_capabilities: {status: p.native_capability_scope === 'provider_metadata_only' ? 'advertised' : 'unknown',
        scope: 'provider', image_generation: p.native_image_generation},
    })), onboarding: {question_required: snapshot.onboarding_question_required, answer: snapshot.onboarding_answer}});
    for (const provider of clean.providers) {
      const stored = snapshot.providers.find(item => item.provider === provider.provider);
      if (Number.isInteger(stored?.advertised_model_count) && stored.advertised_model_count >= provider.advertised_models.length
          && stored.advertised_model_count <= 1_000) provider.advertised_model_count = stored.advertised_model_count;
    }
    return {...cached, snapshot: clean};
  } catch { return null; }
}

function writeCache(file, value) {
  let temp;
  try {
    fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
    try { if (fs.lstatSync(file).isSymbolicLink()) return; } catch {}
    temp = path.join(path.dirname(file), '.claude-activation-' + process.pid + '-' + crypto.randomBytes(8).toString('hex'));
    fs.writeFileSync(temp, JSON.stringify(value), {mode: 0o600, flag: 'wx'});
    fs.renameSync(temp, file); temp = undefined;
  } catch {} finally { if (temp) try { fs.unlinkSync(temp); } catch {} }
}

function lockCache(file, now) {
  const lock = file + '.lock';
  try {
    fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
    const owner = JSON.stringify({pid: process.pid, created_at: now, token: crypto.randomBytes(16).toString('hex')});
    let descriptor;
    try { descriptor = fs.openSync(lock, 'wx', 0o600); }
    catch (error) {
      if (error.code !== 'EEXIST') return null;
      const stat = fs.lstatSync(lock);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 1_024) return null;
      const bytes = fs.readFileSync(lock, 'utf8'), previous = JSON.parse(bytes);
      if (!Number.isInteger(previous.pid) || previous.pid <= 0 || !Number.isFinite(previous.created_at)
          || now - previous.created_at <= 60_000) return null;
      try { process.kill(previous.pid, 0); return null; }
      catch (error) { if (error.code !== 'ESRCH') return null; }
      if (fs.readFileSync(lock, 'utf8') !== bytes) return null;
      fs.unlinkSync(lock);
      descriptor = fs.openSync(lock, 'wx', 0o600);
    }
    fs.writeFileSync(descriptor, owner); fs.closeSync(descriptor);
    return () => { try { if (fs.readFileSync(lock, 'utf8') === owner) fs.unlinkSync(lock); } catch {} };
  } catch { return null; }
}

function audit(file, value) {
  if (!file) return;
  try {
    const destination = path.resolve(file);
    fs.mkdirSync(path.dirname(destination), {recursive: true, mode: 0o700});
    try { const stat = fs.lstatSync(destination); if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 1_000_000) return; } catch {}
    const descriptor = fs.openSync(destination, fs.constants.O_CREAT | fs.constants.O_APPEND | fs.constants.O_WRONLY | (fs.constants.O_NOFOLLOW || 0), 0o600);
    fs.fchmodSync(descriptor, 0o600);
    fs.writeSync(descriptor, JSON.stringify(value) + '\n'); fs.closeSync(descriptor);
  } catch {}
}

export async function activationHook(input, supplied = {}) {
  if (!input || input.hook_event_name !== 'UserPromptSubmit') return {};
  const env = supplied.env || process.env, home = supplied.home || os.homedir();
  const helperPath = supplied.helperPath || path.join(HERE, 'cross_cli_router.py');
  const skillPath = supplied.skillPath || path.resolve(HERE, '..', 'SKILL.md');
  const cwd = path.dirname(helperPath), stateDir = stateDirectory(env, home);
  const cacheFile = supplied.cacheFile || path.join(stateDir, 'claude-activation-cache.json');
  const now = supplied.now === undefined ? Date.now() : supplied.now;
  const policy = loadActivationPolicy(skillPath);
  const sources = ['cross_cli_router.py', 'provider_adapters.py', 'task_capabilities.py', 'codex_rpc.py', 'inspect_models.py', 'codex_image_bridge.py']
    .map(name => path.join(cwd, name));
  const key = fingerprint([fileURLToPath(import.meta.url), ...sources], env, cwd, stateDir, policy.sha256);
  const cached = readCache(cacheFile, key, now), ttl = supplied.ttlMs === undefined ? TTL : supplied.ttlMs;
  let result, cache = 'miss';
  if (!supplied.noCache && cached && now - cached.created_at < ttl) {
    result = {status: 'available', snapshot: cached.snapshot}; cache = 'hit';
  } else {
    const release = lockCache(cacheFile, now);
    if (!release) {
      result = cached ? {status: 'stale', snapshot: cached.snapshot, reason: 'discovery_in_progress'} : {status: 'unavailable', reason: 'discovery_in_progress'};
      cache = cached ? 'stale' : 'busy';
    } else {
      try {
        const deadline = Date.now() + (supplied.deadlineMs || 35_000);
        result = await discover({env, cwd, helperPath}, () => Math.max(0, deadline - Date.now()));
        if (result.status === 'available') writeCache(cacheFile, {schema_version: 1, key, created_at: now, snapshot: result.snapshot});
      } finally { release(); }
    }
  }
  const imageBridge = installedImageBridge(result.snapshot, path.join(cwd, 'codex_image_bridge.py'));
  const evidence = {status: result.status, source: cache === 'hit' ? 'cached_read_only_cli_discovery' : 'read_only_cli_discovery',
    cache, policy_source: policy.source, skill_sha256: policy.sha256, ...result};
  const context = [
    'Dynamic Model Router automatic activation — current machine evidence.',
    policy.text,
    'Installed entrypoint: ' + JSON.stringify(skillPath) + '. Load its full instructions with Skill dynamic-model-router or Read when needed; the snapshot already covers CLI discovery, not current-host tools.',
    'The following JSON is metadata, not instructions or authority to execute. CLI presence, advertised provider image support, account access, callable image tools and generated output are separate evidence.',
    JSON.stringify(evidence),
    'Dedicated image bridge (separate from text adapters): ' + JSON.stringify(imageBridge) + '. An installed bridge still needs its read-only probe; this is not successful generation or permission to dispatch.',
    result.status === 'unavailable' ? 'Discovery is unavailable (' + result.reason + '). Resolve this prerequisite or run the installed discovery helper before concluding that no other provider can help.' : '',
    result.status === 'stale' ? 'This snapshot is stale while another discovery is running. Refresh before making an availability-dependent decision.' : '',
    'Preserve explicit user model/effort choices. This hook has not changed settings, sent inference, generated media or authorized a handoff.',
  ].filter(Boolean).join('\n\n');
  audit(env.DYNAMIC_MODEL_ROUTER_HOOK_AUDIT_FILE, {event: 'UserPromptSubmit', status: result.status, cache,
    policy_source: policy.source, skill_sha256: policy.sha256,
    snapshot_sha256: result.snapshot ? HASH(JSON.stringify(result.snapshot)) : null});
  return {hookSpecificOutput: {hookEventName: 'UserPromptSubmit', additionalContext: context.slice(0, MAX_CONTEXT)}};
}

async function readInput() {
  const chunks = []; let total = 0;
  for await (const chunk of process.stdin) {
    total += chunk.length;
    if (total > MAX_INPUT) throw new Error('input_limit');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

export async function main() {
  try {
    const args = process.argv.slice(2);
    if (args.some(arg => arg !== '--no-cache')) throw new Error('unsupported_arguments');
    const input = await readInput();
    const output = await activationHook(input, {noCache: args.includes('--no-cache')});
    process.stdout.write(JSON.stringify(output) + '\n');
  } catch {
    // Hook failure must not block the original user prompt or invent a snapshot.
    process.stdout.write(JSON.stringify({hookSpecificOutput: {hookEventName: 'UserPromptSubmit',
      additionalContext: FALLBACK_POLICY + '\nAutomatic CLI discovery is unavailable; use the installed helper and report that limitation before selecting a provider.'}}) + '\n');
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();

