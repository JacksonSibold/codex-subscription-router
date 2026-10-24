import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, ArrowDown, ArrowUp, BookOpen, Bot, Box, Check, ChevronRight,
  CircleGauge, Cloud, Code2, Copy, Cpu, Download, ExternalLink, Eye, EyeOff,
  FileJson, Gauge, Github, GripVertical, KeyRound, Layers3, Link2, LoaderCircle,
  Menu, Monitor, MoreHorizontal, Network, PanelLeftClose, Plus, RefreshCw,
  Save, Search, Settings2, ShieldCheck, Sparkles, Star, TerminalSquare, Trash2,
  WandSparkles, X, Zap,
} from 'lucide-react';

const PROVIDERS = {
  openai: { name: 'OpenAI', short: 'OAI', color: '#a7f3d0', description: 'ChatGPT subscription through Codex', icon: Sparkles },
  anthropic: { name: 'Claude Pro', short: 'CL', color: '#e8b49b', description: 'Claude Pro through OpenCode OAuth', icon: Bot },
  kimi: { name: 'Kimi Code', short: 'KM', color: '#b7c8ff', description: 'Kimi membership native Responses API', icon: MoonIcon },
  opencode: { name: 'OpenCode Go', short: 'GO', color: '#e8d58b', description: 'Your OpenCode Go model catalog', icon: Code2 },
};
const EFFORTS = ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
const PAGE_META = {
  overview: ['Your subscriptions, one workspace.', 'Manage every model route without giving up the Codex experience.'],
  connections: ['Connections', 'Use official sign-in flows. Credentials stay in their provider stores.'],
  models: ['Model picker', 'Choose exactly what appears in Codex, and how it behaves.'],
  capabilities: ['Capabilities', 'A clear view of thinking, tools, Computer Use, and delegation.'],
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
  const good = status === 'credential_found' || status === true;
  const label = good ? 'Credential found' : status === 'unknown' ? 'Check in Codex' : 'Not connected';
  return <span className={`status-pill ${good ? 'good' : ''}`}><i/>{label}</span>;
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
  const { settings, providers, router, catalog } = data;
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
      <button className="metric-card" onClick={() => setPage('connections')}><span className="metric-icon green"><Link2/></span><div><strong>{connected}<small> / 4</small></strong><span>Credentials found</span></div><ChevronRight size={17}/></button>
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

function Connections({ data, updateSettings, reload, notify }) {
  const { settings, providers } = data;
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
  return <div className="page">
    <div className="notice"><ShieldCheck size={18}/><span>Relay detects whether credentials exist, but never displays them. “Credential found” is not a billed API test.</span></div>
    <div className="connection-grid">{Object.entries(PROVIDERS).map(([id, meta]) => {
      const state = providers[id] || {};
      const enabled = settings.providers[id].enabled;
      return <section className={`panel connection-card ${!enabled ? 'disabled-card' : ''}`} key={id}>
        <div className="connection-top"><ProviderMark provider={id}/><Toggle checked={enabled} onChange={value => setEnabled(id, value)} label={`Enable ${meta.name}`}/></div>
        <div className="connection-title"><h3>{meta.name}</h3><StatusPill status={state.status}/></div>
        <p>{meta.description}</p><div className="credential-detail"><KeyRound size={14}/>{state.detail || state.auth}</div>
        {(id === 'kimi' || id === 'opencode') ? <>
          <KeyForm provider={id} onDone={reload} notify={notify}/>
          <button className="text-button docs-link" onClick={() => action(id, 'docs')}>Open official key console <ExternalLink size={13}/></button>
        </> : <div className="connection-actions"><button className="button secondary" onClick={() => action(id, 'login')}><ExternalLink size={15}/>{id === 'openai' ? 'Open Codex sign-in' : 'Open OpenCode OAuth'}</button><button className="icon-button" title="Official documentation" onClick={() => action(id, 'docs')}><BookOpen size={17}/></button></div>}
        {id === 'anthropic' && <div className="safe-note">Uses OpenCode’s Anthropic connection only. Your separate work Claude Code setup is never read or changed.</div>}
      </section>;
    })}</div>
    <section className="panel environment-note"><TerminalSquare size={22}/><div><h3>Write-only API key storage</h3><p>Kimi and OpenCode keys are saved to the Windows current-user environment. Existing Codex requests keep running; newly routed requests read the updated value.</p></div></section>
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
  return <aside className="panel model-editor"><div className="editor-heading"><div><span className="eyebrow">MODEL SETTINGS</span><h3>Customize route</h3></div><button className="icon-button" onClick={close}><X size={17}/></button></div>
    <div className="editor-model-id"><ProviderMark provider={model.provider}/><div><strong>{meta.name}</strong><code>{model.id}</code></div></div>
    <label className="field"><span>Picker display name</span><input value={model.display_name} maxLength={120} onChange={e => change(next => { next.display_name = e.target.value; })}/></label>
    <div className="field"><span>Default thinking level</span><div className="select-wrap"><select value={model.reasoning.default || ''} disabled={!model.reasoning.supported.length} onChange={e => change(next => { next.reasoning.default = e.target.value || null; })}>{model.reasoning.supported.map(e => <option key={e}>{e}</option>)}</select><ChevronRight size={14}/></div></div>
    <div className="field"><span>Available thinking levels</span><div className="effort-options">{EFFORTS.map(effort => <button key={effort} className={model.reasoning.supported.includes(effort) ? 'selected' : ''} onClick={() => toggleEffort(effort)}>{model.reasoning.supported.includes(effort) && <Check size={12}/>} {effort}</button>)}</div><small>Only levels supported by this model should be enabled.</small></div>
    <div className="editor-section"><span className="field-label">TOOLS & AGENTS</span>
      {[['shell', 'Shell & file tools', TerminalSquare], ['computer_use', 'Computer Use bridge', Monitor], ['web_search', 'Hosted web search', Search], ['connected_apps', 'Connected apps', Cloud]].map(([key, label, Icon]) => <div className="setting-row" key={key}><Icon size={16}/><span>{label}{unsupported && (key === 'web_search' || key === 'connected_apps') && <small>OpenAI only</small>}</span><Toggle checked={model.tools[key]} disabled={unsupported && (key === 'web_search' || key === 'connected_apps')} onChange={value => change(next => { next.tools[key] = value; })} label={label}/></div>)}
      <div className="setting-row"><Bot size={16}/><span>Codex subagents<small>Catalog multi-agent support</small></span><Toggle checked={model.subagents} onChange={value => change(next => { next.subagents = value; })} label="Codex subagents"/></div>
    </div>
    <button className={`button full ${model.id === settings.runtime.default_model ? 'default-selected' : 'secondary'}`} onClick={() => update(model, true)}><Star size={15} fill={model.id === settings.runtime.default_model ? 'currentColor' : 'none'}/>{model.id === settings.runtime.default_model ? 'Default Codex model' : 'Make default model'}</button>
    <button className="text-button danger remove-model" onClick={() => remove(model.id)}><Trash2 size={14}/>Remove from configuration</button>
  </aside>;
}

function AddModelModal({ data, onAdd, close }) {
  const [provider, setProvider] = useState('anthropic');
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const suggestions = data.available_models.filter(m => m.provider === provider && !data.settings.models.some(existing => existing.id === m.id));
  function submit(event) {
    event.preventDefault();
    if (!id.trim() || !name.trim()) return;
    const efforts = provider === 'kimi' ? ['low', 'high', 'max'] : provider === 'opencode' ? ['low', 'medium', 'high'] : ['low', 'medium', 'high', 'xhigh', 'max'];
    onAdd({ id: id.trim(), provider, display_name: name.trim(), visible: true, reasoning: { default: efforts.includes('medium') ? 'medium' : efforts.at(-1), supported: efforts }, tools: { shell: true, computer_use: true, web_search: provider === 'openai', connected_apps: provider === 'openai' }, subagents: true });
  }
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && close()}><form className="modal panel" onSubmit={submit}><div className="section-heading"><div><span className="eyebrow">NEW ROUTE</span><h3>Add a model</h3></div><button type="button" className="icon-button" onClick={close}><X size={18}/></button></div>
    <label className="field"><span>Provider</span><div className="provider-choice">{Object.entries(PROVIDERS).map(([key, meta]) => <button type="button" key={key} className={provider === key ? 'selected' : ''} onClick={() => { setProvider(key); setId(''); }}><ProviderMark provider={key} size="small"/>{meta.name}</button>)}</div></label>
    {suggestions.length > 0 && <div className="field"><span>Discovered locally</span><div className="suggestions">{suggestions.slice(0, 5).map(m => <button type="button" key={m.id} onClick={() => { setId(m.id); setName(m.name); }}>{m.name}</button>)}</div></div>}
    <label className="field"><span>Upstream model ID</span><input required value={id} onChange={e => setId(e.target.value)} placeholder={provider === 'anthropic' ? 'claude-sonnet-5-5' : provider === 'kimi' ? 'k3.1-pro-highspeed' : 'provider-model-id'}/><small>Must exactly match the provider’s model identifier.</small></label>
    <label className="field"><span>Display name</span><input required value={name} onChange={e => setName(e.target.value)} placeholder="My model"/></label>
    <div className="modal-actions"><button type="button" className="button secondary" onClick={close}>Cancel</button><button className="button primary"><Plus size={16}/>Add model</button></div>
  </form></div>;
}

