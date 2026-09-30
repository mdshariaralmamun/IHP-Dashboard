'use client';

import { useCallback, useEffect, useState } from 'react';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { useTheme } from '@/components/ThemeProvider';
import { useUser } from '@/lib/useUser';
import { listAiProviders, testAiProvider, type AiProviderInfo } from '@/lib/api';

interface SettingsResp {
  ai_provider: string;
  ai_provider_label: string;
  ai_provider_kind: string;
  ai_provider_docs: string;
  ai_provider_local: boolean;
  ai_base_url: string;
  ai_chat_model: string;
  ai_embed_model: string;
  ai_embed_provider: string;
  ai_api_key_present: boolean;
  ai_key_env: string;
  theme: string;
  overrides: Record<string, unknown>;
  env: { AI_BASE_URL: string; AI_CHAT_MODEL: string; AI_EMBED_MODEL: string };
  vat_rate: number;
  usd_sar_rate: number;
  default_currency: string;
  archive_path: string;
  trackers_dir: string;
  pr_request_dir: string;
}

interface TrackerFilesResp {
  trackers_dir: string;
  planner_latest: string | null;
  om_latest: string | null;
  pr_request_dir: string;
  pr_request_dir_exists: boolean;
  pr_request_pdfs: { filename: string; size_kb: number }[];
  pr_request_count: number;
  note: string;
}

interface TestResp {
  ok: boolean;
  latency_ms?: number;
  url?: string;
  models?: string[];
  model?: string;
  reply?: string;
  base_url?: string;
  error?: string;
  hint?: string;
}

/** Providers offered as one-click chips (the full list lives in the select). */
const QUICK_PICKS = ['ollama', 'deepseek', 'openai', 'anthropic', 'google-gemini', 'openrouter'];

const OPENROUTER_FREE_MODELS = [
  { id: 'nvidia/nemotron-3-ultra-550b-a55b:free', label: 'NVIDIA Nemotron 3 Ultra 550B' },
  { id: 'deepseek/deepseek-chat', label: 'DeepSeek Chat' },
  { id: 'google/gemma-2-27b-it', label: 'Google Gemma 2 27B' },
];

export default function SettingsPage() {
  return (
    <AuthGuard>
      <SettingsView />
    </AuthGuard>
  );
}

