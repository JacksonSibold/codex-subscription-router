import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = resolve(app, '..');
const artifacts = resolve(root, 'artifacts');
mkdirSync(artifacts, { recursive: true });
const child = spawn(process.execPath, [resolve(app, 'scripts/dev.mjs'), '--host', '127.0.0.1', '--port', '7100'], { cwd: app, stdio: ['ignore', 'pipe', 'pipe'] });
child.stdout.on('data', data => process.stdout.write(data));
child.stderr.on('data', data => process.stderr.write(data));

function stop() {
  if (child.killed) return;
  if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  else child.kill('SIGTERM');
}

try {
  let state;
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const response = await fetch('http://127.0.0.1:7100/api/state');
      if (response.ok) { state = await response.json(); break; }
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  if (!state) throw new Error('Development app did not become ready');
  if (state.settings.models.length !== 11) throw new Error('Default model settings did not load');
  if (state.live_apply !== false) throw new Error('Preview must use isolated development mode');
  const preview = await fetch('http://127.0.0.1:7100/api/preview', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Router-Manager': '1' }, body: JSON.stringify({ settings: state.settings }),
  });
  if (!preview.ok) throw new Error(`Catalog preview failed: ${await preview.text()}`);
  const catalog = await preview.json();
  if (catalog.models.length !== 11) throw new Error('Expected all eleven default models in preview');
  const apply = await fetch('http://127.0.0.1:7100/api/apply', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Router-Manager': '1' }, body: JSON.stringify({ settings: state.settings }),
  });
  const applied = await apply.json();
  if (!apply.ok || applied.router_reloaded !== false) throw new Error('Development apply must never signal the live router');
  if (!existsSync(resolve(root, '.dev-codex/mixed-models.json'))) throw new Error('Isolated catalog was not generated');

  const chromeCandidates = [
    process.env.CHROME_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  ].filter(Boolean);
  const chrome = chromeCandidates.find(existsSync);
  if (!chrome) throw new Error('Chrome or Edge is required for the rendered UI check');
  for (const page of ['overview', 'models', 'connections']) {
    const screenshot = resolve(artifacts, `relay-${page}.png`);
    const args = ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--window-size=1440,1100', `--screenshot=${screenshot}`, '--virtual-time-budget=4000', `http://127.0.0.1:7100/#${page}`];
    const result = spawnSync(chrome, args, { stdio: 'inherit', timeout: 45000 });
    if (result.status !== 0 || !existsSync(screenshot)) throw new Error(`Headless browser render failed for ${page}`);
  }
  console.log('PASS API state, isolated apply, 11-model preview, and three rendered UI pages');
} finally {
  stop();
}
