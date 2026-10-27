import React, { useEffect, useMemo, useRef, useState } from 'react';
import { findSelectableDefault, isSelectableDefault } from './model-defaults.js';
import {
  Activity, ArrowDown, ArrowUp, BookOpen, Bot, Box, Check, ChevronDown, ChevronRight,
  CircleGauge, Cloud, Code2, Copy, Cpu, Download, ExternalLink, Eye, EyeOff,
  FileJson, Gauge, Github, GripVertical, HardDrive, KeyRound, Layers3, Link2, LoaderCircle,
  Menu, Monitor, MoreHorizontal, Network, PanelLeftClose, Pencil, Plus, RefreshCw,
  Save, Search, Server, Settings2, ShieldCheck, Sparkles, Star, TerminalSquare, Trash2,
  WandSparkles, X, Zap,
} from 'lucide-react';

const PROVIDERS = {
  openai: { name: 'OpenAI', short: 'OAI', color: '#7dd3fc', description: 'ChatGPT subscription through Codex', icon: Sparkles },
  anthropic: { name: 'Claude', short: 'CL', color: '#93c5fd', description: 'Claude plans through Relay-owned OAuth', icon: Bot },
  kimi: { name: 'Kimi Code', short: 'KM', color: '#a5b4fc', description: 'Kimi membership native Responses API', icon: MoonIcon },
  opencode: { name: 'OpenCode Go', short: 'GO', color: '#67e8f9', description: 'Your OpenCode Go model catalog', icon: Code2 },
  local: { name: 'Local models', short: 'LOC', color: '#818cf8', description: 'Ollama, LM Studio, or another loopback model server', icon: HardDrive },
};
const EFFORTS = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
const RELAY_VERSION = __RELAY_VERSION__;
const PAGE_META = {
  overview: ['Your subscriptions, one workspace.', 'Manage every model route without giving up the Codex experience.'],
  connections: ['Connections', 'Use official sign-in flows. Credentials stay in their provider stores.'],
  models: ['Model picker', 'Choose exactly what appears in Codex, and how it behaves.'],
  capabilities: ['Capabilities', 'A clear view of thinking, tools, Computer Use, and cross-provider delegation.'],
  usage: ['Usage', 'Subscription allowances and token activity across every connected account.'],
  diagnostics: ['Diagnostics', 'Local health and sanitized activity. Never any access tokens.'],
};

function MoonIcon(props) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" {...props}><path d="M20 15.2A8.5 8.5 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2Z"/></svg>;
}

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Router-Manager': '1' }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The local manager could not complete that action.');
  return data;
}

function ProviderMark({ provider, size = 'normal' }) {
  const meta = PROVIDERS[provider] || PROVIDERS.openai;
  const Icon = meta.icon;
  return <span className={`provider-mark ${size}`} style={{ '--provider-color': meta.color }}><Icon size={size === 'small' ? 15 : 19}/></span>;
}

function Toggle({ checked, onChange, label, disabled = false }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} className={`toggle ${checked ? 'on' : ''}`} onClick={() => onChange(!checked)}><span/></button>;
}

function StatusPill({ status }) {
  const good = status === 'credential_found' || status === 'ready' || status === true;
  const label = status === 'credential_found' ? 'Credential found' : status === 'ready' ? 'Endpoint ready'
    : status === 'unknown' ? 'Setup needed' : 'Not connected';
  return <span className={`status-pill ${good ? 'good' : ''}`}><i/>{label}</span>;
}

function formatTokens(value) {
  const number = Number(value || 0);
  if (number >= 1_000_000_000) return `${(number / 1_000_000_000).toFixed(1)}B`;
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return number.toLocaleString();
}

function newModel(provider, upstreamId, name, settings, extra = {}) {
  const base = String(upstreamId || 'model').toLowerCase().replace(/[^a-z0-9._:/-]+/g, '-').replace(/^-+|-+$/g, '') || 'model';
  let id = extra.id || base;
  if (settings.models.some(model => model.id === id)) id = `${provider}-${base}`;
  let suffix = 2;
  const root = id;
  while (settings.models.some(model => model.id === id)) id = `${root}-${suffix++}`;
  const efforts = provider === 'kimi' ? ['low', 'high', 'max']
    : provider === 'anthropic' ? ['low', 'medium', 'high', 'xhigh', 'max']
      : ['low', 'medium', 'high', 'xhigh'];
  return {
    id, upstream_id: upstreamId, provider, display_name: name || upstreamId, visible: true,
    reasoning: { default: efforts.includes('medium') ? 'medium' : efforts.at(-1), supported: efforts },
    tools: { shell: true, computer_use: true, web_search: provider === 'openai', connected_apps: provider === 'openai' },
    subagents: true, ...extra,
  };
}

function KeyForm({ provider, onDone, notify }) {
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    if (!key.trim()) return;
    setBusy(true);
    try {
      const result = await api('/api/credential', { provider, key });
      setKey(''); notify(result.message); onDone();
    } catch (error) { notify(error.message, 'error'); }
    finally { setBusy(false); }
  }
  return <form className="key-form" onSubmit={submit}>
    <label><KeyRound size={15}/><input type="password" value={key} onChange={e => setKey(e.target.value)} placeholder={provider === 'kimi' ? 'Paste Kimi Code API key' : 'Paste OpenCode API key'} autoComplete="off"/></label>
    <button className="button secondary" disabled={!key.trim() || busy}>{busy ? <LoaderCircle className="spin" size={16}/> : 'Save key'}</button>
  </form>;
}

function Overview({ data, setPage }) {
  const { settings, providers, router, catalog, usage } = data;
  const visible = settings.models.filter(m => m.visible && settings.providers[m.provider].enabled);
  const connected = Object.values(providers).filter(p => p.status === 'credential_found').length;
  return <div className="page overview-page">
    <section className="hero-panel">
      <div className="hero-copy"><span className="eyebrow"><span className="live-dot"/>LOCAL CONTROL CENTER</span>
        <h2>Every model.<br/><em>Your rules.</em></h2>
        <p>One private router for your coding subscriptions. No credentials in the browser, no changes until you apply them.</p>
        <button className="button primary" onClick={() => setPage('models')}>Customize your picker <ChevronRight size={16}/></button>
      </div>
      <div className="orbit-art" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="orbit-center"><Network size={34}/></div>
        {Object.keys(PROVIDERS).map((p, i) => <span className={`orbit-node node-${i}`} key={p}><ProviderMark provider={p}/></span>)}
      </div>
    </section>
    <div className="metric-grid">
      <button className="metric-card" onClick={() => setPage('models')}><span className="metric-icon purple"><Layers3/></span><div><strong>{visible.length}</strong><span>Models in picker</span></div><ChevronRight size={17}/></button>
      <button className="metric-card" onClick={() => setPage('connections')}><span className="metric-icon green"><Link2/></span><div><strong>{connected}<small> / {Object.keys(PROVIDERS).length}</small></strong><span>Accounts or endpoints ready</span></div><ChevronRight size={17}/></button>
      <button className="metric-card" onClick={() => setPage('usage')}><span className="metric-icon purple"><Gauge/></span><div><strong>{formatTokens(usage?.totals?.total_tokens)}</strong><span>{usage?.totals?.requests || 0} requests · 30 days</span></div><ChevronRight size={17}/></button>
      <button className="metric-card" onClick={() => setPage('diagnostics')}><span className="metric-icon amber"><Activity/></span><div><strong className="metric-text">{router.reachable ? 'Online' : 'Standby'}</strong><span>Router status</span></div><ChevronRight size={17}/></button>
    </div>
    <div className="overview-columns">
      <section className="panel route-panel"><div className="section-heading"><div><span className="eyebrow">ACTIVE ROUTES</span><h3>Your model lanes</h3></div><button className="text-button" onClick={() => setPage('connections')}>Manage <ChevronRight size={14}/></button></div>
        <div className="route-list">{Object.entries(PROVIDERS).map(([id, meta]) => <div className="route-row" key={id}><ProviderMark provider={id}/><div><strong>{meta.name}</strong><span>{settings.models.filter(m => m.provider === id && m.visible).length} visible models</span></div><div className="route-line"><i/></div><StatusPill status={providers[id]?.status}/></div>)}</div>
      </section>
      <section className="panel picker-preview"><div className="section-heading"><div><span className="eyebrow">CODEX PICKER</span><h3>Ready when you are</h3></div><Box size={19}/></div>
        <div className="mini-picker">{visible.slice(0, 5).map(model => <div key={model.id}><ProviderMark provider={model.provider} size="small"/><span>{model.display_name}</span>{model.id === settings.runtime.default_model && <Star size={13} fill="currentColor"/>}</div>)}{visible.length > 5 && <div className="more-models">+ {visible.length - 5} more models</div>}</div>
        <p className="subtle-note"><ShieldCheck size={14}/> Last generated catalog: {catalog.length} entries</p>
      </section>
    </div>
    <div className="privacy-strip"><ShieldCheck size={20}/><div><strong>Private by design</strong><span>Traffic binds to 127.0.0.1. Provider credentials never cross into another model lane.</span></div><span className="local-badge">LOCAL ONLY</span></div>
  </div>;
}