function SettingsView() {
  const { user } = useUser();
  const { theme: liveTheme, setTheme: setLiveTheme } = useTheme();
  const [token, setToken] = useState<string | null>(null);
  const [data, setData] = useState<SettingsResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const [baseUrl, setBaseUrl] = useState('');
  const [chatModel, setChatModel] = useState('');
  const [embedModel, setEmbedModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [aiProvider, setAiProvider] = useState('ollama');
  const [theme, setTheme] = useState('kaust');
  const [vatRate, setVatRate] = useState(0.15);
  const [usdSarRate, setUsdSarRate] = useState(3.75);
  const [defaultCurrency, setDefaultCurrency] = useState('SAR');
  const [archivePath, setArchivePath] = useState('');
  const [trackersDir, setTrackersDir] = useState('');
  const [prRequestDir, setPrRequestDir] = useState('');
  const [trackerFiles, setTrackerFiles] = useState<TrackerFilesResp | null>(null);
  const [test, setTest] = useState<TestResp | null>(null);
  const [testing, setTesting] = useState(false);
  const [providers, setProviders] = useState<AiProviderInfo[]>([]);

  useEffect(() => {
    setToken(localStorage.getItem('ihp_access_token'));
  }, []);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch('/api/admin/settings', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`Failed: ${r.status}`);
      const d: SettingsResp = await r.json();
      setData(d);
      setAiProvider(d.ai_provider || 'ollama');
      setBaseUrl(d.ai_base_url);
      setChatModel(d.ai_chat_model);
      setEmbedModel(d.ai_embed_model);
      setApiKey('');
      setTheme(d.theme);
      setVatRate(d.vat_rate);
      setUsdSarRate(d.usd_sar_rate);
      setDefaultCurrency(d.default_currency);
      setArchivePath(d.archive_path);
      setTrackersDir(d.trackers_dir ?? '');
      setPrRequestDir(d.pr_request_dir ?? '');
      // The provider catalogue drives the picker below.
      listAiProviders()
        .then((catalogue) => setProviders(catalogue.providers))
        .catch(() => setProviders([]));
      // Also fetch live tracker-file resolution (newest dated versions)
      fetch('/api/admin/settings/tracker-files', {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((t: TrackerFilesResp | null) => setTrackerFiles(t))
        .catch(() => setTrackerFiles(null));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { void load(); }, [load]);

  async function save() {
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      const r = await fetch('/api/admin/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          ai_provider: aiProvider,
          ai_base_url: baseUrl,
          ai_chat_model: chatModel,
          ai_embed_model: embedModel,
          ai_api_key: apiKey || undefined,
          theme,
          vat_rate: vatRate,
          usd_sar_rate: usdSarRate,
          default_currency: defaultCurrency,
          archive_path: archivePath,
          trackers_dir: trackersDir,
          pr_request_dir: prRequestDir,
        }),
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(`Save failed (${r.status}): ${t.slice(0, 200)}`);
      }
      const d: SettingsResp = await r.json();
      setData(d);
      setSavedAt(Date.now());
      setApiKey('');
      // Re-resolve tracker files against the (possibly new) directories
      fetch('/api/admin/settings/tracker-files', {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r2) => (r2.ok ? r2.json() : null))
        .then((t: TrackerFilesResp | null) => setTrackerFiles(t))
        .catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  async function clearOverrides() {
    if (!token) return;
    if (!confirm('Revert all AI settings to the values defined in backend/.env?')) return;
    setSaving(true);
    try {
      const r = await fetch('/api/admin/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ clear: ['AI_PROVIDER', 'AI_BASE_URL', 'AI_CHAT_MODEL', 'AI_EMBED_MODEL', 'AI_API_KEY', 'OPENROUTER_API_KEY'] }),
      });
      if (!r.ok) throw new Error('Failed');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Clear failed');
    } finally {
      setSaving(false);
    }
  }

  /** Probe the provider exactly as typed - credentials are not stored. */
  async function testConnection() {
    setTesting(true);
    setTest(null);
    try {
      const result = await testAiProvider({
        provider: aiProvider,
        model: chatModel || undefined,
        base_url: baseUrl || undefined,
        api_key: apiKey || undefined,
      });
      setTest({
        ok: result.ok,
        model: result.model,
        reply: result.reply,
        latency_ms: result.seconds ? Math.round(result.seconds * 1000) : undefined,
        error: result.ok ? undefined : result.error ?? 'No response from the provider.',
        hint: providers.find((p) => p.id === aiProvider)?.key_env,
      });
    } catch (e) {
      setTest({ ok: false, error: e instanceof Error ? e.message : 'Test failed' });
    } finally {
      setTesting(false);
    }
  }

  function applyProvider(id: string) {
    const info = providers.find((p) => p.id === id);
    setAiProvider(id);
    setApiKey('');
    if (!info) return;
    const needsUrl = ['custom', 'azure-openai', 'cloudflare'].includes(id);
    setBaseUrl(needsUrl ? '' : info.base_url || '');
    setChatModel(info.default_models?.[0] ?? '');
  }

  return (
    <div className="min-h-screen">
      <Header user={user} />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-apple-text">Settings</h1>
            <p className="mt-1 text-sm text-apple-muted">
              AI provider, theme, currency, archive path, and runtime configuration.
            </p>
          </div>
        </div>

        {error && <ErrorBox message={error} onRetry={load} />}

        {loading && <p className="py-12 text-center text-sm text-apple-muted">Loading…</p>}

        {data && (
          <div className="space-y-6">
            {/* AI provider card */}
            <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
              <h2 className="text-sm font-bold uppercase tracking-wider text-apple-text">AI provider</h2>
              <p className="mt-1 text-xs text-apple-muted">
                Drives the assistant on the project page and corpus retrieval. Local Ollama is the default;
                cloud providers work via OpenAI-compatible or Anthropic-compatible APIs.
              </p>

              <div className="mt-4 flex flex-wrap gap-2">
                {QUICK_PICKS.map((id) => {
                  const info = providers.find((p) => p.id === id);
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => applyProvider(id)}
                      className={
                        'rounded-full border px-3 py-1.5 text-xs font-semibold transition ' +
                        (aiProvider === id
                          ? 'border-apple-primary bg-apple-primary/10 text-apple-primary'
                          : 'border-apple-border text-apple-text hover:bg-apple-surface/50')
                      }
                    >
                      {info?.label ?? id}
                    </button>
                  );
                })}
              </div>

              <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
                <Field label="AI Provider (all market APIs)">
                  <select
                    value={aiProvider}
                    onChange={(e) => applyProvider(e.target.value)}
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm bg-white text-apple-text dark:bg-[#1f1f22]"
                  >
                    <optgroup label="Local / self-hosted">
                      {providers.filter((p) => p.local).map((p) => (
                        <option key={p.id} value={p.id}>{p.label}{p.key_present ? ' \u2713' : ''}</option>
                      ))}
                    </optgroup>
                    <optgroup label="Cloud APIs">
                      {providers.filter((p) => !p.local).map((p) => (
                        <option key={p.id} value={p.id}>{p.label}{p.key_present ? ' \u2713' : ''}</option>
                      ))}
                    </optgroup>
                  </select>
                  {(() => {
                    const info = providers.find((p) => p.id === aiProvider);
                    if (!info) return null;
                    return (
                      <p className="mt-1 text-[10px] text-apple-muted">
                        {info.kind} API
                        {info.key_env ? ' \u00b7 key from ' + info.key_env : ''}
                        {info.notes ? ' \u00b7 ' + info.notes : ''}
                        {info.docs && (
                          <>
                            {' '}\u00b7{' '}
                            <a href={info.docs} target="_blank" rel="noopener noreferrer" className="underline text-primary">
                              docs
                            </a>
                          </>
                        )}
                      </p>
                    );
                  })()}
                </Field>
                <Field label="Base URL">
                  <input
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="http://localhost:11434"
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                  />
                </Field>
                <Field label={'API key' + (data.ai_key_env ? ' (' + data.ai_key_env + ')' : '')}>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={data.ai_api_key_present ? '•••••• (set; leave empty to keep)' : 'paste key…'}
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                  />
                  <p className="mt-1 text-[10px] text-apple-muted">
                    Stored per provider in settings.json; leave empty to keep the current key.
                  </p>
                </Field>
                <Field label="Chat model">
                  {aiProvider === 'openrouter' ? (
                    <>
                      <select
                        value={OPENROUTER_FREE_MODELS.some((m) => m.id === chatModel) ? chatModel : '__custom__'}
                        onChange={(e) => {
                          if (e.target.value !== '__custom__') setChatModel(e.target.value);
                        }}
                        className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm bg-white text-apple-text dark:bg-[#1f1f22]"
                      >
                        {OPENROUTER_FREE_MODELS.map((m) => (
                          <option key={m.id} value={m.id}>{m.label} (free)</option>
                        ))}
                        <option value="__custom__">Custom model…</option>
                      </select>
                      {!OPENROUTER_FREE_MODELS.some((m) => m.id === chatModel) && (
                        <input
                          value={chatModel}
                          onChange={(e) => setChatModel(e.target.value)}
                          placeholder="e.g. anthropic/claude-3.5-sonnet"
                          className="mt-1.5 w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                        />
                      )}
                    </>
                  ) : (
                    <>
                      <input
                        value={chatModel}
                        onChange={(e) => setChatModel(e.target.value)}
                        list="suggested-models"
                        placeholder="model name"
                        className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                      />
                      <datalist id="suggested-models">
                        {(providers.find((p) => p.id === aiProvider)?.default_models ?? []).map((m) => (
                          <option key={m} value={m} />
                        ))}
                      </datalist>
                    </>
                  )}
                </Field>
                <Field label="Embed model (optional)">
                  <input
                    value={embedModel}
                    onChange={(e) => setEmbedModel(e.target.value)}
                    placeholder="nomic-embed-text"
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                  />
                </Field>
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={save}
                  disabled={saving}
                  className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save changes'}
                </button>
                <button
                  type="button"
                  onClick={testConnection}
                  disabled={testing}
                  className="rounded-md border border-apple-border px-4 py-2 text-sm font-medium text-apple-text hover:bg-apple-surface/50 disabled:opacity-50"
                >
                  {testing ? 'Testing…' : 'Test connection'}
                </button>
                <button
                  type="button"
                  onClick={clearOverrides}
                  disabled={saving}
                  className="rounded-md border border-red-200 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
                >
                  Reset to .env
                </button>
                {savedAt && (
                  <span className="text-xs text-emerald-600">Saved {new Date(savedAt).toLocaleTimeString()}.</span>
                )}
              </div>

              {test && (
                <div className={`mt-4 rounded-md border p-3 text-xs ${
                  test.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-red-200 bg-red-50 text-red-900'
                }`}>
                  {test.ok ? (
                    <>
                      <div className="font-bold">Connected to {test.base_url} in {test.latency_ms}ms</div>
                      {test.model && (
                        <div className="mt-1">Model: {test.model}</div>
                      )}
                      {test.reply && (
                        <div className="mt-1">Reply: &ldquo;{test.reply}&rdquo;</div>
                      )}
                      {test.models && test.models.length > 0 && (
                        <div className="mt-1">Models: {test.models.slice(0, 6).join(', ')}{test.models.length > 6 ? '…' : ''}</div>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="font-bold">Failed: {test.error}</div>
                      {test.hint && <div className="mt-1 italic">{test.hint}</div>}
                    </>
                  )}
                </div>
              )}

              <details className="mt-4 text-xs text-apple-muted">
                <summary className="cursor-pointer font-semibold text-apple-muted">
                  Environment values (from backend/.env)
                </summary>
                <div className="mt-2 space-y-1 font-mono">
                  <div>AI_BASE_URL = {data.env.AI_BASE_URL}</div>
                  <div>AI_CHAT_MODEL = {data.env.AI_CHAT_MODEL}</div>
                  <div>AI_EMBED_MODEL = {data.env.AI_EMBED_MODEL}</div>
                </div>
                <p className="mt-2 italic">
                  The fields above are the live values. The form values override them at runtime;
                  clicking <em>Reset to .env</em> reverts the overrides.
                </p>
              </details>
            </section>

            {/* Currency & rates card */}
            <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
              <h2 className="text-sm font-bold uppercase tracking-wider text-apple-text">Currency & rates</h2>
              <p className="mt-1 text-xs text-apple-muted">
                Budget and pricing configuration for project financials.
              </p>
              <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                <Field label="VAT rate">
                  <input
                    type="number"
                    step="0.01"
                    value={vatRate}
                    onChange={(e) => setVatRate(parseFloat(e.target.value) || 0.15)}
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                    placeholder="0.15"
                  />
                </Field>
                <Field label="USD to SAR rate">
                  <input
                    type="number"
                    step="0.01"
                    value={usdSarRate}
                    onChange={(e) => setUsdSarRate(parseFloat(e.target.value) || 3.75)}
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                    placeholder="3.75"
                  />
                </Field>
                <Field label="Default currency">
                  <input
                    type="text"
                    value={defaultCurrency}
                    onChange={(e) => setDefaultCurrency(e.target.value.toUpperCase().replace(/[^A-Z]/g, '') || 'SAR')}
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                    placeholder="SAR"
                  />
                </Field>
              </div>
            </section>

            {/* Theme card */}
            <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
              <h2 className="text-sm font-bold uppercase tracking-wider text-apple-text">Theme</h2>
              <p className="mt-1 text-xs text-apple-muted">
                KAUST brand palette. The choice is stored in your browser; the backend remembers
                the default for new visitors.
              </p>
              <div className="mt-4 flex gap-2">
                {(['kaust', 'kaust-dark'] as const).map((t) => {
                  const live = t === 'kaust' ? 'light' : 'dark';
                  return (
                    <label key={t} className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm ${
                      liveTheme === live ? 'border-primary bg-primary/10 text-primary' : 'border-apple-border hover:bg-apple-surface/50 text-apple-text'
                    }`}>
                      <input
                        type="radio"
                        name="theme"
                        value={t}
                        checked={liveTheme === live}
                        onChange={() => {
                          setTheme(t);
                          setLiveTheme(live as 'light' | 'dark');
                        }}
                      />
                      {t === 'kaust' ? '☀️ Light (KAUST)' : '🌙 Dark (KAUST)'}
                    </label>
                  );
                })}
              </div>
            </section>

            {/* Archive path card */}
            <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
              <h2 className="text-sm font-bold uppercase tracking-wider text-apple-text">Archive path</h2>
              <p className="mt-1 text-xs text-apple-muted">
                Root directory for engineering data archive ingestion.
              </p>
              <div className="mt-4 flex items-center gap-3">
                <input
                  type="text"
                  value={archivePath}
                  onChange={(e) => setArchivePath(e.target.value)}
                  placeholder="e.g. E:\ENGINEERING_DATA\01_RAW_ARCHIVE"
                  className="flex-1 rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                />
                <button
                  type="button"
                  onClick={() => {
                    const suggestions = ['E:\\\\ENGINEERING_DATA\\\\01_RAW_ARCHIVE', 'E:\\\\archives', 'D:\\\\Archive'];
                    const existing = archivePath || '';
                    const prompt = existing
                      ? 'Enter archive path or select a suggestion'
                      : 'Enter archive path';
                    const choice = window.prompt(prompt, archivePath || '');
                    if (choice) {
                      setArchivePath(choice);
                    }
                  }}
                  className="rounded-md border border-apple-border px-3 py-2 text-sm font-medium text-apple-text hover:bg-apple-surface/50"
                >
                  Browse / Set
                </button>
              </div>
            </section>

            {/* Tracker files card */}
            <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
              <h2 className="text-sm font-bold uppercase tracking-wider text-apple-text">Tracker files</h2>
              <p className="mt-1 text-xs text-apple-muted">
                The Planner saves dated versions (e.g. <code>_21092026</code>) of each tracker. The system
                always resolves the newest dated file — never a hardcoded date.
              </p>
              <div className="mt-4 space-y-3">
                <Field label="Trackers directory">
                  <input
                    type="text"
                    value={trackersDir}
                    onChange={(e) => setTrackersDir(e.target.value)}
                    placeholder="E:\\ENGINEERING_DATA\\trackers"
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                  />
                </Field>
                <Field label="PR request drop folder (PDFs)">
                  <input
                    type="text"
                    value={prRequestDir}
                    onChange={(e) => setPrRequestDir(e.target.value)}
                    placeholder="E:\\ENGINEERING_DATA\\trackers\\PR Request Copy"
                    className="w-full rounded-md border border-apple-border px-3 py-1.5 text-sm font-mono"
                  />
                </Field>

                {/* Live resolution status */}
                {trackerFiles && (
                  <div className="mt-2 rounded-md border border-apple-border bg-apple-surface/50 p-3 text-xs">
                    <p className="font-semibold text-apple-text">Currently resolved</p>
                    <div className="mt-2 space-y-1 font-mono text-apple-muted">
                      <div>
                        IHP Planner:{' '}
                        <span className={trackerFiles.planner_latest ? 'text-emerald-600' : 'text-red-600'}>
                          {trackerFiles.planner_latest ?? 'not found'}
                        </span>
                      </div>
                      <div>
                        O&M Tracking:{' '}
                        <span className={trackerFiles.om_latest ? 'text-emerald-600' : 'text-red-600'}>
                          {trackerFiles.om_latest ?? 'not found'}
                        </span>
                      </div>
                      <div>
                        PR requests:{' '}
                        <span className={trackerFiles.pr_request_dir_exists ? 'text-emerald-600' : 'text-red-600'}>
                          {trackerFiles.pr_request_count} PDF{trackerFiles.pr_request_count === 1 ? '' : 's'}
                          {trackerFiles.pr_request_dir_exists ? '' : ' (folder not found)'}
                        </span>
                      </div>
                    </div>
                    <p className="mt-2 italic text-apple-muted">{trackerFiles.note}.</p>
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={save}
                    disabled={saving}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
                  >
                    {saving ? 'Saving…' : 'Save tracker paths'}
                  </button>
                  {savedAt && (
                    <span className="text-xs text-emerald-600">Saved {new Date(savedAt).toLocaleTimeString()}.</span>
                  )}
                </div>
              </div>
            </section>

            {/* Read-only env section */}
            <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
              <h2 className="text-sm font-bold uppercase tracking-wider text-apple-text">Environment variables</h2>
              <p className="mt-1 text-xs text-apple-muted">
                Backend environment at process start. The full set lives in <code>backend/.env</code>.
              </p>
              <pre className="mt-3 overflow-x-auto rounded-md bg-apple-surface/50 p-3 text-[11px] font-mono text-apple-text">
{`DATABASE_URL = ${data.env.AI_BASE_URL ? '(set)' : '(default)'}
SECRET_KEY   = (hidden)
ADMIN_USERNAME = admin
ADMIN_PASSWORD = (hidden)
${Object.entries(data.overrides).map(([k, v]) => `OVERRIDE  ${k} = ${typeof v === 'string' ? v : JSON.stringify(v)}`).join('\n')}`}
              </pre>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[10px] font-semibold uppercase tracking-wider text-apple-muted">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

