import { spawn } from 'node:child_process';
import { copyFileSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = resolve(app, '..');
const devHome = resolve(root, '.dev-codex');
mkdirSync(devHome, { recursive: true });
copyFileSync(resolve(root, 'catalog/opencode-go-models.json'), resolve(devHome, 'opencode-go-models.json'));
const cache = resolve(devHome, 'models_cache.json');
if (!existsSync(cache)) {
  writeFileSync(cache, JSON.stringify({ models: [
    { slug: 'gpt-6.1-sol', display_name: 'GPT-6.1 Sol', shell_type: 'unified_exec', supported_in_api: true },
    { slug: 'gpt-6-luna', display_name: 'GPT-6 Luna', shell_type: 'unified_exec', supported_in_api: true },
  ] }), 'utf8');
}

const python = process.env.PYTHON || 'python';
const manager = spawn(python, [resolve(root, 'router/manager.py')], {
  stdio: ['ignore', 'pipe', 'pipe'],
  env: {
    ...process.env, CODEX_HOME: devHome, CODEX_ROUTER_DEV: '1',
    CODEX_ROUTER_MANAGER_PORT: process.env.CODEX_ROUTER_MANAGER_PORT || '18766',
    CODEX_ROUTER_SETTINGS: resolve(devHome, 'router-settings.json'),
    CODEX_ROUTER_CREDENTIALS: resolve(devHome, 'credentials.json'),
    CODEX_ROUTER_USAGE_DB: resolve(devHome, 'router-usage.sqlite'),
    OPENCODE_AUTH_PATH: resolve(devHome, 'opencode-auth.json'),
  },
});
manager.stdout.on('data', data => process.stdout.write(`[manager] ${data}`));
manager.stderr.on('data', data => process.stderr.write(`[manager] ${data}`));

const viteArgs = [resolve(app, 'node_modules/vite/bin/vite.js'), ...process.argv.slice(2)];
const vite = spawn(process.execPath, viteArgs, { cwd: app, stdio: 'inherit' });
let closing = false;
function close(code = 0) {
  if (closing) return;
  closing = true;
  if (!manager.killed) manager.kill();
  if (!vite.killed) vite.kill();
  setTimeout(() => process.exit(code), 150).unref();
}
process.on('SIGINT', () => close(0));
process.on('SIGTERM', () => close(0));
manager.on('exit', code => { if (!closing && code) close(code); });
vite.on('exit', code => close(code || 0));