function ModelsPage({ data, updateSettings, notify }) {
  const { settings } = data;
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [adding, setAdding] = useState(false);
  const [preview, setPreview] = useState(null);
  const dragIndex = useRef(null);
  const selectedModel = settings.models.find(m => m.id === selected);
  const models = settings.models.map((m, index) => ({ ...m, index })).filter(m => (filter === 'all' || m.provider === filter) && `${m.display_name} ${m.id}`.toLowerCase().includes(query.toLowerCase()));
  function move(from, to) {
    if (from === to || from < 0 || to < 0 || to >= settings.models.length) return;
    const next = structuredClone(settings); const [item] = next.models.splice(from, 1); next.models.splice(to, 0, item); updateSettings(next);
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
    <div className="model-toolbar"><label className="search-box"><Search size={16}/><input placeholder="Find a model…" value={query} onChange={e => setQuery(e.target.value)}/></label><div className="select-wrap filter-select"><select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All providers</option>{Object.entries(PROVIDERS).map(([id, meta]) => <option value={id} key={id}>{meta.name}</option>)}</select><ChevronRight size={14}/></div><button className="button secondary" onClick={makePreview}><Eye size={16}/>Preview</button><button className="button primary" onClick={() => setAdding(true)}><Plus size={16}/>Add model</button></div>
    <div className="models-layout"><section className="panel models-list"><div className="list-header"><span>{settings.models.filter(m => m.visible).length} shown in Codex</span><span>Drag to reorder</span></div>
      {models.map(model => <div key={model.id} className={`model-row ${selected === model.id ? 'selected' : ''} ${!model.visible ? 'hidden-model' : ''}`} draggable onDragStart={() => { dragIndex.current = model.index; }} onDragOver={e => e.preventDefault()} onDrop={() => move(dragIndex.current, model.index)} onClick={() => setSelected(model.id)}>
        <GripVertical className="grip" size={17}/><ProviderMark provider={model.provider}/><div className="model-row-copy"><strong>{model.display_name}</strong><span>{model.id}</span><div className="model-tags"><span>{model.reasoning.default || 'no thinking'}</span>{model.tools.computer_use && <span><Monitor size={11}/>Computer Use</span>}{model.subagents && <span><Bot size={11}/>Subagents</span>}</div></div>
        {model.id === settings.runtime.default_model && <Star className="default-star" size={15} fill="currentColor"/>}<div className="row-actions"><button className="icon-button" title="Move up" onClick={e => { e.stopPropagation(); move(model.index, model.index - 1); }}><ArrowUp size={14}/></button><button className="icon-button" title="Move down" onClick={e => { e.stopPropagation(); move(model.index, model.index + 1); }}><ArrowDown size={14}/></button><Toggle checked={model.visible} onChange={value => { const next = structuredClone(settings); next.models[model.index].visible = value; updateSettings(next); }} label={`Show ${model.display_name}`}/></div>
      </div>)}{models.length === 0 && <div className="empty-state"><Search size={24}/><p>No models match this filter.</p></div>}
      <div className="list-footer"><ShieldCheck size={14}/>Changes stay local until you save or apply.</div>
    </section><ModelEditor model={selectedModel} settings={settings} update={update} remove={remove} close={() => setSelected(null)}/></div>
    {adding && <AddModelModal data={data} close={() => setAdding(false)} onAdd={model => { const next = structuredClone(settings); next.models.push(model); updateSettings(next); setAdding(false); setSelected(model.id); }}/>}
    {preview && <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && setPreview(null)}><div className="modal panel"><div className="section-heading"><div><span className="eyebrow">GENERATED CATALOG</span><h3>{preview.models.length} models in Codex</h3></div><button className="icon-button" onClick={() => setPreview(null)}><X size={18}/></button></div><p className="modal-description">This preview uses your local model metadata. Missing upstream IDs are omitted.</p><div className="catalog-preview">{preview.included.map((m, i) => <div key={m.slug}><span>{i + 1}</span><strong>{m.display_name}</strong><code>{m.slug}</code></div>)}</div></div></div>}
  </div>;
}

