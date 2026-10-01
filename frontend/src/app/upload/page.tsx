'use client';

import { useCallback, useEffect, useState } from 'react';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { getToken } from '@/lib/api';
import type { TrackerSources } from '@/lib/api';
import { useUser } from '@/lib/useUser';

interface MismatchField {
  field: string;
  planner: string | null;
  om: string | null;
}
interface Mismatch {
  pr_key: string;
  in_planner: boolean;
  in_om: boolean;
  in_db: boolean;
  db_stage: string | null;
  db_location: string | null;
  db_pi_name: string | null;
  planner_title: string | null;
  om_title: string | null;
  db_title: string | null;
  mismatches: MismatchField[];
}
interface MismatchSummary {
  total: number;
  in_planner: number;
  in_om: number;
  in_db: number;
  with_conflicts: number;
  missing_in_om: number;
  missing_in_planner: number;
  conflicts_by_field: Record<string, number>;
}
interface MismatchResponse {
  summary: MismatchSummary;
  computed_at: number | null;
  planner_path: string;
  om_path: string;
  items: Mismatch[];
  total: number;
}

async function uploadTracker(
  url: string,
  file: File,
  token: string,
  fields: Record<string, string> = {},
) {
  const fd = new FormData();
  fd.append('file', file);
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  const r = await fetch(url, {
    method: 'POST',
    body: fd,
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`Upload failed (${r.status}): ${text.slice(0, 200)}`);
  }
  return r.json();
}

