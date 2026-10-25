// Builds the shared React UI (../frontend) and copies it into ./renderer for packaging.
// Pure Node so it works the same on Windows, macOS and Linux.
import { execSync } from 'node:child_process';
import { cpSync, existsSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frontend = join(here, '..', '..', 'frontend');
const target = join(here, '..', 'renderer');
const run = (cmd) => execSync(cmd, { cwd: frontend, stdio: 'inherit', shell: true });

if (!existsSync(join(frontend, 'node_modules'))) run('npm ci --no-audit --no-fund');
run('npm run build');
rmSync(target, { recursive: true, force: true });
cpSync(join(frontend, 'dist'), target, { recursive: true });
console.log(`Renderer copied to ${target}`);
