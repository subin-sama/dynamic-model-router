#!/usr/bin/env node
import { install, uninstall } from './install.mjs';

function parse(argv) {
  const options = {};
  let action = 'install';
  if (argv[0] === 'install' || argv[0] === 'uninstall') action = argv.shift();
  for (let index = 0; index < argv.length; index++) {
    const value = argv[index];
    if (value === '--help' || value === '-h') return { help: true };
    if (value === '--dry-run') options.dryRun = true;
    else if (value === '--json') options.json = true;
    else if (value === '--agents' || value === '--home') {
      const next = argv[++index];
      if (!next || next.startsWith('-')) throw new Error(`Missing value for ${value}`);
      options[value.slice(2)] = next;
    } else throw new Error(`Unknown option: ${value}`);
  }
  return { action, options };
}

try {
  const parsed = parse(process.argv.slice(2));
  if (parsed.help) {
    console.log(`Dynamic Model Router global installer

Usage: dynamic-model-router [install|uninstall] [options]

Default: install and enable routing for every task in detected supported agents.

  --agents IDS   Comma-separated agent IDs, or all verified adapters
  --dry-run      Show planned changes without writing files
  --json         Print machine-readable results
  --home PATH    Isolated home root; ignores real profile environment overrides
  --help         Show this help

Existing user instructions are preserved and backed up before changes.
Uninstall removes managed blocks and unchanged owned files only.
Closed AI services and unsupported global-rule mechanisms are not configured.
`);
  } else {
    const result = parsed.action === 'uninstall' ? uninstall(parsed.options) : install(parsed.options);
    if (parsed.options.json) console.log(JSON.stringify(result, null, 2));
    else {
      console.log(result.dryRun ? 'Dry run: no files changed.' : result.message);
      for (const agent of result.agents) {
        console.log(`${agent.label}: ${agent.status}`);
        if (agent.skillPath) console.log(`  Skill: ${agent.skillPath}`);
        if (agent.instructionPath) console.log(`  Instructions: ${agent.instructionPath}`);
        for (const note of agent.notes) console.log(`  Note: ${note}`);
      }
      for (const backup of result.backups) console.log(`Backup: ${backup}`);
      for (const file of result.preservedFiles) console.log(`Preserved modified file: ${file}`);
      if (result.dryRun) for (const change of result.changes) console.log(`${change.action}: ${change.path}`);
    }
  }
} catch (error) {
  console.error(`Installer stopped: ${error.message}`);
  process.exitCode = 1;
}