function Capabilities({ settings }) {
  const rows = [
    ['Thinking levels', 'Per-model picker options', ['Native', 'Native + adapter', 'Native', 'Native']],
    ['Shell & file tools', 'Request-level tool policy', ['Native', 'Adapted', 'Function tools', 'Function tools']],
    ['Computer Use', 'Codex namespace tool bridge', ['Native', 'Adapted', 'Bridged', 'Bridged']],
    ['Hosted web search', 'Provider-hosted search declarations', ['Native', 'Not enabled', 'Not enabled', 'Not enabled']],
    ['Connected apps', 'Large Codex connector namespaces', ['Native', 'Excluded', 'Excluded', 'Excluded']],
    ['Codex subagents', 'Multi-agent v2 catalog flag', ['Configurable', 'Configurable', 'Configurable', 'Configurable']],
  ];
  return <div className="page"><div className="notice"><Monitor size={18}/><span>Computer Use bridging is preserved for Claude and available to standard Responses routes. Compatibility still depends on the upstream model’s tool-calling behavior.</span></div>
    <section className="panel capability-panel"><div className="capability-table"><div className="cap-row cap-head"><div>Capability</div>{Object.entries(PROVIDERS).map(([id, meta]) => <div key={id}><ProviderMark provider={id} size="small"/>{meta.name}</div>)}</div>{rows.map(([name, detail, values]) => <div className="cap-row" key={name}><div><strong>{name}</strong><span>{detail}</span></div>{values.map((value, i) => <div key={i}><span className={value.includes('Not') || value === 'Excluded' ? 'unavailable' : 'available'}>{!value.includes('Not') && value !== 'Excluded' && <Check size={13}/>} {value}</span></div>)}</div>)}</div></section>
    <div className="capability-notes"><section className="panel"><span className="metric-icon purple"><Gauge/></span><h3>Thinking that follows the model</h3><p>Each route advertises only the levels you enable. Claude uses Anthropic effort output; Kimi and OpenCode use Responses reasoning.</p></section><section className="panel"><span className="metric-icon green"><ShieldCheck/></span><h3>Guardrails, not guesswork</h3><p>Unsupported hosted tools are excluded before forwarding. Tool choices are enforced on every request, not just shown in the interface.</p></section></div>
    <section className="panel config-summary"><div className="section-heading"><div><span className="eyebrow">YOUR CONFIGURATION</span><h3>Enabled across {settings.models.length} routes</h3></div></div><div className="summary-chips"><span><Monitor size={15}/>{settings.models.filter(m => m.tools.computer_use).length} Computer Use</span><span><Bot size={15}/>{settings.models.filter(m => m.subagents).length} Subagents</span><span><TerminalSquare size={15}/>{settings.models.filter(m => m.tools.shell).length} Shell tools</span></div></section>
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
  return <div className="page"><div className="diagnostic-grid"><section className="panel health-card"><div className="section-heading"><div><span className="eyebrow">LOCAL SERVICE</span><h3>Router health</h3></div><button className="icon-button" onClick={refresh}><RefreshCw size={17} className={loading ? 'spin' : ''}/></button></div><div className={`health-orb ${health.reachable ? 'online' : ''}`}><Activity size={28}/></div><h2>{health.reachable ? 'Router is responding' : 'Router is on standby'}</h2><p>{health.reachable ? `${health.models ?? '—'} enabled routes · namespace bridge v${health.namespace_bridge ?? '—'}` : health.detail || 'Start the updated router when you are ready.'}</p><span className="endpoint"><span className="live-dot"/>127.0.0.1 only</span></section>
    <section className="panel paths-card"><div className="section-heading"><div><span className="eyebrow">LOCAL FILES</span><h3>Configuration locations</h3></div><FileJson size={19}/></div><label>Preferences<code>{data.settings_location}</code></label><label>Generated Codex catalog<code>{data.catalog_location}</code></label><div className="safe-note">Settings contain no API keys or OAuth tokens. Backups are created before every saved change.</div><button className="button secondary" onClick={() => { const blob = new Blob([JSON.stringify(data.settings, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'router-settings-export.json'; a.click(); URL.revokeObjectURL(url); }}><Download size={15}/>Export safe preferences</button></section></div>
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
  function updateSettings(next) { setSettings(next); setDirty(true); setData(current => ({ ...current, settings: next })); }
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
  const nav = [['overview', 'Overview', CircleGauge], ['connections', 'Connections', Link2], ['models', 'Model picker', Layers3], ['capabilities', 'Capabilities', WandSparkles], ['diagnostics', 'Diagnostics', Activity]];
  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}><div className="brand"><div className="brand-mark"><Network size={23}/></div><div><strong>relay</strong><span>CODEX ROUTER</span></div><button className="icon-button mobile-close" onClick={() => setMobileNav(false)}><X size={18}/></button></div>
      <nav><span className="nav-label">WORKSPACE</span>{nav.map(([id, label, Icon]) => <button className={page === id ? 'active' : ''} key={id} onClick={() => { setPage(id); setMobileNav(false); }}><Icon size={18}/>{label}{id === 'models' && currentData && <span className="nav-count">{currentData.settings.models.filter(m => m.visible).length}</span>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="local-card"><ShieldCheck size={18}/><div><strong>Your machine. Your keys.</strong><span>Loopback-only management</span></div></div><a href="https://github.com/JacksonSibold/codex-subscription-router" target="_blank" rel="noreferrer" className="github-link"><Github size={17}/>Open source<ExternalLink size={12}/></a><div className="version">RELAY 0.1.0 <span>•</span> LOCAL</div></div>
    </aside>
    {mobileNav && <div className="nav-scrim" onClick={() => setMobileNav(false)}/>}
    <main><header className="topbar"><button className="icon-button mobile-menu" onClick={() => setMobileNav(true)}><Menu size={20}/></button><div><h1>{title}</h1><p>{subtitle}</p></div><div className="header-actions">{dirty && <span className="unsaved"><i/>Unsaved changes</span>}<button className="button secondary save-button" disabled={!dirty || !!busy} onClick={() => save(false)}>{busy === 'save' ? <LoaderCircle className="spin" size={16}/> : <Save size={16}/>}<span>Save</span></button><button className="button primary apply-button" disabled={!dirty || !!busy} onClick={() => save(true)}>{busy === 'apply' ? <LoaderCircle className="spin" size={16}/> : <Zap size={16}/>}<span>{data?.live_apply ? 'Save & apply' : 'Save & generate'}</span></button></div></header>
      <div className="content">{currentData ? <>
        {page === 'overview' && <Overview data={currentData} setPage={setPage}/>} 
        {page === 'connections' && <Connections data={currentData} updateSettings={updateSettings} reload={reload} notify={notify}/>} 
        {page === 'models' && <ModelsPage data={currentData} updateSettings={updateSettings} notify={notify}/>} 
        {page === 'capabilities' && <Capabilities settings={currentData.settings}/>} 
        {page === 'diagnostics' && <Diagnostics data={currentData} notify={notify}/>} 
      </> : <div className="loading-screen"><div className="brand-mark"><Network size={27}/></div><LoaderCircle className="spin" size={23}/><p>Opening your local control center…</p></div>}</div>
    </main>
    {toast && <div className={`toast ${toast.type}`}><span>{toast.type === 'error' ? <X size={17}/> : <Check size={17}/>}</span><p>{toast.message}</p><button onClick={() => setToast(null)}><X size={15}/></button></div>}
  </div>;
}
