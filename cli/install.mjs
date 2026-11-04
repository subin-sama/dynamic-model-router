import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { resolveAdapters } from './adapters.mjs';

export const BEGIN = '<!-- dynamic-model-router:begin -->';
export const END = '<!-- dynamic-model-router:end -->';
const NAME = 'dynamic-model-router';
const PAYLOAD = ['SKILL.md', 'LICENSE', 'README.md', 'VALIDATION.md', 'agents', 'references', 'scripts', 'assets'];
const DEFAULT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const same = (a, b) => a === null ? b === null : b !== null && a.equals(b);

function hasSkillName(bytes) {
  const frontmatter = /^(?:\uFEFF)?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(bytes.toString('utf8'));
  return Boolean(frontmatter && /^name:\s*(?:dynamic-model-router|"dynamic-model-router"|'dynamic-model-router')\s*$/m.test(frontmatter[1]));
}

function exists(file) {
  try { fs.lstatSync(file); return true; } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

function actualPath(file) {
  let cursor = path.resolve(file);
  const tail = [];
  while (!exists(cursor)) {
    const parent = path.dirname(cursor);
    if (parent === cursor) throw new Error(`Cannot resolve destination: ${file}`);
    tail.unshift(path.basename(cursor));
    cursor = parent;
  }
  return path.join(fs.realpathSync(cursor), ...tail);
}

function snapshot(file) {
  if (!exists(file)) return { bytes: null, mode: 0o600 };
  const stat = fs.lstatSync(file);
  if (!stat.isFile()) throw new Error(`Expected a regular file: ${file}`);
  return { bytes: fs.readFileSync(file), mode: stat.mode & 0o777 };
}

function executable(name, env) {
  const extensions = process.platform === 'win32' ? (env.PATHEXT || '.EXE;.CMD;.BAT').split(';') : [''];
  return (env.PATH || '').split(path.delimiter).some(dir => extensions.some(extension => {
    try { fs.accessSync(path.join(dir, name + extension), fs.constants.X_OK); return true; }
    catch { return false; }
  }));
}

function payloadFiles(root) {
  const files = new Map();
  const walk = relative => {
    const source = path.join(root, relative);
    if (!exists(source)) return;
    const stat = fs.lstatSync(source);
    if (stat.isSymbolicLink()) throw new Error(`The packaged payload contains a symlink: ${relative}`);
    if (stat.isDirectory()) {
      for (const name of fs.readdirSync(source).sort()) walk(path.join(relative, name));
    } else if (stat.isFile()) {
      files.set(relative, { bytes: fs.readFileSync(source), mode: stat.mode & 0o777 });
    } else throw new Error(`Unsupported payload entry: ${relative}`);
  };
  for (const relative of PAYLOAD) walk(relative);
  if (!files.has('SKILL.md') || !files.has('LICENSE')) throw new Error('The package is missing SKILL.md or LICENSE');
  if (!hasSkillName(files.get('SKILL.md').bytes)) {
    throw new Error('The packaged skill name is invalid');
  }
  return files;
}

function validSkill(directory) {
  try {
    if (!fs.statSync(directory).isDirectory()) return false;
    return hasSkillName(fs.readFileSync(path.join(directory, 'SKILL.md')));
  } catch { return false; }
}

function selectedAdapters(options, previous, uninstalling) {
  const home = path.resolve(options.home || os.homedir());
  const env = options.env || (options.home ? {} : process.env);
  const adapters = options.adapters || resolveAdapters({ home, env, hasExecutable: name => executable(name, env) });
  let ids = options.agents;
  if (typeof ids === 'string') ids = ids.split(',').filter(Boolean);
  if (!ids || !ids.length) ids = uninstalling ? Object.keys(previous.agents) : adapters.filter(item => item.detected).map(item => item.id);
  if (ids.includes('all')) ids = adapters.map(item => item.id);
  ids = [...new Set(ids)];
  for (const id of ids) if (!adapters.some(item => item.id === id)) throw new Error(`Unsupported agent: ${id}`);
  const targets = adapters.filter(item => ids.includes(item.id));
  if (!targets.length && !uninstalling) throw new Error('No supported agents detected. Use --agents all or select supported agent IDs explicitly.');
  for (const target of targets) if (!uninstalling && target.blockedReason) throw new Error(`${target.label}: ${target.blockedReason}`);
  return { home, targets, allAdapters: adapters };
}

function assertOwnedPath(directory, relative) {
  if (actualPath(directory) !== directory) throw new Error(`An owned skill root changed its real path: ${directory}`);
  let cursor = directory;
  for (const component of relative.split(/[\\/]/)) {
    cursor = path.join(cursor, component);
    if (exists(cursor) && fs.lstatSync(cursor).isSymbolicLink()) throw new Error(`An owned skill path was replaced by a symlink: ${cursor}`);
  }
}

function loadState(home) {
  const file = actualPath(path.join(home, '.config', NAME, 'install-state.json'));
  const original = snapshot(file);
  const empty = { version: 1, agents: {}, skills: {}, instructions: {} };
  if (original.bytes === null) return { file, original, state: empty };
  let state;
  try { state = JSON.parse(original.bytes.toString('utf8')); }
  catch { throw new Error('Installer state is not valid JSON; it was not changed'); }
  if (state.version !== 1 || !state.agents || !state.skills || !state.instructions) throw new Error('Unsupported installer state; it was not changed');
  for (const owned of Object.values(state.skills)) {
    if (!owned.files || typeof owned.files !== 'object') throw new Error('Invalid owned-file metadata; no files were changed');
    for (const relative of Object.keys(owned.files)) {
      if (path.isAbsolute(relative) || relative.split(/[\\/]/).includes('..')) throw new Error('Unsafe owned-file metadata; no files were changed');
    }
  }
  return { file, original, state };
}

function occurrences(bytes, needle) {
  const result = [];
  const token = Buffer.from(needle);
  let offset = 0;
  while ((offset = bytes.indexOf(token, offset)) !== -1) { result.push(offset); offset += token.length; }
  return result;
}

function locateBlock(bytes) {
  const begins = occurrences(bytes, BEGIN);
  const ends = occurrences(bytes, END);
  if (!begins.length && !ends.length) return null;
  if (begins.length !== 1 || ends.length !== 1 || ends[0] < begins[0]) {
    throw new Error('Malformed or duplicate dynamic-model-router instruction markers; no files were changed');
  }
  let end = ends[0] + Buffer.byteLength(END);
  if (bytes.subarray(end, end + 2).equals(Buffer.from('\r\n'))) end += 2;
  else if (bytes[end] === 10) end++;
  return { start: begins[0], end, bytes: bytes.subarray(begins[0], end) };
}

function blockFor(paths, newline) {
  const entries = [...new Set(paths)].sort();
  const rendered = entries.map(file => `- ${JSON.stringify(path.join(file, 'SKILL.md'))}`).join(newline);
  return Buffer.from([
    BEGIN, '## Automatic model and effort routing', '',
    'Use the installed dynamic-model-router skill for every task in every project.',
    'Read the first available installed entrypoint below, or reuse its instructions when already loaded:',
    rendered, '',
    'Reassess model and native reasoning effort at meaningful task or phase boundaries.',
    'Apply selections only through controls this host exposes and permits. Preserve explicit user model and effort choices.',
    'Distinguish recommended, requested, applied, and runtime-verified settings accurately.',
    'Prefer supported native inline receipts in graphical Codex visualizations or Antigravity App generative UI; follow the installed references/inline-receipts.md and the host output contract. When native output is final-response-only, keep a compact text receipt at task start and show the native card with the outcome. If native rendering or its payload is unavailable, use the Markdown fallback below.',
    'At each task start, show a compact chat receipt as a Markdown blockquote with two or three short lines separated by Markdown hard breaks: a colored status indicator and bold Routing/status line, then > **Scope** · Model `value` · Effort `value`, and an optional brief reason.',
    'Use 🟦 recommended, 🟨 requested, 🟪 applied, 🟩 verified, ⚪ unchanged, 🟧 unverified, and 🟥 error beside the localized textual status; use text alone if emoji rendering is unavailable. Color supplements the label.',
    'Localize status, scope, labels, and reason to the user\'s language; keep model IDs and native effort values exact. Use a compact plain-text line if Markdown is unavailable.',
    'Identify Parent, Worker with its name, or External with its name. Update only for meaningful setting, scope, evidence, fallback, or outcome changes.',
    'Prefer native receipts when supported, otherwise this chat format and status indicators, over legacy raw bracket-log or neutral-icon examples in reused skills. Honor explicit presentation preferences; terminal and structured log formats stay unchanged.',
    'Style or animate only the receipt inside a supported native sandbox. Do not patch the host app, inject chat DOM/CSS, open a separate window, or imitate live progress with repeated messages, artificial status changes, or prerecorded spinners. Snapshot cards do not establish a live runtime subscription.',
    'Use recommended before application, requested after submission, applied after host acknowledgement, and verified only for matching runtime evidence.',
    'Use unchanged for inherited/no-change settings and unknown for unexposed values. In chat, render unexposed values with a localized "not exposed" label, combining both as "Model/effort: not exposed" when appropriate. Never invent a model or effort or claim a worker change affected the parent.',
    'Visibly report verified, unverified, or error outcomes. Qualify partial evidence; assistant chat receipts are not native app banners or guaranteed host logs.',
    'Installation does not grant a missing model-switch control or change an in-flight request.',
    END, '',
  ].join(newline), 'utf8');
}

function instructionChange(before, desiredPaths, prior) {
  const bytes = before.bytes || Buffer.alloc(0);
  const found = locateBlock(bytes);
  if (found && prior?.block && !found.bytes.equals(Buffer.from(prior.block, 'base64'))) {
    throw new Error('The managed routing block was edited; preserving it instead of overwriting user changes');
  }
  if (found && !prior && desiredPaths.length) {
    throw new Error('A routing block exists without installer ownership metadata; preserving it');
  }
  if (!desiredPaths.length) {
    if (!found) return { after: before.bytes, record: null };
    let prefix = bytes.subarray(0, found.start);
    if (prior?.separator && prior?.prefixHash) {
      const separator = Buffer.from(prior.separator, 'base64');
      if (prefix.length >= separator.length && prefix.subarray(-separator.length).equals(separator)
          && hash(prefix.subarray(0, prefix.length - separator.length)) === prior.prefixHash) {
        prefix = prefix.subarray(0, prefix.length - separator.length);
      }
    }
    const after = Buffer.concat([prefix, bytes.subarray(found.end)]);
    return { after: !after.length && prior?.originalExisted === false ? null : after, record: null };
  }
  const newline = bytes.includes(Buffer.from('\r\n')) ? '\r\n' : '\n';
  const block = blockFor(desiredPaths, newline);
  if (found) {
    return { after: Buffer.concat([bytes.subarray(0, found.start), block, bytes.subarray(found.end)]),
      record: { ...prior, block: block.toString('base64'), originalExisted: prior?.originalExisted ?? before.bytes !== null } };
  }
  const ending = bytes.subarray(Math.max(0, bytes.length - 4)).toString('utf8');
  const separator = !bytes.length || /(?:\r?\n){2}$/.test(ending) ? '' : /\n$/.test(ending) ? newline : newline + newline;
  return { after: Buffer.concat([bytes, Buffer.from(separator), block]), record: {
    block: block.toString('base64'), separator: Buffer.from(separator).toString('base64'),
    prefixHash: hash(bytes), originalExisted: before.bytes !== null,
  } };
}

function addOperation(operations, file, after, kind, mode) {
  const before = snapshot(file);
  const operation = { file, before: before.bytes, after, kind, mode: mode ?? before.mode };
  const existing = operations.get(file);
  if (existing && !same(existing.after, after)) throw new Error(`Conflicting changes target the same file: ${file}`);
  if (!same(before.bytes, after)) operations.set(file, operation);
}

function ensureParent(file, made) {
  const missing = [];
  let dir = path.dirname(file);
  while (!exists(dir)) { missing.push(dir); dir = path.dirname(dir); }
  if (!fs.statSync(dir).isDirectory()) throw new Error(`Parent is not a directory: ${dir}`);
  for (const item of missing.reverse()) { fs.mkdirSync(item); made.push(item); }
}

function atomicWrite(file, bytes, mode, made, expected) {
  ensureParent(file, made);
  if (actualPath(file) !== file) throw new Error(`A destination changed its real path: ${file}`);
  const temporary = path.join(path.dirname(file), `.${NAME}-${process.pid}-${crypto.randomBytes(8).toString('hex')}.tmp`);
  let descriptor;
  try {
    descriptor = fs.openSync(temporary, 'wx', mode);
    fs.writeFileSync(descriptor, bytes);
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor); descriptor = undefined;
    fs.chmodSync(temporary, mode);
    if (actualPath(file) !== file || (expected !== undefined && !same(snapshot(file).bytes, expected))) {
      throw new Error(`A destination changed during installation: ${file}`);
    }
    fs.renameSync(temporary, file);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
    if (exists(temporary)) fs.unlinkSync(temporary);
  }
}

