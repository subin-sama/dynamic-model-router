import path from 'node:path';
import crypto from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';

export const CLAUDE_HOOK_RUNTIME = path.join('scripts', 'claude_activation_hook.mjs');
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

// Claude command hooks use the user's shell. Single quoting prevents shell
// expansion, including spaces, apostrophes, dollars and command substitutions.
export const shellQuote = value => `'${String(value).replaceAll("'", "'\"'\"'")}'`;

export function claudeHook(skillPath, node = process.execPath) {
  return { type: 'command', command: `${shellQuote(node)} ${shellQuote(path.join(skillPath, CLAUDE_HOOK_RUNTIME))}`, timeout: 45 };
}

function parse(bytes) {
  if (bytes === null) return {};
  const text = bytes.toString('utf8');
  if (!Buffer.from(text, 'utf8').equals(bytes)) throw new Error('Claude settings must be valid UTF-8; preserving the file');
  let value;
  try { value = text.replace(/^\uFEFF/, '').trim() ? JSON.parse(text.replace(/^\uFEFF/, '')) : {}; }
  catch { throw new Error('Claude settings are not valid JSON; no files were changed'); }
  if (!object(value)) throw new Error('Claude settings must be a JSON object; no files were changed');
  if (own(value, 'hooks') && !object(value.hooks)) throw new Error('Claude hooks must be an object; preserving settings');
  if (own(value.hooks || {}, 'UserPromptSubmit')) {
    const entries = value.hooks.UserPromptSubmit;
    if (!Array.isArray(entries) || entries.some(entry => !object(entry) || !Array.isArray(entry.hooks)
      || entry.hooks.some(hook => !object(hook)))) {
      throw new Error('Claude UserPromptSubmit hooks are malformed; preserving settings');
    }
  }
  return value;
}

function render(value, before) {
  const raw = before?.toString('utf8') || '';
  const newline = raw.includes('\r\n') ? '\r\n' : '\n';
  const leading = /(?:\r?\n)([\t ]+)"/.exec(raw)?.[1];
  const indent = leading && leading.length <= 8 ? leading : '  ';
  const suffix = before === null || /\r?\n$/.test(raw) ? newline : '';
  return Buffer.from((raw.startsWith('\uFEFF') ? '\uFEFF' : '')
    + JSON.stringify(value, null, indent).replaceAll('\n', newline) + suffix, 'utf8');
}

function locations(value, predicate) {
  const found = [];
  for (const [entryIndex, entry] of (value.hooks?.UserPromptSubmit || []).entries()) {
    for (const [hookIndex, hook] of entry.hooks.entries()) {
      if (predicate(hook)) found.push({ entryIndex, hookIndex });
    }
  }
  return found;
}

const related = hook => typeof hook.command === 'string' && hook.command.includes('claude_activation_hook.mjs');

/** Merge only the owned command hook; unrelated keys and hook commands survive.
 * Exact original bytes can be restored from the protected installer backup when
 * no newer settings content would be lost. No settings values enter state.
 */
export function changeClaudeHook(before, desired, prior, originalBytes = null) {
  if (!desired && !prior) return { after: before, record: null };
  if (!desired && before === null) return { after: null, record: null };
  const value = parse(before);
  const matching = prior ? locations(value, hook => isDeepStrictEqual(hook, prior.hook)) : [];
  const relatedHooks = locations(value, related);
  if (prior && (matching.length !== 1 || relatedHooks.length !== 1)) {
    if (!desired && matching.length === 0 && relatedHooks.length === 0) return { after: before, record: null };
    throw new Error('The managed Claude activation hook was edited, removed or duplicated; preserving settings');
  }
  if (!prior && relatedHooks.length) throw new Error('A Claude activation hook exists without installer ownership; preserving it');

  if (!desired) {
    const { entryIndex, hookIndex } = matching[0];
    const entries = value.hooks.UserPromptSubmit;
    entries[entryIndex].hooks.splice(hookIndex, 1);
    if (isDeepStrictEqual(entries[entryIndex], { hooks: [] })) entries.splice(entryIndex, 1);
    if (prior.createdEvent && entries.length === 0) delete value.hooks.UserPromptSubmit;
    if (prior.createdHooks && Object.keys(value.hooks).length === 0) delete value.hooks;
    const unchanged = prior.installedHash === digest(before);
    if (unchanged && prior.originalHash === null && Object.keys(value).length === 0) return { after: null, record: null };
    if (unchanged && originalBytes !== null && isDeepStrictEqual(value, parse(originalBytes))) return { after: originalBytes, record: null };
    return { after: render(value, before), record: null };
  }

  if (prior && isDeepStrictEqual(prior.hook, desired)) return { after: before, record: prior, disabled: value.disableAllHooks === true };
  let record;
  if (prior) {
    const { entryIndex, hookIndex } = matching[0];
    value.hooks.UserPromptSubmit[entryIndex].hooks[hookIndex] = desired;
    record = { ...prior, hook: desired };
  } else {
    const createdHooks = !own(value, 'hooks');
    if (createdHooks) value.hooks = {};
    const createdEvent = !own(value.hooks, 'UserPromptSubmit');
    if (createdEvent) value.hooks.UserPromptSubmit = [];
    value.hooks.UserPromptSubmit.push({ hooks: [desired] });
    record = { hook: desired, createdHooks, createdEvent, originalHash: before === null ? null : digest(before) };
  }
  const after = render(value, before);
  record.installedHash = digest(after);
  return { after, record, disabled: value.disableAllHooks === true };
}
