import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = resolve(app, '..');
const artifacts = resolve(root, 'artifacts');
const expectedVersion = readFileSync(resolve(root, 'VERSION'), 'utf8').trim();
mkdirSync(artifacts, { recursive: true });
const child = spawn(process.execPath, [resolve(app, 'scripts/dev.mjs'), '--host', '127.0.0.1', '--port', '7100'], {
  cwd: app, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, CODEX_ROUTER_MANAGER_PORT: '18767' },
});
child.stdout.on('data', data => process.stdout.write(data));
child.stderr.on('data', data => process.stderr.write(data));

function stop() {
  if (child.killed) return;
  if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  else child.kill('SIGTERM');
}

let localServer;
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
  if (state.version !== expectedVersion) throw new Error(`Manager version ${state.version} did not match ${expectedVersion}`);
  if (state.live_apply !== false) throw new Error('Preview must use isolated development mode');
  if (!state.providers.local) throw new Error('Local provider was not exposed by the manager');
  if (typeof state.usage?.totals?.requests !== 'number') throw new Error('Usage dashboard was not exposed by the manager');
  if (!Array.isArray(state.usage?.accounts) || state.usage.accounts.length < 5) throw new Error('Usage account inventory was incomplete');
  if (state.codex_link?.live_apply !== false) throw new Error('Codex linking was not disabled in isolated development mode');
  for (const provider of ['openai', 'anthropic', 'kimi']) {
    if (!state.available_models?.some(model => model.provider === provider)) {
      throw new Error(`Add-model catalog did not include ${provider}`);
    }
  }
  const providerModelsResponse = await fetch('http://127.0.0.1:7100/api/provider-models?refresh=1');
  const providerModels = await providerModelsResponse.json();
  if (!providerModelsResponse.ok) throw new Error(`Provider catalog API failed: ${JSON.stringify(providerModels)}`);
  for (const provider of ['openai', 'anthropic', 'kimi', 'opencode']) {
    if (!Array.isArray(providerModels.providers?.[provider]?.models)) {
      throw new Error(`Provider catalog did not include ${provider}`);
    }
  }
  const catalogJson = JSON.stringify(providerModels).toLowerCase();
  if (catalogJson.includes('access_token') || catalogJson.includes('refresh_token')) {
    throw new Error('Provider catalog response contained credential-shaped fields');
  }
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

  localServer = createServer((request, response) => {
    if (request.url === '/v1/models') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ data: [{ id: 'relay-local-test', name: 'Relay Local Test' }] }));
      return;
    }
    response.writeHead(404);
    response.end();
  });
  await new Promise((resolveReady, reject) => {
    localServer.once('error', reject);
    localServer.listen(0, '127.0.0.1', resolveReady);
  });
  const localEndpoint = `http://127.0.0.1:${localServer.address().port}/v1`;
  const discoveryResponse = await fetch('http://127.0.0.1:7100/api/local/discover', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Router-Manager': '1' },
    body: JSON.stringify({ endpoint: localEndpoint }),
  });
  const discovery = await discoveryResponse.json();
  if (!discoveryResponse.ok || discovery.models?.[0]?.id !== 'relay-local-test') {
    throw new Error(`Local discovery failed: ${JSON.stringify(discovery)}`);
  }
  const localDocument = structuredClone(state.settings);
  localDocument.providers.local.enabled = true;
  localDocument.models.push({
    id: 'relay-local-test', upstream_id: 'relay-local-test', provider: 'local',
    display_name: 'Relay Local Test', visible: true,
    reasoning: { default: 'medium', supported: ['low', 'medium', 'high'] },
    tools: { shell: true, computer_use: true, web_search: false, connected_apps: false },
    subagents: true, local: { endpoint: localEndpoint, protocol: 'openai_chat', credential_env: null },
  });
  const localPreviewResponse = await fetch('http://127.0.0.1:7100/api/preview', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Router-Manager': '1' },
    body: JSON.stringify({ settings: localDocument }),
  });
  const localPreview = await localPreviewResponse.json();
  if (!localPreviewResponse.ok) throw new Error(`Local catalog preview failed: ${JSON.stringify(localPreview)}`);
  const localEntry = localPreview.included.find(model => model.slug === 'relay-local-test');
  if (!localEntry || localEntry.multi_agent_version !== 'v2') throw new Error('Local route was not child-agent eligible');
  const usageResponse = await fetch('http://127.0.0.1:7100/api/usage?days=30');
  if (!usageResponse.ok) throw new Error('Usage API failed');
  const usage = await usageResponse.json();
  if (typeof usage.totals?.total_tokens !== 'number') throw new Error('Usage totals were missing');
  const allowanceResponse = await fetch('http://127.0.0.1:7100/api/subscription-usage');
  const allowances = await allowanceResponse.json();
  if (!allowanceResponse.ok || allowances.providers?.length !== 5) {
    throw new Error(`Subscription allowance API failed: ${JSON.stringify(allowances)}`);
  }

  const chromeCandidates = [
    process.env.CHROME_PATH,
    process.env.PROGRAMFILES && resolve(process.env.PROGRAMFILES, 'Google/Chrome/Application/chrome.exe'),
    process.env['PROGRAMFILES(X86)'] && resolve(process.env['PROGRAMFILES(X86)'], 'Google/Chrome/Application/chrome.exe'),
    process.env['PROGRAMFILES(X86)'] && resolve(process.env['PROGRAMFILES(X86)'], 'Microsoft/Edge/Application/msedge.exe'),
    process.env.PROGRAMFILES && resolve(process.env.PROGRAMFILES, 'Microsoft/Edge/Application/msedge.exe'),
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ].filter(Boolean);
  if (process.platform !== 'win32' && process.platform !== 'darwin') {
    for (const name of ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge']) {
      const found = spawnSync('which', [name], { encoding: 'utf8' });
      if (found.status === 0 && found.stdout.trim()) chromeCandidates.push(found.stdout.trim());
    }
  }
  const chrome = chromeCandidates.find(existsSync);
  if (!chrome) throw new Error('Chrome or Edge is required for the rendered UI check');
  for (const page of ['overview', 'models', 'connections', 'usage', 'capabilities']) {
    const screenshot = resolve(artifacts, `relay-${page}.png`);
    const args = ['--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--hide-scrollbars', '--window-size=1440,1100', `--screenshot=${screenshot}`, '--virtual-time-budget=4000', `http://127.0.0.1:7100/#${page}`];
    const result = spawnSync(chrome, args, { stdio: 'inherit', timeout: 45000 });
    if (result.status !== 0 || !existsSync(screenshot)) throw new Error(`Headless browser render failed for ${page}`);
  }
  console.log('PASS API state, provider catalogs, isolated apply, local discovery, usage, allowances, cross-provider preview, and five rendered UI pages');
} finally {
  if (localServer) await new Promise(resolveClose => localServer.close(resolveClose));
  stop();
}
