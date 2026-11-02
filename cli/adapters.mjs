import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const SKILL = 'dynamic-model-router';

function configPath(value, fallback, home) {
  if (!value) return fallback;
  if (value === '~') return home;
  if (value.startsWith('~/') || value.startsWith('~\\')) return path.resolve(home, value.slice(2));
  return path.resolve(value);
}

function nonemptyFile(file) {
  try { return fs.statSync(file).isFile() && fs.readFileSync(file, 'utf8').trim().length > 0; }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

export function stripJsonComments(text) {
  let result = '', quoted = false, escaped = false, line = false, block = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i], next = text[i + 1];
    if (line) {
      if (char === '\n' || char === '\r') { line = false; result += char; }
      else result += ' ';
    } else if (block) {
      if (char === '*' && next === '/') { block = false; result += '  '; i++; }
      else result += char === '\n' || char === '\r' ? char : ' ';
    } else if (quoted) {
      result += char;
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === '"') quoted = false;
    } else if (char === '"') { quoted = true; result += char; }
    else if (char === '/' && next === '/') { line = true; result += '  '; i++; }
    else if (char === '/' && next === '*') { block = true; result += '  '; i++; }
    else result += char;
  }
  return result;
}

function geminiInstruction(configDir, env, home) {
  const defaultSystem = process.platform === 'darwin'
    ? '/Library/Application Support/GeminiCli/settings.json'
    : process.platform === 'win32'
      ? path.join(env.ProgramData || env.PROGRAMDATA || 'C:\\ProgramData', 'gemini-cli/settings.json')
      : '/etc/gemini-cli/settings.json';
  const system = configPath(env.GEMINI_CLI_SYSTEM_SETTINGS_PATH, defaultSystem, home);
  const defaults = configPath(env.GEMINI_CLI_SYSTEM_DEFAULTS_PATH,
    path.join(path.dirname(system), 'system-defaults.json'), home);
  const settingsPaths = [defaults, path.join(configDir, 'settings.json'), system];
  let names = ['GEMINI.md'];
  for (const settingsPath of settingsPaths) {
    try {
      const text = fs.readFileSync(settingsPath, 'utf8').replace(/^\uFEFF/, '');
      const settings = JSON.parse(stripJsonComments(text));
      const configured = settings?.context?.fileName;
      if (configured !== undefined) names = Array.isArray(configured) ? configured : [configured];
    } catch (error) {
      if (error.code !== 'ENOENT') return {instructionPath: path.join(configDir, 'GEMINI.md'), notes: [],
        blockedReason: 'Cannot safely read Gemini settings; no instruction file will be changed.'};
    }
  }
  {
    if (!names.length || names.some(name => typeof name !== 'string' || !name.trim()
        || path.basename(name) !== name || name === '.' || name === '..' || /[\\/]/.test(name))) {
      return {instructionPath: path.join(configDir, 'GEMINI.md'), notes: [],
        blockedReason: 'Gemini context.fileName must contain supported plain instruction filenames.'};
    }
  }
  const selected = names.find(name => nonemptyFile(path.join(configDir, name))) ?? names[0];
  return {instructionPath: path.join(configDir, selected),
    notes: selected === 'GEMINI.md' ? [] : [`Using Gemini's configured context filename: ${selected}`]};
}

export function resolveAdapters({home = os.homedir(), env = process.env, hasExecutable = () => false} = {}) {
  home = path.resolve(home);
  const shared = path.join(home, '.agents', 'skills', SKILL);
  const codex = configPath(env.CODEX_HOME, path.join(home, '.codex'), home);
  const claude = configPath(env.CLAUDE_CONFIG_DIR, path.join(home, '.claude'), home);
  const geminiRoot = configPath(env.GEMINI_CLI_HOME, home, home);
  const gemini = path.join(geminiRoot, '.gemini');
  const antigravity = path.join(home, '.gemini');
  const xdg = configPath(env.XDG_CONFIG_HOME, path.join(home, '.config'), home);
  const opencode = configPath(env.OPENCODE_CONFIG_DIR, path.join(xdg, 'opencode'), home);
  const copilot = configPath(env.COPILOT_HOME, path.join(home, '.copilot'), home);
  const detected = (directory, command) => fs.existsSync(directory) || Boolean(hasExecutable(command));
  const codexOverride = path.join(codex, 'AGENTS.override.md');
  const effectiveCodex = nonemptyFile(codexOverride) ? codexOverride : path.join(codex, 'AGENTS.md');
  return [
    {id: 'codex', label: 'Codex', detected: detected(codex, 'codex'),
      instructionPath: effectiveCodex, skillPaths: [shared, path.join(codex, 'skills', SKILL)],
      notes: effectiveCodex === codexOverride ? ['Using the nonempty global AGENTS.override.md that Codex loads first.'] : []},
    {id: 'claude-code', label: 'Claude Code', detected: detected(claude, 'claude'),
      instructionPath: path.join(claude, 'CLAUDE.md'),
      skillPaths: [path.join(claude, 'skills', SKILL), shared], notes: []},
    {id: 'gemini-cli', label: 'Gemini CLI', detected: detected(gemini, 'gemini'),
      skillPaths: [path.join(geminiRoot, '.agents', 'skills', SKILL), path.join(gemini, 'skills', SKILL)],
      ...geminiInstruction(gemini, env, home)},
    {id: 'antigravity', label: 'Antigravity',
      detected: ['antigravity', 'antigravity-cli', 'antigravity-ide'].some(
        directory => fs.existsSync(path.join(antigravity, directory)))
        || Boolean(hasExecutable('agy')) || Boolean(hasExecutable('antigravity')),
      instructionPath: path.join(antigravity, 'AGENTS.md'),
      skillPaths: [path.join(antigravity, 'config', 'skills', SKILL)],
      shadowSkillPaths: [path.join(antigravity, 'antigravity-cli', 'skills', SKILL),
        path.join(antigravity, 'skills', SKILL), path.join(antigravity, 'antigravity', 'skills', SKILL)],
      notes: ['Uses the common App, CLI, and IDE global paths; Gemini CLI home overrides do not apply.']},
    {id: 'opencode', label: 'OpenCode', detected: detected(opencode, 'opencode'),
      instructionPath: path.join(opencode, 'AGENTS.md'),
      skillPaths: [shared, path.join(opencode, 'skills', SKILL)], notes: []},
    {id: 'github-copilot', label: 'GitHub Copilot CLI', detected: detected(copilot, 'copilot'),
      instructionPath: path.join(copilot, 'copilot-instructions.md'),
      skillPaths: [shared, path.join(copilot, 'skills', SKILL)], notes: []},
  ];
}

export const UNSUPPORTED_AUTOMATIC_ACTIVATION = [
  'Cursor: configure account-level User Rules in the app; this installer does not claim reliable all-project file activation.',
  'Hosted chat products and other clients without supported user-wide local instruction files require their own integration.',
];
