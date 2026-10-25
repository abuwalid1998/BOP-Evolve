// Development: run the Vite dev server and point Electron at it (hot reload in the window).
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = join(here, '..', '..', 'frontend');
const DEV_URL = 'http://localhost:5173';
const isWin = process.platform === 'win32';

const vite = spawn(isWin ? 'npm.cmd' : 'npm', ['run', 'dev', '--', '--port', '5173', '--strictPort'], {
  cwd: frontend,
  stdio: 'inherit',
  shell: isWin,
});

async function waitForVite(timeoutMs = 60000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      if ((await fetch(DEV_URL)).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('Vite dev server did not start');
}

await waitForVite();
const electronBin = (await import('electron')).default;
const electron = spawn(electronBin, ['.'], {
  cwd: join(here, '..'),
  stdio: 'inherit',
  env: { ...process.env, BOP_EVOLVE_DEV_URL: DEV_URL },
});
const stop = () => {
  vite.kill();
  electron.kill();
};
electron.on('exit', () => {
  vite.kill();
  process.exit(0);
});
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