function assertSnapshot(operation) {
  if (actualPath(operation.file) !== operation.file) throw new Error(`A destination changed its real path: ${operation.file}`);
  if (!same(snapshot(operation.file).bytes, operation.before)) throw new Error(`A destination changed during installation: ${operation.file}`);
}

function commit(operations, stateDirectory, options) {
  const made = [], completed = [], backups = [];
  for (const operation of operations) assertSnapshot(operation);
  try {
    for (const operation of operations) {
      assertSnapshot(operation);
      if (operation.kind === 'instruction' && operation.before !== null) {
        const backup = path.join(stateDirectory, 'backups', `${hash(Buffer.from(operation.file)).slice(0, 12)}-${hash(operation.before)}.bak`);
        if (exists(backup)) {
          if (!fs.readFileSync(backup).equals(operation.before)) throw new Error('An instruction backup conflicts with its content hash');
        } else atomicWrite(backup, operation.before, 0o600, made, null);
        backups.push(backup);
      }
      options.beforeWrite?.(operation, completed.length);
      assertSnapshot(operation);
      if (operation.after === null) fs.unlinkSync(operation.file);
      else atomicWrite(operation.file, operation.after, operation.mode, made, operation.before);
      completed.push(operation);
    }
  } catch (error) {
    const conflicts = [];
    for (const operation of completed.reverse()) {
      try {
        if (!same(snapshot(operation.file).bytes, operation.after)) { conflicts.push(operation.file); continue; }
        if (operation.before === null) fs.unlinkSync(operation.file);
        else atomicWrite(operation.file, operation.before, operation.mode, made, operation.after);
      } catch { conflicts.push(operation.file); }
    }
    for (const dir of [...made].reverse()) { try { fs.rmdirSync(dir); } catch {} }
    if (conflicts.length) throw new Error(`${error.message}; rollback preserved concurrent changes in: ${conflicts.join(', ')}`);
    throw error;
  }
  return backups;
}