function ClaudeConnect({ state, reload, notify }) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [authUrl, setAuthUrl] = useState('');
  async function start() {
    setBusy(true);
    try {
      const result = await api('/api/oauth/anthropic/start', {});
      setAuthUrl(result.auth_url);
      notify(result.message);
    } catch (error) { notify(error.message, 'error'); }
    finally { setBusy(false); }
  }
  async function complete(event) {
    event.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    try {
      const result = await api('/api/oauth/anthropic/complete', { code });
      notify(result.connected ? 'Claude connected through Relay OAuth. Tokens are stored outside this browser.' : 'Claude authorization completed.');
      setCode(''); setAuthUrl(''); reload();
    } catch (error) { notify(error.message, 'error'); }
    finally { setBusy(false); }
  }
  return <div className="claude-connect">
    <div className="connection-actions"><button className="button secondary" disabled={busy} onClick={start}>{busy ? <LoaderCircle className="spin" size={15}/> : <ExternalLink size={15}/>}{state.status === 'credential_found' ? 'Reconnect Claude' : 'Start Claude sign-in'}</button></div>
    <form className="oauth-code" onSubmit={complete}><label><KeyRound size={15}/><input value={code} onChange={event => setCode(event.target.value)} placeholder="Paste authorization code" autoComplete="off"/></label><button className="button primary" disabled={busy || !code.trim()}>Connect</button></form>
    {authUrl && <p className="oauth-help">The authorization page opened in your browser. If it did not, <a href={authUrl} target="_blank" rel="noreferrer">open Claude sign-in</a>. After approving access, copy the code shown and paste it above.</p>}
    <div className="safe-note"><ShieldCheck size={13}/> Sign in with whichever eligible Claude plan you have, including Pro, Max, Team, or Enterprise where Claude Code access is included. Relay owns this OAuth connection; OpenCode and your separate Claude Code configuration are not used.</div>
  </div>;
}

function CodexLinkCard({ codex, reload, notify, setPage }) {
  const [busy, setBusy] = useState(false);
  const linked = Boolean(codex?.linked);
  async function link() {
    setBusy(true);
    try {
      const result = await api('/api/codex/link', {});
      notify(result.message || 'Codex is linked to Relay.');
      await reload();
    } catch (error) { notify(error.message, 'error'); }
    finally { setBusy(false); }
  }
  const status = linked ? 'Linked' : codex?.live_apply === false ? 'Preview only' : 'Not linked';
  return <section className={`panel codex-link-card ${linked ? 'is-linked' : ''}`}>
    <div className="codex-link-main">
      <div className="codex-link-heading"><span className="metric-icon purple"><TerminalSquare size={20}/></span><div><span className="eyebrow">CODEX ON THIS PC</span><h3>{linked ? 'Your local Codex uses Relay' : 'Connect your Codex model picker'}</h3></div><span className={`link-status ${linked ? 'linked' : ''}`}><i/>{status}</span></div>
      <p>Link this machine's Codex installation to Relay. Your OpenAI sign-in stays in Codex, while every configured Claude, Kimi, OpenCode, and local route becomes available from the same picker.</p>
      <div className="codex-config-path"><span>Codex config</span><code>{codex?.config_location || 'Codex configuration path unavailable'}</code></div>
      {codex?.error && <div className="link-error">{codex.error}</div>}
      {!linked && codex?.reason && <div className="link-error"><strong>{codex.reason}</strong>{codex.action && <span>{codex.action}</span>}</div>}
      <div className="codex-link-actions">
        <button className="button primary" disabled={busy || codex?.live_apply === false} onClick={link}>{busy ? <LoaderCircle className="spin" size={16}/> : <Link2 size={16}/>}{linked ? 'Repair Codex link' : 'Link Codex on this PC'}</button>
        <button className="button secondary" onClick={() => setPage('models')}><Layers3 size={16}/>Review picker models</button>
      </div>
      <div className="safe-note"><ShieldCheck size={13}/>Only Relay's model defaults, catalog path, and <code>mixed</code> provider are updated. Unrelated Codex projects, plugins, providers, and credentials are preserved with a timestamped backup. Open a new Codex chat after linking.</div>
    </div>
    <div className="codex-link-facts">
      <div><span>Provider</span><strong>{codex?.model_provider || 'mixed'}</strong></div>
      <div><span>Relay endpoint</span><strong>127.0.0.1:{codex?.router_port || 18765}</strong></div>
      <div><span>Catalog</span><strong>{codex?.catalog_exists ? 'Ready' : 'Created when linked'}</strong></div>
      <div><span>Codex CLI</span><strong>{codex?.codex_installed ? 'Detected' : 'Not on PATH'}</strong></div>
    </div>
  </section>;
}