async function fetchMismatches(token: string, onlyConflicts: boolean): Promise<MismatchResponse> {
  const r = await fetch(
    `/api/admin/import/mismatches?limit=500&only_conflicts=${onlyConflicts}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!r.ok) throw new Error(`Failed: ${r.status}`);
  return r.json();
}

/**
 * What actually happened to the file that was just uploaded.
 *
 * `published` is the backend saying the file became the live version, and
 * `active_source` says whether the app is now reading THIS upload or a
 * newer file that was already there — the difference between "it worked"
 * and "it worked but something newer still outranks it".
 */
function publishNote(res: any): string {
  if (res?.published === false) return 'staged only (dry run) — nothing published';
  if (res?.active_source === 'upload') return `published — now live: ${res.active_file}`;
  if (res?.active_file) return `published, but a newer file still wins: ${res.active_file}`;
  return 'published';
}

async function fetchSources(token: string): Promise<TrackerSources> {
  const r = await fetch('/api/admin/import/sources', {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) throw new Error(`Failed: ${r.status}`);
  return r.json();
}

async function resolveMismatch(prKey: string, field: string, source: 'planner' | 'om', token: string) {
  const fd = new FormData();
  fd.append('pr_key', prKey);
  fd.append('field', field);
  fd.append('source', source);
  const r = await fetch('/api/admin/import/mismatches/resolve', {
    method: 'POST', body: fd,
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`Resolve failed (${r.status}): ${text.slice(0, 200)}`);
  }
  return r.json();
}

export default function UploadPage() {
  return (
    <AuthGuard>
      <UploadView />
    </AuthGuard>
  );
}

function UploadView() {
  const { user } = useUser();
  const [token, setToken] = useState<string | null>(null);
  const [plannerFile, setPlannerFile] = useState<File | null>(null);
  const [omFile, setOmFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [mismatches, setMismatches] = useState<MismatchResponse | null>(null);
  const [sources, setSources] = useState<TrackerSources | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [onlyConflicts, setOnlyConflicts] = useState(true);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    // MUST go through the shared helper: the JWT is stored under
    // 'ihp_access_token'. Reading a hard-coded key here ('ihp_token') made
    // every request on this page a silent no-op — the click did nothing at
    // all, with no error, because both refresh() and doUpload() bail out
    // when the token is null.
    setToken(getToken());
  }, []);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    // Settled, not sequential: a failure in one panel must never hide the
    // other. The live-version panel is what tells the user whether their
    // upload actually took over, so it always gets its own attempt.
    const [mismatchResult, sourceResult] = await Promise.allSettled([
      fetchMismatches(token, onlyConflicts),
      fetchSources(token),
    ]);
    if (mismatchResult.status === 'fulfilled') {
      setMismatches(mismatchResult.value);
    } else {
      const reason = mismatchResult.reason;
      setError(reason instanceof Error ? reason.message : 'Failed to load mismatches');
    }
    if (sourceResult.status === 'fulfilled') {
      setSources(sourceResult.value);
    }
    setLoading(false);
  }, [token, onlyConflicts]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function doUpload() {
    if (!token) {
      // Never fail silently: that is what made "Upload & compare" look
      // broken. Re-read the token in case the page mounted before login.
      const fresh = getToken();
      if (!fresh) {
        setError('Your session has expired. Reload the page and sign in again, then retry.');
        return;
      }
      setToken(fresh);
      return;
    }
    if (!plannerFile && !omFile) {
      setError('Choose at least one file to upload.');
      return;
    }
    setUploading(true);
    setError(null);
    setUploadStatus(null);
    try {
      if (plannerFile) {
        const res = await uploadTracker('/api/admin/import/planner', plannerFile, token, { dry_run: 'false' });
        setUploadStatus(`Planner: ${res.rows_processed} rows processed — ${publishNote(res)}`);
      }
      if (omFile) {
        const res = await uploadTracker('/api/admin/import/om', omFile, token, { sheet: ' In House Projects' });
        setUploadStatus(
          (s) => (s ? s + ' · ' : '') + `O&M: ${res.rows_parsed} rows parsed — ${publishNote(res)}`,
        );
      }
      setPlannerFile(null);
      setOmFile(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  async function handleResolve(prKey: string, field: string, source: 'planner' | 'om') {
    if (!token) return;
    setError(null);
    try {
      await resolveMismatch(prKey, field, source, token);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Resolve failed');
    }
  }

  const visible = mismatches?.items.filter((m) => {
    if (!filter) return true;
    const f = filter.toLowerCase();
    return m.pr_key.toLowerCase().includes(f) ||
      (m.planner_title || '').toLowerCase().includes(f) ||
      (m.om_title || '').toLowerCase().includes(f);
  }) ?? [];

  return (
    <div className="min-h-screen">
      <Header user={user} />
      <main className="mx-auto max-w-7xl px-4 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-apple-text">
              Tracker upload &amp; mismatch review
            </h1>
            <p className="mt-1 text-sm text-apple-muted">
              Import the live Microsoft Project planner and the O&amp;M tracking sheet, then resolve data conflicts PR by PR.
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="rounded-md border border-apple-border px-3 py-1.5 text-sm font-medium text-apple-text hover:bg-apple-surface disabled:opacity-50"
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        {/* Which version of each tracker the app is reading right now */}
        <ActiveVersions sources={sources} />

        {/* Upload cards */}
        <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
          <UploadCard
            title="MS Project planner (live source)"
            description="The Microsoft Project export. Drives the project register and dashboard. Uploading creates / updates IHP projects."
            file={plannerFile}
            onFile={setPlannerFile}
            color="blue"
          />
          <UploadCard
            title="O&M tracking sheet"
            description="The historic record: location, division and requestor. Publishing it makes it the live O&M sheet the summary, SOW and MOM read. No project rows are written."
            file={omFile}
            onFile={setOmFile}
            color="emerald"
          />
        </div>

        <div className="mb-6 flex items-center gap-3">
          <button
            type="button"
            onClick={doUpload}
            disabled={uploading || (!plannerFile && !omFile)}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {uploading ? 'Uploading…' : 'Upload & compare'}
          </button>
        </div>

        {uploadStatus && (
          <div className="mb-6 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            {uploadStatus}
          </div>
        )}

        {error && <ErrorBox message={error} onRetry={refresh} />}

        {/* Mismatch summary */}
        {mismatches && (
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-6">
            <SummaryTile label="Total PRs seen" value={mismatches.summary.total} />
            <SummaryTile label="In planner" value={mismatches.summary.in_planner} accent="blue" />
            <SummaryTile label="In O&amp;M" value={mismatches.summary.in_om} accent="emerald" />
            <SummaryTile label="In DB" value={mismatches.summary.in_db} accent="slate" />
            <SummaryTile label="With conflicts" value={mismatches.summary.with_conflicts} accent="amber" />
            <SummaryTile
              label="Missing in O&amp;M"
              value={mismatches.summary.missing_in_om}
              accent={mismatches.summary.missing_in_om > 0 ? 'red' : 'slate'}
            />
          </div>
        )}

        {/* Conflicts by field */}
        {mismatches && Object.keys(mismatches.summary.conflicts_by_field || {}).length > 0 && (
          <div className="mb-6 rounded-lg border border-apple-border bg-apple-surface p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-apple-text">Conflicts by field</h2>
            <div className="mt-3 flex flex-wrap gap-3 text-xs">
              {Object.entries(mismatches.summary.conflicts_by_field)
                .sort(([, a], [, b]) => b - a)
                .map(([field, count]) => (
                  <div key={field} className="rounded-md border border-apple-border bg-apple-surface/50 px-3 py-2">
                    <div className="font-mono text-sm font-bold text-apple-text">{count}</div>
                    <div className="text-[10px] uppercase tracking-wider text-apple-muted">{field}</div>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Filter + table */}
        {mismatches && (
          <div className="rounded-lg border border-apple-border bg-apple-surface shadow-sm">
            <div className="flex items-center justify-between gap-3 border-b border-apple-border p-3">
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter PR / title…"
                className="w-64 rounded-md border border-apple-border px-3 py-1.5 text-sm"
              />
              <label className="flex items-center gap-2 text-xs text-apple-muted">
                <input
                  type="checkbox"
                  checked={onlyConflicts}
                  onChange={(e) => setOnlyConflicts(e.target.checked)}
                />
                Only show rows with conflicts
              </label>
              <span className="ml-auto text-xs text-apple-muted">
                {visible.length} of {mismatches.items.length} items
              </span>
            </div>
            {visible.length === 0 ? (
              <p className="p-12 text-center text-sm text-apple-muted">
                No mismatches to show. Upload both trackers above to populate this view.
              </p>
            ) : (
              <div className="max-h-[60vh] overflow-y-auto">
                <table className="min-w-full divide-y divide-apple-border text-sm">
                  <thead className="sticky top-0 bg-apple-surface/50 text-xs uppercase tracking-wider text-apple-muted">
                    <tr>
                      <th className="px-3 py-2 text-left">PR</th>
                      <th className="px-3 py-2 text-left">Title (planner / O&amp;M)</th>
                      <th className="px-3 py-2 text-left">Stage</th>
                      <th className="px-3 py-2 text-left">Conflicts</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-apple-border">
                    {visible.map((m) => (
                      <tr key={m.pr_key} className="align-top hover:bg-apple-surface/50">
                        <td className="whitespace-nowrap px-3 py-2 font-mono text-xs font-semibold text-apple-text">
                          {m.pr_key}
                        </td>
                        <td className="px-3 py-2">
                          <div className="text-apple-text">{m.planner_title || m.om_title || m.db_title || '—'}</div>
                          {(m.planner_title && m.om_title && m.planner_title !== m.om_title) && (
                            <div className="mt-1 text-[11px] text-apple-muted">
                              O&amp;M title: <span className="italic">{m.om_title}</span>
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          <div className="text-apple-text">{m.db_stage || '—'}</div>
                          <div className="text-[10px] text-apple-muted">
                            in_planner={String(m.in_planner)} in_om={String(m.in_om)} in_db={String(m.in_db)}
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          {m.mismatches.length === 0 ? (
                            <span className="text-xs text-apple-muted">No conflicts</span>
                          ) : (
                            <div className="space-y-1.5">
                              {m.mismatches.map((fm) => (
                                <div key={fm.field} className="rounded border border-amber-200 bg-amber-50 p-2 text-xs">
                                  <div className="flex items-center justify-between">
                                    <span className="font-mono font-semibold text-amber-900">{fm.field}</span>
                                    <div className="flex gap-1">
                                      <ResolveButton onClick={() => handleResolve(m.pr_key, fm.field, 'planner')} colour="blue">
                                        Use planner
                                      </ResolveButton>
                                      <ResolveButton onClick={() => handleResolve(m.pr_key, fm.field, 'om')} colour="emerald">
                                        Use O&amp;M
                                      </ResolveButton>
                                    </div>
                                  </div>
                                  <div className="mt-1 grid grid-cols-2 gap-2 text-[11px]">
                                    <div className="rounded bg-blue-50 px-2 py-1">
                                      <div className="text-[9px] font-bold uppercase text-blue-700">Planner</div>
                                      <div className="truncate text-apple-text" title={String(fm.planner)}>{String(fm.planner)}</div>
                                    </div>
                                    <div className="rounded bg-emerald-50 px-2 py-1">
                                      <div className="text-[9px] font-bold uppercase text-emerald-700">O&amp;M</div>
                                      <div className="truncate text-apple-text" title={String(fm.om)}>{String(fm.om)}</div>
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function UploadCard({ title, description, file, onFile, color }: {
  title: string; description: string;
  file: File | null; onFile: (f: File | null) => void;
  color: 'blue' | 'emerald';
}) {
  const border = color === 'blue' ? 'border-blue-200' : 'border-emerald-200';
  const ring = color === 'blue' ? 'focus:ring-blue-500' : 'focus:ring-emerald-500';
  return (
    <label className={`block cursor-pointer rounded-lg border-2 border-dashed bg-apple-surface p-4 text-sm hover:bg-apple-surface/50 focus:outline-none focus:ring-2 ${border} ${ring}`}>
      <div className="flex items-center justify-between">
        <div className="font-semibold text-apple-text">{title}</div>
        {file && <span className="rounded bg-primary px-2 py-0.5 text-[10px] font-bold text-white">Selected</span>}
      </div>
      <p className="mt-1 text-xs text-apple-muted">{description}</p>
      <div className="mt-3 text-xs text-apple-text">
        {file ? (
          <div className="flex items-center justify-between">
            <span className="truncate font-medium">{file.name}</span>
            <button
              type="button"
              onClick={(e) => { e.preventDefault(); onFile(null); }}
              className="text-apple-muted hover:text-apple-text"
            >
              ✕
            </button>
          </div>
        ) : (
          <span className="text-apple-muted">Click to choose an .xlsx file…</span>
        )}
      </div>
      <input
        type="file"
        accept=".xlsx"
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0] || null)}
      />
    </label>
  );
}

function SummaryTile({ label, value, accent }: {
  label: string; value: number; accent?: 'blue' | 'emerald' | 'amber' | 'red' | 'slate';
}) {
  const map: Record<string, string> = {
    blue: 'text-blue-700', emerald: 'text-emerald-700', amber: 'text-amber-700',
    red: 'text-red-700', slate: 'text-apple-text',
  };
  return (
    <div className="rounded-lg border border-apple-border bg-apple-surface p-3 shadow-sm">
      <div className={`text-2xl font-bold ${accent ? map[accent] : 'text-apple-text'}`}>{value}</div>
      <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-apple-muted">{label}</div>
    </div>
  );
}

function ResolveButton({ children, onClick, colour }: {
  children: React.ReactNode; onClick: () => void;
  colour: 'blue' | 'emerald';
}) {
  const cls = colour === 'blue'
    ? 'bg-blue-600 hover:bg-blue-700 text-white'
    : 'bg-emerald-600 hover:bg-emerald-700 text-white';
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2 py-0.5 text-[10px] font-semibold ${cls}`}
    >
      {children}
    </button>
  );
}

