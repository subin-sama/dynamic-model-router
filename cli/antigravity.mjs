import { spawn } from 'node:child_process';
import { constants } from 'node:os';
import { fileURLToPath } from 'node:url';

export function launchAntigravity(args) {
  const script = fileURLToPath(new URL('../scripts/antigravity_parent_router.py', import.meta.url));
  const python = process.env.DYNAMIC_MODEL_ROUTER_PYTHON || 'python3';
  return new Promise((resolve, reject) => {
    const child = spawn(python, [script, ...args], { stdio: 'inherit', shell: false });
    const forward = signal => child.kill(signal);
    const interrupt = () => forward('SIGINT');
    const terminate = () => forward('SIGTERM');
    process.on('SIGINT', interrupt);
    process.on('SIGTERM', terminate);
    const cleanup = () => {
      process.off('SIGINT', interrupt);
      process.off('SIGTERM', terminate);
    };
    child.once('error', error => {
      cleanup();
      reject(new Error(error.code === 'ENOENT'
        ? 'Antigravity routing requires Python 3.9+ on PATH (python3), or DYNAMIC_MODEL_ROUTER_PYTHON set to its executable.'
        : error.message));
    });
    child.once('close', (code, signal) => {
      cleanup();
      resolve(code ?? (128 + (constants.signals[signal] || 1)));
    });
  });
}