function Connections({ data, updateSettings, reload, notify, setPage }) {
  const { settings, providers, codex_link: codexLink } = data;
  async function action(provider, kind) {
    try {
      const result = await api(kind === 'login' ? '/api/login' : '/api/open-docs', { provider });
      if (result.message) notify(result.message);
    } catch (error) { notify(error.message, 'error'); }
  }
  function setEnabled(provider, enabled) {
    const next = structuredClone(settings);
    next.providers[provider].enabled = enabled;
    const currentDefault = next.models.find(model => model.id === next.runtime.default_model);
    if (!enabled && currentDefault?.provider === provider) {
      const replacement = next.models.find(model => model.visible && model.provider !== provider && next.providers[model.provider].enabled);
      if (replacement) next.runtime.default_model = replacement.id;
    }
    updateSettings(next);
  }
  const localModels = settings.models.filter(model => model.provider === 'local');
  return <div className="page">
    <div className="notice"><ShieldCheck size={18}/><span>Relay detects whether credentials exist, but never displays them. “Credential found” is not a billed API test.</span></div>
    <CodexLinkCard codex={codexLink} reload={reload} notify={notify} setPage={setPage}/>
    <div className="connection-grid">{Object.entries(PROVIDERS).map(([id, meta]) => {
      const state = providers[id] || {};
      const enabled = settings.providers[id].enabled;
      return <section className={`panel connection-card ${!enabled ? 'disabled-card' : ''}`} key={id}>
        <div className="connection-top"><ProviderMark provider={id}/><Toggle checked={enabled} onChange={value => setEnabled(id, value)} label={`Enable ${meta.name}`}/></div>
        <div className="connection-title"><h3>{meta.name}</h3><StatusPill status={state.status}/></div>
        <p>{meta.description}</p><div className="credential-detail">{id === 'local' ? <Server size={14}/> : <KeyRound size={14}/>}{state.detail || state.auth}</div>
        {(id === 'kimi' || id === 'opencode') ? <>
          <KeyForm provider={id} onDone={reload} notify={notify}/>
          <button className="text-button docs-link" onClick={() => action(id, 'docs')}>Open official key console <ExternalLink size={13}/></button>
        </> : id === 'anthropic' ? <ClaudeConnect state={state} reload={reload} notify={notify}/>
        : id === 'local' ? <div className="local-connection">
          <div className="local-count"><HardDrive size={16}/><div><strong>{localModels.length}</strong><span>{localModels.length === 1 ? 'local route' : 'local routes'} configured</span></div></div>
          <button className="button secondary" onClick={() => setPage('models')}><Plus size={15}/>Add a local model</button>
          <button className="text-button docs-link" onClick={() => action(id, 'docs')}>OpenAI-compatible API reference <ExternalLink size={13}/></button>
        </div>
        : <div className="connection-actions"><button className="button secondary" onClick={() => action(id, 'login')}><ExternalLink size={15}/>Open Codex sign-in</button><button className="icon-button" title="Official documentation" onClick={() => action(id, 'docs')}><BookOpen size={17}/></button></div>}
      </section>;
    })}</div>
    <section className="panel environment-note"><TerminalSquare size={22}/><div><h3>Credential boundaries</h3><p>Kimi and OpenCode keys are write-only from the browser. Claude uses Relay's own PKCE OAuth for whichever eligible Claude plan you sign into; OpenAI traffic uses Codex's existing sign-in. Credentials never cross provider lanes.</p></div></section>
  </div>;
}


function ModelEditor({ model, settings, update, remove, close }) {
  if (!model) return <aside className="panel model-editor empty-editor"><Settings2 size={28}/><h3>Select a model</h3><p>Edit its picker name, thinking levels, and tool access.</p></aside>;
  const meta = PROVIDERS[model.provider];
  function change(mutator) { const next = structuredClone(model); mutator(next); update(next); }
  function toggleEffort(effort) {
    change(next => {
      const list = next.reasoning.supported;
      next.reasoning.supported = list.includes(effort) ? list.filter(e => e !== effort) : [...list, effort];
      if (next.reasoning.supported.length === 0) next.reasoning.default = null;
      else if (!next.reasoning.supported.includes(next.reasoning.default)) next.reasoning.default = next.reasoning.supported[0];
    });
  }
  const unsupported = model.provider !== 'openai';
  const eligibleChildren = settings.models.filter(candidate => candidate.id !== model.id && candidate.visible && candidate.subagents && settings.providers[candidate.provider]?.enabled);
  const childProviders = new Set(eligibleChildren.map(candidate => candidate.provider));
  return <aside className="panel model-editor"><div className="editor-heading"><div><span className="eyebrow">MODEL SETTINGS</span><h3>Customize route</h3></div><button className="icon-button" onClick={close}><X size={17}/></button></div>
    <div className="editor-model-id"><ProviderMark provider={model.provider}/><div><strong>{meta.name}</strong><code>Route {model.id}</code></div></div>
    <label className="field"><span>Picker display name</span><input value={model.display_name} maxLength={120} onChange={e => change(next => { next.display_name = e.target.value; })}/></label>
    <label className="field"><span>Upstream model ID</span><input value={model.upstream_id || model.id} maxLength={200} onChange={e => change(next => { next.upstream_id = e.target.value; })}/><small>This exact identifier is sent to {meta.name}. The stable Relay route ID stays {model.id}.</small></label>
    {model.provider === 'local' && <>
      <label className="field"><span>Loopback endpoint</span><input value={model.local?.endpoint || ''} onChange={e => change(next => { next.local ||= {}; next.local.endpoint = e.target.value; })} placeholder="http://127.0.0.1:11434/v1"/><small>Only localhost or another loopback IP is accepted. Relay appends the protocol path.</small></label>
      <label className="field"><span>Wire protocol</span><div className="select-wrap"><select value={model.local?.protocol || 'openai_chat'} onChange={e => change(next => { next.local ||= {}; next.local.protocol = e.target.value; })}><option value="openai_chat">OpenAI Chat Completions</option><option value="openai_responses">OpenAI Responses</option></select><ChevronRight size={14}/></div></label>
      <label className="field"><span>Optional credential variable</span><input value={model.local?.credential_env || ''} onChange={e => change(next => { next.local ||= {}; next.local.credential_env = e.target.value || null; })} placeholder="LOCAL_LLM_API_KEY"/><small>Use an environment or Relay credential name, never paste the key into settings.</small></label>
    </>}
    <div className="field"><span>Default thinking level</span><div className="select-wrap"><select value={model.reasoning.default || ''} disabled={!model.reasoning.supported.length} onChange={e => change(next => { next.reasoning.default = e.target.value || null; })}>{model.reasoning.supported.map(e => <option key={e}>{e}</option>)}</select><ChevronRight size={14}/></div></div>
    <div className="field"><span>Available thinking levels</span><div className="effort-options">{EFFORTS.map(effort => <button key={effort} className={model.reasoning.supported.includes(effort) ? 'selected' : ''} onClick={() => toggleEffort(effort)}>{model.reasoning.supported.includes(effort) && <Check size={12}/>} {effort}</button>)}</div><small>Only levels supported by this model should be enabled.</small></div>
    <div className="editor-section"><span className="field-label">TOOLS & AGENTS</span>
      {[['shell', 'Shell & file tools', TerminalSquare], ['computer_use', 'Computer Use bridge', Monitor], ['web_search', 'Hosted web search', Search], ['connected_apps', 'Connected apps', Cloud]].map(([key, label, Icon]) => <div className="setting-row" key={key}><Icon size={16}/><span>{label}{unsupported && (key === 'web_search' || key === 'connected_apps') && <small>OpenAI only</small>}</span><Toggle checked={model.tools[key]} disabled={unsupported && (key === 'web_search' || key === 'connected_apps')} onChange={value => change(next => { next.tools[key] = value; })} label={label}/></div>)}
      <div className="setting-row"><Bot size={16}/><span>Cross-provider subagents<small>{eligibleChildren.length ? `${eligibleChildren.length} eligible child routes across ${childProviders.size} provider${childProviders.size === 1 ? '' : 's'}. This model can delegate to any of them.` : 'No other eligible child routes are visible and enabled.'}</small></span><Toggle checked={model.subagents} onChange={value => change(next => { next.subagents = value; })} label="Cross-provider subagents"/></div>
    </div>
    <button className={`button full ${model.id === settings.runtime.default_model ? 'default-selected' : 'secondary'}`} onClick={() => update(model, true)}><Star size={15} fill={model.id === settings.runtime.default_model ? 'currentColor' : 'none'}/>{model.id === settings.runtime.default_model ? 'Default Codex model' : 'Make default model'}</button>
    <button className="text-button danger remove-model" onClick={() => remove(model.id)}><Trash2 size={14}/>Remove from configuration</button>
  </aside>;
}