function ActiveVersions({ sources }: { sources: TrackerSources | null }) {
  const rows = [
    {
      label: 'Planner tracker',
      file: sources?.planner_latest,
      date: sources?.planner_date,
      source: sources?.planner_source,
    },
    {
      label: 'O&M tracker',
      file: sources?.om_latest,
      date: sources?.om_date,
      source: sources?.om_source,
    },
  ];
  return (
    <div className="mb-6 rounded-lg border border-apple-border bg-apple-surface p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-apple-text">Live tracker versions</h2>
        <span className="text-[11px] text-apple-muted">
          the newest _DDMMYYYY version wins, uploaded or dropped in
        </span>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        {rows.map((r) => (
          <div key={r.label} className="rounded-md border border-apple-border bg-apple-surface/50 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-apple-muted">{r.label}</div>
            <div className="mt-1 break-all font-mono text-xs text-apple-text">
              {r.file ?? '— not resolved —'}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
              {r.date && (
                <span className="rounded bg-blue-50 px-1.5 py-0.5 font-medium text-blue-700">{r.date}</span>
              )}
              {r.source && (
                <span
                  className={
                    r.source === 'upload'
                      ? 'rounded bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700'
                      : 'rounded border border-apple-border px-1.5 py-0.5 font-medium text-apple-muted'
                  }
                >
                  {r.source === 'upload' ? 'from your upload' : 'from the Planner folder'}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
      {sources?.upload_dir && (
        <p className="mt-3 text-[11px] text-apple-muted">
          Uploads are published to <span className="font-mono">{sources.upload_dir}</span> and persist across
          redeploys; the Planner&apos;s own folder{' '}
          <span className="font-mono">{sources.configured_dir}</span> keeps being searched, so a newer export dropped
          there still wins.
        </p>
      )}
    </div>
  );
}