function plan(options, removing) {
  const home = path.resolve(options.home || os.homedir());
  const loaded = loadState(home);
  const previous = loaded.state;
  const state = structuredClone(previous);
  const { targets, allAdapters } = selectedAdapters(options, previous, removing);
  for (const [directory, owned] of Object.entries(previous.skills)) {
    for (const relative of Object.keys(owned.files)) assertOwnedPath(directory, relative);
  }
  const operations = new Map();
  const results = [];
  const payload = removing ? null : payloadFiles(path.resolve(options.payloadRoot || DEFAULT_ROOT));
  const plannedSkills = new Map();
  const existingSelections = removing ? [] : allAdapters.map(adapter => {
    const candidate = adapter.skillPaths.map(file => path.resolve(file)).find(exists);
    return { candidates: adapter.skillPaths.map(file => actualPath(file)), selected: candidate ? actualPath(candidate) : null };
  });
  for (const target of targets) {
    if (removing) {
      const entry = state.agents[target.id];
      if (entry) delete state.agents[target.id];
      results.push({ id: target.id, label: target.label, status: entry ? 'removed' : 'not-installed', ...(entry || {}), notes: target.notes || [] });
      continue;
    }
    const candidates = target.skillPaths.map(file => path.resolve(file));
    let chosen = candidates.find(exists);
    let status;
    if (chosen) {
      if (!validSkill(chosen)) throw new Error(`Existing skill destination is not a valid ${NAME} skill: ${chosen}`);
      chosen = actualPath(chosen);
      status = previous.skills[chosen] ? 'updated' : 'reused-existing';
    } else {
      chosen = candidates.map(file => actualPath(file)).find(file => plannedSkills.has(file));
      if (!chosen) {
        chosen = candidates.map(file => actualPath(file)).find(candidate => !existingSelections.some(
          other => other.selected !== null && other.selected !== candidate && other.candidates.includes(candidate)));
      }
      if (!chosen) throw new Error(`Installing ${target.label} would create a duplicate skill visible to another configured agent`);
      status = 'installed';
    }
    if (plannedSkills.has(chosen)) status = plannedSkills.get(chosen);
    else if (status !== 'reused-existing') {
      const owned = previous.skills[chosen];
      if (owned) {
        for (const [relative, digest] of Object.entries(owned.files)) {
          const current = snapshot(path.join(chosen, relative)).bytes;
          if (current === null || hash(current) !== digest) throw new Error(`An installed skill file was edited or removed; preserving it: ${path.join(chosen, relative)}`);
        }
      }
      const files = {};
      for (const [relative, value] of payload) {
        const destination = path.join(chosen, relative);
        assertOwnedPath(chosen, relative);
        if (owned && !owned.files[relative] && exists(destination)) throw new Error(`A user file conflicts with a new payload file: ${destination}`);
        addOperation(operations, destination, value.bytes, 'skill', value.mode);
        files[relative] = hash(value.bytes);
      }
      for (const relative of Object.keys(owned?.files || {})) if (!payload.has(relative)) addOperation(operations, path.join(chosen, relative), null, 'skill');
      state.skills[chosen] = { files };
      plannedSkills.set(chosen, status);
    }
    const instructionPath = actualPath(target.instructionPath);
    state.agents[target.id] = { skillPath: chosen, instructionPath };
    results.push({ id: target.id, label: target.label, status, skillPath: chosen, instructionPath, notes: target.notes || [] });
  }
  if (!removing) {
    for (const target of targets) {
      const selected = state.agents[target.id].skillPath;
      for (const candidate of target.shadowSkillPaths || []) {
        if (!exists(candidate)) continue;
        const resolved = actualPath(candidate);
        if (resolved === selected || (previous.skills[resolved] && plannedSkills.has(resolved))) continue;
        throw new Error(`${target.label}: an existing legacy skill may take priority over the common installation: ${candidate}. `
          + 'Preserve or relocate that copy before installing, or update its installer-owned adapter in the same command. No files were changed.');
      }
    }
  }
  const instructionGroups = new Map();
  for (const entry of Object.values(state.agents)) {
    const paths = instructionGroups.get(entry.instructionPath) || [];
    paths.push(entry.skillPath); instructionGroups.set(entry.instructionPath, paths);
  }
  for (const file of new Set([...Object.keys(previous.instructions), ...instructionGroups.keys()])) {
    const before = snapshot(file);
    const change = instructionChange(before, instructionGroups.get(file) || [], previous.instructions[file]);
    addOperation(operations, file, change.after, 'instruction');
    if (change.record) state.instructions[file] = change.record;
    else delete state.instructions[file];
  }
  const preservedFiles = [];
  if (removing) {
    const referenced = new Set(Object.values(state.agents).map(entry => entry.skillPath));
    for (const [directory, owned] of Object.entries(state.skills)) {
      if (referenced.has(directory)) continue;
      for (const [relative, digest] of Object.entries(owned.files)) {
        const file = path.join(directory, relative);
        const current = snapshot(file).bytes;
        if (current !== null && hash(current) === digest) addOperation(operations, file, null, 'skill');
        else if (current !== null) preservedFiles.push(file);
      }
      delete state.skills[directory];
    }
  }
  const empty = !Object.keys(state.agents).length && !Object.keys(state.skills).length && !Object.keys(state.instructions).length;
  addOperation(operations, loaded.file, empty ? null : Buffer.from(JSON.stringify(state, null, 2) + '\n'), 'state', 0o600);
  const changes = [...operations.values()];
  const backups = options.dryRun ? [] : commit(changes, path.dirname(loaded.file), options);
  if (removing && !options.dryRun) {
    const roots = Object.keys(previous.skills);
    const directories = [...new Set(changes.filter(item => item.kind === 'skill').flatMap(item => {
      const values = [];
      const root = roots.find(candidate => item.file.startsWith(candidate + path.sep));
      if (!root) return values;
      let dir = path.dirname(item.file);
      while (dir === root || dir.startsWith(root + path.sep)) { values.push(dir); dir = path.dirname(dir); }
      return values;
    }))].sort((a, b) => b.length - a.length);
    for (const directory of directories) { try { fs.rmdirSync(directory); } catch {} }
  }
  return { action: removing ? 'uninstall' : 'install', dryRun: Boolean(options.dryRun), agents: results,
    changes: changes.map(item => ({ path: item.file, kind: item.kind, action: item.after === null ? 'remove' : item.before === null ? 'create' : 'update' })),
    backups, preservedFiles, statePath: loaded.file,
    message: removing ? 'Removed only managed routing configuration and unchanged owned skill files.' : 'Global routing instructions configured. Restart or refresh each agent. Native model-switch capability still depends on its host.' };
}

export function install(options = {}) { return plan(options, false); }
export function uninstall(options = {}) { return plan(options, true); }