function CustomModelModal({ data, onAdd, close }) {
  const [provider, setProvider] = useState('anthropic');
  const [upstreamId, setUpstreamId] = useState('');
  const [routeId, setRouteId] = useState('');
  const [name, setName] = useState('');
  const [routeEdited, setRouteEdited] = useState(false);
  function updateUpstream(value) {
    setUpstreamId(value);
    if (!routeEdited) setRouteId(value.toLowerCase().replace(/[^a-z0-9._:/-]+/g, '-').replace(/^-+|-+$/g, ''));
  }
  function submit(event) {
    event.preventDefault();
    if (!upstreamId.trim() || !name.trim()) return;
    const model = newModel(provider, upstreamId.trim(), name.trim(), data.settings, { id: routeId.trim() || undefined });
    onAdd(model);
  }
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && close()}><form className="modal panel" onSubmit={submit}><div className="section-heading"><div><span className="eyebrow">CUSTOM ROUTE</span><h3>Add a provider model</h3></div><button type="button" className="icon-button" onClick={close}><X size={18}/></button></div>
    <label className="field"><span>Provider</span><div className="select-wrap"><select value={provider} onChange={event => { setProvider(event.target.value); setRouteEdited(false); setRouteId(upstreamId); }}>{Object.entries(PROVIDERS).filter(([id]) => id !== 'local').map(([id, meta]) => <option value={id} key={id}>{meta.name}</option>)}</select><ChevronRight size={14}/></div></label>
    <label className="field"><span>Upstream model ID</span><input required value={upstreamId} onChange={e => updateUpstream(e.target.value)} placeholder={provider === 'anthropic' ? 'claude-sonnet-5-5' : provider === 'kimi' ? 'k3.1-pro-highspeed' : 'provider-model-id'}/><small>Sent unchanged to the provider.</small></label>
    <label className="field"><span>Relay route ID</span><input required value={routeId} onChange={e => { setRouteEdited(true); setRouteId(e.target.value); }} placeholder="stable-picker-id"/><small>Unique in the picker. Changing it changes the model selected by Codex.</small></label>
    <label className="field"><span>Display name</span><input required value={name} onChange={e => setName(e.target.value)} placeholder="My model"/></label>
    <div className="modal-actions"><button type="button" className="button secondary" onClick={close}>Cancel</button><button className="button primary"><Plus size={16}/>Add model</button></div>
  </form></div>;
}

function LocalModelModal({ data, onAdd, close, notify }) {
  const [endpoint, setEndpoint] = useState('http://127.0.0.1:11434/v1');
  const [protocol, setProtocol] = useState('openai_chat');
  const [discovered, setDiscovered] = useState([]);
  const [upstreamId, setUpstreamId] = useState('');
  const [routeId, setRouteId] = useState('');
  const [name, setName] = useState('');
  const [credentialEnv, setCredentialEnv] = useState('');
  const [busy, setBusy] = useState(false);
  const [routeEdited, setRouteEdited] = useState(false);
  function choose(model) {
    setUpstreamId(model.id); setName(model.name);
    if (!routeEdited) setRouteId(model.id.toLowerCase().replace(/[^a-z0-9._:/-]+/g, '-').replace(/^-+|-+$/g, ''));
  }
  async function discover() {
    setBusy(true);
    try {
      const result = await api('/api/local/discover', { endpoint });
      setDiscovered(result.models || []);
      if (!result.models?.length) notify('The endpoint responded, but it did not list any models.', 'error');
      else if (!upstreamId && result.models.length === 1) choose(result.models[0]);
    } catch (error) { notify(error.message, 'error'); }
    finally { setBusy(false); }
  }
  function submit(event) {
    event.preventDefault();
    if (!endpoint.trim() || !upstreamId.trim() || !name.trim()) return;
    const local = { endpoint: endpoint.trim(), protocol, credential_env: credentialEnv.trim() || null };
    const model = newModel('local', upstreamId.trim(), name.trim(), data.settings, { id: routeId.trim() || undefined, local });
    onAdd(model);
  }
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && close()}><form className="modal panel local-modal" onSubmit={submit}><div className="section-heading"><div><span className="eyebrow">LOCAL ENDPOINT</span><h3>Add an Ollama or LM Studio model</h3></div><button type="button" className="icon-button" onClick={close}><X size={18}/></button></div>
    <label className="field"><span>Loopback base URL</span><div className="endpoint-row"><input required value={endpoint} onChange={event => { setEndpoint(event.target.value); setDiscovered([]); }} placeholder="http://127.0.0.1:11434/v1"/><button type="button" className="button secondary" disabled={busy || !endpoint.trim()} onClick={discover}>{busy ? <LoaderCircle className="spin" size={15}/> : <RefreshCw size={15}/>}Discover</button></div><small>Only localhost and loopback IP addresses are allowed. Relay never forwards your Codex credential.</small></label>
    <label className="field"><span>Wire protocol</span><div className="select-wrap"><select value={protocol} onChange={event => setProtocol(event.target.value)}><option value="openai_chat">OpenAI Chat Completions</option><option value="openai_responses">OpenAI Responses</option></select><ChevronRight size={14}/></div></label>
    {discovered.length > 0 && <div className="field"><span>Models found</span><div className="suggestions local-suggestions">{discovered.map(model => <button type="button" key={model.id} className={upstreamId === model.id ? 'selected' : ''} onClick={() => choose(model)}>{model.name}<code>{model.id}</code></button>)}</div></div>}
    <div className="field-grid"><label className="field"><span>Upstream model ID</span><input required value={upstreamId} onChange={event => { setUpstreamId(event.target.value); if (!routeEdited) setRouteId(event.target.value.toLowerCase().replace(/[^a-z0-9._:/-]+/g, '-')); }} placeholder="llama3.2:3b"/></label><label className="field"><span>Relay route ID</span><input required value={routeId} onChange={event => { setRouteEdited(true); setRouteId(event.target.value); }} placeholder="local-llama"/></label></div>
    <label className="field"><span>Display name</span><input required value={name} onChange={event => setName(event.target.value)} placeholder="Llama 3.2 · Local"/></label>
    <label className="field"><span>Optional credential variable</span><input value={credentialEnv} onChange={event => setCredentialEnv(event.target.value)} placeholder="LOCAL_LLM_API_KEY"/><small>Most local servers need no key. If yours does, this is a credential name, not the secret itself.</small></label>
    <div className="modal-actions"><button type="button" className="button secondary" onClick={close}>Cancel</button><button className="button primary"><Plus size={16}/>Add local model</button></div>
  </form></div>;
}

function AddModelMenu({ data, onAvailable, onCustom, onLocal, notify }) {
  const [available, setAvailable] = useState(data.available_models || []);
  const [providerCatalogs, setProviderCatalogs] = useState(data.provider_catalogs || {});
  const [newModels, setNewModels] = useState(data.provider_catalog_status?.new_models || []);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const configured = (provider, upstreamId) => data.settings.models.some(model =>
    model.provider === provider && (model.upstream_id || model.id) === upstreamId);
  async function refresh(force) {
    setBusy(true);
    try {
      const snapshot = await api(`/api/provider-models${force ? '?refresh=1' : ''}`);
      const merged = new Map((data.available_models || []).map(model => [`${model.provider}:${model.id}`, model]));
      Object.entries(snapshot.providers || {}).forEach(([provider, catalog]) => {
        (catalog.models || []).forEach(model => merged.set(`${provider}:${model.id}`, { ...model, provider }));
      });
      setAvailable([...merged.values()]);
      setProviderCatalogs(snapshot);
      setNewModels(snapshot.new_models || []);
      const failed = Object.entries(snapshot.providers || {}).filter(([, catalog]) => catalog.error).map(([provider]) => PROVIDERS[provider]?.name || provider);
      if (failed.length) notify(`Some catalogs used cached entries: ${failed.join(', ')}.`, 'error');
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => { refresh(true); }, []);
  const needle = query.trim().toLowerCase();
  const newKeys = new Set(newModels.map(model => `${model.provider}:${model.id}`));
  const visibleGroups = Object.entries(PROVIDERS).filter(([id]) => id !== 'local').map(([id, meta]) => ({
    id, meta,
    models: available.filter(model => model.provider === id && (!needle || `${model.name} ${model.id}`.toLowerCase().includes(needle))),
  }));
  return <div className="add-model-menu panel">
    <div className="add-menu-head"><div><span className="eyebrow">PROVIDER CATALOGS</span><strong>Choose a model</strong></div><div className="catalog-head-actions"><span>{newModels.length ? `${newModels.length} new · ` : ''}{available.length} listed</span><button type="button" className="icon-button" title="Refresh provider catalogs" disabled={busy} onClick={() => refresh(true)}><RefreshCw className={busy ? 'spin' : ''} size={15}/></button></div></div>
    <label className="add-menu-search"><Search size={14}/><input autoFocus placeholder="Search every connected provider…" value={query} onChange={event => setQuery(event.target.value)}/>{query && <button type="button" onClick={() => setQuery('')}><X size={13}/></button>}</label>
    <div className="add-menu-scroll">{visibleGroups.map(({ id, meta, models }) => {
      const catalog = providerCatalogs.providers?.[id] || {};
      return <section key={id}><div className="add-group-label" title={catalog.source || ''}><ProviderMark provider={id} size="small"/><strong>{meta.name}</strong><span>{models.length}{needle && catalog.count !== models.length ? ` / ${catalog.count}` : ''}</span></div>{models.map(model => {
        const added = configured(id, model.id);
        const isNew = newKeys.has(`${id}:${model.id}`);
        return <button key={`${id}-${model.id}`} disabled={added} className={added ? 'catalog-added' : ''} onClick={() => onAvailable(id, model)}><span>{model.name}{added ? <em>In picker</em> : isNew ? <em>New</em> : null}</span><code>{model.id}</code></button>;
      })}{!models.length && <p>{needle ? 'No models match this search.' : 'No catalog entries for this provider. Use a custom upstream ID.'}</p>}</section>;
    })}</div>
    <div className="add-menu-footer"><button onClick={onLocal}><HardDrive size={15}/><span><strong>Local model</strong><small>Discover Ollama, LM Studio, or compatible server</small></span><ChevronRight size={14}/></button><button onClick={onCustom}><Plus size={15}/><span><strong>Custom provider model</strong><small>Enter any upstream ID, even before it appears in a catalog</small></span><ChevronRight size={14}/></button></div>
  </div>;
}

function ModelsPage({ data, updateSettings, notify }) {
  const { settings } = data;
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [addMenu, setAddMenu] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [localOpen, setLocalOpen] = useState(false);
  const [preview, setPreview] = useState(null);
  const dragIndex = useRef(null);
  const editorRef = useRef(null);
  const selectedModel = settings.models.find(m => m.id === selected);
  const models = settings.models.map((m, index) => ({ ...m, index })).filter(m => (filter === 'all' || m.provider === filter) && `${m.display_name} ${m.id} ${m.upstream_id || ''}`.toLowerCase().includes(query.toLowerCase()));
  function openEditor(id) {
    setSelected(id);
    window.setTimeout(() => {
      if (window.innerWidth <= 1100) editorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 30);
  }
  function move(from, to) {
    if (from === to || from < 0 || to < 0 || to >= settings.models.length) return;
    const next = structuredClone(settings); const [item] = next.models.splice(from, 1); next.models.splice(to, 0, item); updateSettings(next);
  }
  function addModel(model) {
    const next = structuredClone(settings);
    next.models.push(model);
    next.providers[model.provider].enabled = true;
    updateSettings(next);
    setAddMenu(false); setCustomOpen(false); setLocalOpen(false); setSelected(model.id);
  }
  function update(model, makeDefault = false) {
    const next = structuredClone(settings); const index = next.models.findIndex(m => m.id === model.id); next.models[index] = model;
    if (makeDefault) { next.runtime.default_model = model.id; next.models[index].visible = true; next.providers[model.provider].enabled = true; }
    updateSettings(next);
  }
  function remove(id) {
    const next = structuredClone(settings); next.models = next.models.filter(m => m.id !== id);
    if (next.runtime.default_model === id) next.runtime.default_model = next.models.find(m => m.visible)?.id || '';
    updateSettings(next); setSelected(null);
  }
  async function makePreview() {
    try { const result = await api('/api/preview', { settings }); setPreview(result); }
    catch (error) { notify(error.message, 'error'); }
  }
  return <div className="page models-page">
    <div className="model-toolbar"><label className="search-box"><Search size={16}/><input placeholder="Find a model…" value={query} onChange={e => setQuery(e.target.value)}/></label><div className="select-wrap filter-select"><select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All providers</option>{Object.entries(PROVIDERS).map(([id, meta]) => <option value={id} key={id}>{meta.name}</option>)}</select><ChevronRight size={14}/></div><button className="button secondary" onClick={makePreview}><Eye size={16}/>Preview</button><div className="add-model-wrap"><button className="button primary" onClick={() => setAddMenu(value => !value)}><Plus size={16}/>Add model{data.provider_catalog_status?.new_count > 0 && <span className="nav-count">{data.provider_catalog_status.new_count}</span>}<ChevronDown size={14}/></button>{addMenu && <><button className="add-menu-scrim" aria-label="Close add model menu" onClick={() => setAddMenu(false)}/><AddModelMenu data={data} notify={notify} onAvailable={(provider, model) => addModel(newModel(provider, model.id, model.name, settings))} onCustom={() => { setAddMenu(false); setCustomOpen(true); }} onLocal={() => { setAddMenu(false); setLocalOpen(true); }}/></>}</div></div>
    <div className="models-layout"><section className="panel models-list"><div className="list-header"><span>{settings.models.filter(m => m.visible).length} shown in Codex</span><span>Click a row to edit · drag to reorder</span></div>
      {models.map(model => <div key={model.id} className={`model-row ${selected === model.id ? 'selected' : ''} ${!model.visible ? 'hidden-model' : ''}`} draggable onDragStart={() => { dragIndex.current = model.index; }} onDragOver={e => e.preventDefault()} onDrop={() => move(dragIndex.current, model.index)} onClick={() => openEditor(model.id)}>
        <GripVertical className="grip" size={17}/><ProviderMark provider={model.provider}/><div className="model-row-copy"><strong>{model.display_name}</strong><span>{PROVIDERS[model.provider]?.name} · {model.upstream_id || model.id}</span><div className="model-tags"><span>{model.reasoning.default || 'no thinking'}</span>{model.tools.computer_use && <span><Monitor size={11}/>Computer Use</span>}{model.subagents && <span><Bot size={11}/>Cross-provider</span>}{model.provider === 'local' && <span><HardDrive size={11}/>{model.local?.protocol === 'openai_responses' ? 'Responses' : 'Chat'}</span>}</div></div>
        {model.id === settings.runtime.default_model && <Star className="default-star" size={15} fill="currentColor"/>}<div className="row-actions"><button className="icon-button edit-row" title="Edit model" onClick={e => { e.stopPropagation(); openEditor(model.id); }}><Pencil size={14}/></button><button className="icon-button" title="Move up" onClick={e => { e.stopPropagation(); move(model.index, model.index - 1); }}><ArrowUp size={14}/></button><button className="icon-button" title="Move down" onClick={e => { e.stopPropagation(); move(model.index, model.index + 1); }}><ArrowDown size={14}/></button><span onClick={e => e.stopPropagation()}><Toggle checked={model.visible} onChange={value => { const next = structuredClone(settings); next.models[model.index].visible = value; updateSettings(next); }} label={`Show ${model.display_name}`}/></span></div>
      </div>)}{models.length === 0 && <div className="empty-state"><Search size={24}/><p>No models match this filter.</p></div>}
      <div className="list-footer"><ShieldCheck size={14}/>Changes stay local until you save or apply.</div>
    </section><div ref={editorRef}><ModelEditor model={selectedModel} settings={settings} update={update} remove={remove} close={() => setSelected(null)}/></div></div>
    {customOpen && <CustomModelModal data={data} close={() => setCustomOpen(false)} onAdd={addModel}/>}
    {localOpen && <LocalModelModal data={data} close={() => setLocalOpen(false)} onAdd={addModel} notify={notify}/>}
    {preview && <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && setPreview(null)}><div className="modal panel"><div className="section-heading"><div><span className="eyebrow">GENERATED CATALOG</span><h3>{preview.models.length} models in Codex</h3></div><button className="icon-button" onClick={() => setPreview(null)}><X size={18}/></button></div><p className="modal-description">Every visible route on an enabled provider is included, including custom and edited upstream IDs.</p><div className="catalog-preview">{preview.included.map((m, i) => <div key={m.slug}><span>{i + 1}</span><strong>{m.display_name}</strong><code>{m.slug}</code></div>)}</div></div></div>}
  </div>;
}


function Capabilities({ settings }) {
  const rows = [
    ['Thinking levels', 'Per-model picker options', ['Native', 'Native + adapter', 'Native', 'Native', 'Chat or Responses']],
    ['Shell & file tools', 'Request-level tool policy', ['Native', 'Adapted', 'Function tools', 'Function tools', 'Function tools']],
    ['Computer Use', 'Codex namespace tool bridge', ['Native', 'Adapted', 'Bridged', 'Bridged', 'Bridged']],
    ['Hosted web search', 'Provider-hosted search declarations', ['Native', 'Not enabled', 'Not enabled', 'Not enabled', 'Not enabled']],
    ['Connected apps', 'Large Codex connector namespaces', ['Native', 'Excluded', 'Excluded', 'Excluded', 'Excluded']],
    ['Codex subagents', 'Multi-agent v2 catalog flag', ['Cross-provider', 'Cross-provider', 'Cross-provider', 'Cross-provider', 'Cross-provider']],
  ];
  return <div className="page"><div className="notice"><Monitor size={18}/><span>Computer Use bridging is preserved for Claude and available to standard Responses routes. Compatibility still depends on the upstream model’s tool-calling behavior.</span></div>
    <section className="panel capability-panel"><div className="capability-table"><div className="cap-row cap-head"><div>Capability</div>{Object.entries(PROVIDERS).map(([id, meta]) => <div key={id}><ProviderMark provider={id} size="small"/>{meta.name}</div>)}</div>{rows.map(([name, detail, values]) => <div className="cap-row" key={name}><div><strong>{name}</strong><span>{detail}</span></div>{values.map((value, i) => <div key={i}><span className={value.includes('Not') || value === 'Excluded' ? 'unavailable' : 'available'}>{!value.includes('Not') && value !== 'Excluded' && <Check size={13}/>} {value}</span></div>)}</div>)}</div></section>
    <div className="capability-notes"><section className="panel"><span className="metric-icon purple"><Gauge/></span><h3>Thinking that follows the model</h3><p>Each route advertises only the levels you enable. Claude uses Anthropic effort output; Kimi, OpenCode, and local routes map effort through their supported protocol.</p></section><section className="panel"><span className="metric-icon green"><ShieldCheck/></span><h3>Cross-provider delegation</h3><p>Every enabled subagent route is a multi-agent v2 target. A Claude parent can ask for a Kimi child, an OpenAI parent can ask for a local child, and credentials stay isolated per request.</p></section></div>
    <section className="panel config-summary"><div className="section-heading"><div><span className="eyebrow">YOUR CONFIGURATION</span><h3>Enabled across {settings.models.length} routes</h3></div></div><div className="summary-chips"><span><Monitor size={15}/>{settings.models.filter(m => m.tools.computer_use).length} Computer Use</span><span><Bot size={15}/>{settings.models.filter(m => m.subagents).length} Subagents</span><span><TerminalSquare size={15}/>{settings.models.filter(m => m.tools.shell).length} Shell tools</span></div></section>
  </div>;
}

function formatReset(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `Resets ${value}`;
  return `Resets ${date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}`;
}

function PlanUsage({ snapshot, loading }) {
  const statusLabel = { available: 'Live allowance', not_connected: 'Not connected', unavailable: 'Ledger only', error: 'Check failed' };
  return <section className="panel plan-usage-panel">
    <div className="section-heading"><div><span className="eyebrow">SUBSCRIPTION ALLOWANCES</span><h3>How much each plan has used</h3><p>Provider-reported limits for Codex, Claude, and Kimi. OpenCode and local lanes show routed token activity below when no allowance API is exposed.</p></div><Gauge size={19}/></div>
    {loading && !snapshot ? <div className="plan-loading"><LoaderCircle className="spin" size={19}/><span>Checking connected provider accounts…</span></div> : <div className="plan-usage-grid">{(snapshot?.providers || []).map(row => <article className={`plan-card plan-${row.status}`} key={row.provider}>
      <div className="plan-card-head"><ProviderMark provider={row.provider} size="small"/><div><strong>{PROVIDERS[row.provider]?.name || row.provider}</strong><span>{row.account}</span></div>{row.plan && <b>{row.plan}</b>}</div>
      <span className="plan-status"><i/>{statusLabel[row.status] || 'Unavailable'}</span>
      {row.windows?.length ? <div className="plan-windows">{row.windows.map(window => <div className="plan-window" key={`${window.label}-${window.resets_at}`}><div><span>{window.label}</span><strong>{window.used_percent}% used</strong></div><div className="plan-meter"><i style={{ width: `${Math.max(1, window.used_percent)}%` }}/></div><small>{[formatReset(window.resets_at), `${window.remaining_percent}% remaining`].filter(Boolean).join(' · ')}</small></div>)}</div> : <p className="plan-detail">{row.detail || 'This provider did not return a plan allowance.'}</p>}
    </article>)}</div>}
    <div className="plan-footnote"><ShieldCheck size={13}/>Allowance percentages are read directly from the provider and are not estimates. Token activity below comes from requests routed through Relay.</div>
  </section>;
}

function Usage({ data, notify }) {
  const [days, setDays] = useState(30);
  const [usage, setUsage] = useState(data.usage);
  const [subscription, setSubscription] = useState(null);
  const [loading, setLoading] = useState(false);
  async function refresh() {
    setLoading(true);
    const [ledger, allowances] = await Promise.allSettled([
      api(`/api/usage?days=${days}`), api('/api/subscription-usage'),
    ]);
    if (ledger.status === 'fulfilled') setUsage(ledger.value);
    else notify(ledger.reason?.message || 'Could not load the Relay usage ledger.', 'error');
    if (allowances.status === 'fulfilled') setSubscription(allowances.value);
    else notify(allowances.reason?.message || 'Could not read provider subscription allowances.', 'error');
    setLoading(false);
  }
  useEffect(() => { refresh(); }, [days]);
  const totals = usage?.totals || {};
  const dailyMax = Math.max(1, ...(usage?.daily || []).map(day => Number(day.total_tokens || 0)));
  return <div className="page usage-page">
    <div className="usage-toolbar"><div><span className="eyebrow">ACCOUNT LEDGER</span><h2>Usage across every account</h2><p>Live subscription allowances sit beside Relay's routed token ledger. Relay never stores prompts, responses, API keys, or OAuth tokens.</p></div><div className="usage-actions"><div className="select-wrap"><select value={days} onChange={event => setDays(Number(event.target.value))}><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select><ChevronRight size={14}/></div><button className="icon-button" onClick={refresh} title="Refresh usage"><RefreshCw className={loading ? 'spin' : ''} size={17}/></button></div></div>
    <div className="usage-metrics"><section><span>Total tokens</span><strong>{formatTokens(totals.total_tokens)}</strong><small>{totals.requests || 0} requests</small></section><section><span>Input</span><strong>{formatTokens(totals.input_tokens)}</strong><small>{formatTokens(totals.cached_tokens)} cached</small></section><section><span>Output</span><strong>{formatTokens(totals.output_tokens)}</strong><small>{formatTokens(totals.reasoning_tokens)} reasoning</small></section><section><span>Connected accounts</span><strong>{usage?.connected_accounts || 0}</strong><small>{usage?.accounts?.length || 0} tracked provider/local lanes</small></section></div>
    <PlanUsage snapshot={subscription} loading={loading}/>
    <div className="usage-layout"><section className="panel usage-chart-panel"><div className="section-heading"><div><span className="eyebrow">DAILY ACTIVITY</span><h3>Tokens by day</h3></div><Gauge size={19}/></div>{(usage?.daily || []).length ? <div className="usage-chart">{usage.daily.map(day => <div className="usage-day" key={day.day} title={`${day.day}: ${formatTokens(day.total_tokens)} tokens · ${day.requests} requests`}><div><i style={{ height: `${Math.max(4, Number(day.total_tokens) / dailyMax * 100)}%` }}/></div><span>{day.day.slice(5)}</span></div>)}</div> : <div className="empty-state usage-empty"><Gauge size={27}/><p>No usage has been recorded in this period. Send a request through Relay and it will appear here.</p></div>}</section>
      <section className="panel account-usage-panel"><div className="section-heading"><div><span className="eyebrow">ACCOUNTS</span><h3>Every connected lane</h3></div><Network size={19}/></div><div className="account-usage-list">{(usage?.accounts || []).map(row => <div key={`${row.provider}-${row.account}`} title={row.detail || ''} className={!row.connected ? 'account-inactive' : ''}><ProviderMark provider={row.provider} size="small"/><div><strong>{row.account}</strong><span>{PROVIDERS[row.provider]?.name || row.provider} · {row.requests || 0} requests{row.historical ? ' · historical' : row.connected ? '' : ' · not connected'}</span></div><code>{formatTokens(row.total_tokens)}</code></div>)}{!usage?.accounts?.length && <div className="empty-state"><Link2 size={24}/><p>No provider accounts are available yet.</p></div>}</div></section></div>
    <div className="usage-tables"><section className="panel"><div className="section-heading"><div><span className="eyebrow">MODELS</span><h3>Token distribution</h3></div><Layers3 size={19}/></div><div className="usage-table">{(usage?.models || []).map(row => <div className="usage-table-row" key={`${row.provider}-${row.model}`}><span><ProviderMark provider={row.provider} size="small"/><strong>{data.settings.models.find(model => model.id === row.model)?.display_name || row.model}</strong></span><span>{row.requests} req.</span><span>{formatTokens(row.total_tokens)} tokens</span></div>)}{!usage?.models?.length && <div className="empty-state"><p>Model usage will appear after the first routed request.</p></div>}</div></section>
      <section className="panel"><div className="section-heading"><div><span className="eyebrow">RECENT</span><h3>Latest requests</h3></div><Activity size={19}/></div><div className="usage-table recent-usage">{(usage?.recent || []).map((row, index) => <div className="usage-table-row" key={`${row.created_at}-${index}`}><span><ProviderMark provider={row.provider} size="small"/><strong>{row.model}</strong></span><span className={row.status >= 200 && row.status < 300 ? 'request-ok' : 'request-error'}>{row.status}</span><span>{formatTokens(row.total_tokens)}</span></div>)}{!usage?.recent?.length && <div className="empty-state"><p>No recent requests.</p></div>}</div></section></div>
    <div className="notice usage-notice"><ShieldCheck size={18}/><span>Subscription percentages are read live from provider accounts. The Relay ledger stores only provider, account label, model route, HTTP status, and token counts; prompts, responses, API keys, and OAuth tokens are never stored.</span></div>
  </div>;
}

function Diagnostics({ data, notify }) {
  const [diagnostics, setDiagnostics] = useState(null);
  const [loading, setLoading] = useState(false);
  async function refresh() {
    setLoading(true);
    try { setDiagnostics(await api('/api/diagnostics')); }
    catch (error) { notify(error.message, 'error'); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);
  const health = diagnostics?.router || data.router;
  const routerCurrent = !health?.relay_version || health.relay_version === data.version;
  const routeHealth = diagnostics?.route_health || data.route_health;
  const catalog = diagnostics?.provider_catalog || data.provider_catalog_status;
  const issues = [...(routeHealth?.errors || []), ...(routeHealth?.warnings || [])];
  return <div className="page"><div className="diagnostic-grid"><section className="panel health-card"><div className="section-heading"><div><span className="eyebrow">LOCAL SERVICE</span><h3>Router health</h3></div><button className="icon-button" onClick={refresh}><RefreshCw size={17} className={loading ? 'spin' : ''}/></button></div><div className={`health-orb ${health.reachable ? 'online' : ''}`}><Activity size={28}/></div><h2>{health.reachable ? 'Router is responding' : 'Router is on standby'}</h2><p>{health.reachable ? `${health.models ?? '—'} enabled routes · namespace bridge v${health.namespace_bridge ?? '—'}` : health.detail || 'Start the updated router when you are ready.'}</p><span className="endpoint"><span className="live-dot"/>127.0.0.1 only</span></section>
    <section className="panel paths-card"><div className="section-heading"><div><span className="eyebrow">LOCAL FILES</span><h3>Configuration locations</h3></div><FileJson size={19}/></div><label>Preferences<code>{data.settings_location}</code></label><label>Generated Codex catalog<code>{data.catalog_location}</code></label><label>Usage ledger<code>{data.usage_location}</code></label><div className="safe-note">Settings contain no API keys or OAuth tokens. Backups are created before every saved change.</div><button className="button secondary" onClick={() => { const blob = new Blob([JSON.stringify(data.settings, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'router-settings-export.json'; a.click(); URL.revokeObjectURL(url); }}><Download size={15}/>Export safe preferences</button></section></div>
    <section className={`panel route-issues-panel ${routeHealth?.status || 'ready'}`}><div className="section-heading"><div><span className="eyebrow">ROUTE CHECKS</span><h3>{issues.length ? `${issues.length} model issue${issues.length === 1 ? '' : 's'} need attention` : 'Every configured route looks healthy'}</h3></div><span className="local-badge">{routeHealth?.routes_checked ?? data.settings.models.length} CHECKED</span></div>
      <div className="catalog-freshness"><span>Provider catalogs: <strong>{catalog?.stale ? 'refreshing' : 'current'}</strong>{catalog?.checked_at ? ` · ${catalog.checked_at}` : ''}</span>{catalog?.new_count > 0 && <span><strong>{catalog.new_count} new model{catalog.new_count === 1 ? '' : 's'}</strong> available in Add model</span>}</div>
      {issues.length ? <div className="route-issue-list">{issues.map((issue, index) => <div className={`route-issue ${routeHealth?.errors?.includes(issue) ? 'error' : 'warning'}`} key={`${issue.route_id}-${issue.code}-${index}`}><ProviderMark provider={issue.provider} size="small"/><div><strong>{issue.message}</strong><p>{issue.action}</p><code>{issue.code} · {issue.route_id}</code></div></div>)}</div> : <div className="healthy-routes"><Check size={20}/><div><strong>Credentials and cataloged upstream IDs match</strong><span>Custom IDs are allowed and will be checked again after the next provider catalog refresh.</span></div></div>}
    </section>
    {!routerCurrent && <div className="notice route-version-notice"><RefreshCw size={17}/><span><strong>Router update pending.</strong> Relay {data.version} is installed, while the running router is {health.relay_version}. Your active session was not restarted; the new router loads automatically the next time Codex and Router start normally.</span></div>}
    <section className="panel logs-panel"><div className="section-heading"><div><span className="eyebrow">SANITIZED ACTIVITY</span><h3>Recent router events</h3></div><span className="local-badge">REDACTED</span></div><div className="log-view">{diagnostics?.log?.length ? diagnostics.log.map((line, i) => <code key={i}>{line}</code>) : <div className="empty-state"><TerminalSquare size={23}/><p>No local router log is available in this development environment.</p></div>}</div></section>
  </div>;
}

export default function App() {
  const [page, setPage] = useState(() => {
    const requested = window.location.hash.slice(1);
    return Object.hasOwn(PAGE_META, requested) ? requested : 'overview';
  });
  const [data, setData] = useState(null);
  const [settings, setSettings] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState('');
  const [toast, setToast] = useState(null);
  const [mobileNav, setMobileNav] = useState(false);
  const toastTimer = useRef(null);
  function notify(message, type = 'success') { clearTimeout(toastTimer.current); setToast({ message, type }); toastTimer.current = setTimeout(() => setToast(null), 5000); }
  async function reload() {
    try { const next = await api('/api/state'); setData(next); setSettings(next.settings); setDirty(false); }
    catch (error) { notify(error.message, 'error'); }
  }
  useEffect(() => { reload(); }, []);
  useEffect(() => { window.history.replaceState(null, '', `#${page}`); }, [page]);
  function updateSettings(next) {
    if (!isSelectableDefault(next)) {
      const replacement = findSelectableDefault(next);
      if (!replacement) {
        notify('Keep at least one visible model on an enabled provider.', 'error');
        return;
      }
      next.runtime.default_model = replacement.id;
      notify(`Default model switched to ${replacement.display_name} so the picker always has a valid selection.`);
    }
    setSettings(next);
    setDirty(true);
    setData(current => ({ ...current, settings: next }));
  }
  async function save(apply = false) {
    setBusy(apply ? 'apply' : 'save');
    try {
      const result = await api(apply ? '/api/apply' : '/api/settings', { settings });
      notify(result.message || 'Preferences saved with a local backup.');
      await reload();
    } catch (error) { notify(error.message, 'error'); }
    finally { setBusy(''); }
  }
  const currentData = data && settings ? { ...data, settings } : null;
  const [title, subtitle] = PAGE_META[page];
  const nav = [['overview', 'Overview', CircleGauge], ['connections', 'Connections', Link2], ['models', 'Model picker', Layers3], ['usage', 'Usage', Gauge], ['capabilities', 'Capabilities', WandSparkles], ['diagnostics', 'Diagnostics', Activity]];
  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}><div className="brand"><div className="brand-mark"><Network size={23}/></div><div><strong>relay</strong><span>CODEX ROUTER</span></div><button className="icon-button mobile-close" onClick={() => setMobileNav(false)}><X size={18}/></button></div>
      <nav><span className="nav-label">WORKSPACE</span>{nav.map(([id, label, Icon]) => <button className={page === id ? 'active' : ''} key={id} onClick={() => { setPage(id); setMobileNav(false); }}><Icon size={18}/>{label}{id === 'models' && currentData && <span className="nav-count">{currentData.settings.models.filter(m => m.visible).length}</span>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="local-card"><ShieldCheck size={18}/><div><strong>Your machine. Your keys.</strong><span>Loopback-only management</span></div></div><a href="https://github.com/JacksonSibold/codex-subscription-router" target="_blank" rel="noreferrer" className="github-link"><Github size={17}/>Open source<ExternalLink size={12}/></a><div className="version">RELAY {currentData?.version || RELAY_VERSION} <span>•</span> LOCAL</div></div>
    </aside>
    {mobileNav && <div className="nav-scrim" onClick={() => setMobileNav(false)}/>}
    <main><header className="topbar"><button className="icon-button mobile-menu" onClick={() => setMobileNav(true)}><Menu size={20}/></button><div><h1>{title}</h1><p>{subtitle}</p></div><div className="header-actions">{dirty && <span className="unsaved"><i/>Unsaved changes</span>}<button className="button secondary save-button" disabled={!dirty || !!busy} onClick={() => save(false)}>{busy === 'save' ? <LoaderCircle className="spin" size={16}/> : <Save size={16}/>}<span>Save</span></button><button className="button primary apply-button" disabled={!dirty || !!busy} onClick={() => save(true)}>{busy === 'apply' ? <LoaderCircle className="spin" size={16}/> : <Zap size={16}/>}<span>{data?.live_apply ? 'Save & apply' : 'Save & generate'}</span></button></div></header>
      <div className="content">{currentData ? <>
        {page === 'overview' && <Overview data={currentData} setPage={setPage}/>}
        {page === 'connections' && <Connections data={currentData} updateSettings={updateSettings} reload={reload} notify={notify} setPage={setPage}/>}
        {page === 'models' && <ModelsPage data={currentData} updateSettings={updateSettings} notify={notify}/>}
        {page === 'usage' && <Usage data={currentData} notify={notify}/>}
        {page === 'capabilities' && <Capabilities settings={currentData.settings}/>}
        {page === 'diagnostics' && <Diagnostics data={currentData} notify={notify}/>}
      </> : <div className="loading-screen"><div className="brand-mark"><Network size={27}/></div><LoaderCircle className="spin" size={23}/><p>Opening your local control center…</p></div>}</div>
    </main>
    {toast && <div className={`toast ${toast.type}`}><span>{toast.type === 'error' ? <X size={17}/> : <Check size={17}/>}</span><p>{toast.message}</p><button onClick={() => setToast(null)}><X size={15}/></button></div>}
  </div>;
}
