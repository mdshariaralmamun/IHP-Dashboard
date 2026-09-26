'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { getConsistency } from '@/lib/api';
import type { ConsistencyIssue, ConsistencyResponse } from '@/lib/api';
import { useUser } from '@/lib/useUser';

/** Plain-English explanation of every check, shown on the page. */
const CODE_META: Record<string, { label: string; what: string }> = {
  STATUS_MISMATCH: {
    label: 'Completion conflict',
    what: 'One source says the work is finished, the other still tracks it as open.',
  },
  TYPE_MISMATCH: {
    label: 'Type conflict',
    what: 'BASELINE / ASEPC disagrees between the Planner and the O&M register.',
  },
  UNCLASSIFIED_PR: {
    label: 'Unclassified PR',
    what: 'An active PR has no "IHP Classification of Request", so it cannot be placed.',
  },
  DUPLICATE_OM_ROW: {
    label: 'Duplicate row',
    what: 'The same PR appears more than once in the O&M register.',
  },
  MISSING_BUCKET: {
    label: 'Missing bucket',
    what: 'A Planner row has no Bucket, so it cannot be assigned to a division.',
  },
  OM_ONLY: {
    label: 'O&M only',
    what: 'Tracked in the O&M register but missing from the Planner file.',
  },
  PLANNER_ONLY: {
    label: 'Planner only',
    what: 'In the Planner but not yet in the O&M register.',
  },
  ACTIVE_ALSO_IN_PLANNER: {
    label: 'Active PR also in Planner',
    what: 'Listed in an O&M active tab and already picked up by the Planner.',
  },
};

const SEVERITY_STYLE: Record<string, { badge: string; dot: string; label: string }> = {
  error: { badge: 'bg-red-100 text-red-800 ring-red-300', dot: 'bg-red-500', label: 'Error' },
  warning: { badge: 'bg-amber-100 text-amber-800 ring-amber-300', dot: 'bg-amber-500', label: 'Warning' },
  info: { badge: 'bg-blue-100 text-blue-800 ring-blue-300', dot: 'bg-blue-400', label: 'Info' },
};

export default function ConsistencyPage() {
  return (
    <AuthGuard>
      <ConsistencyView />
    </AuthGuard>
  );
}

function ConsistencyView() {
  const { user } = useUser();
  const [data, setData] = useState<ConsistencyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sev, setSev] = useState<string>('');
  const [code, setCode] = useState<string>('');

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      setData(await getConsistency(refresh));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run the consistency check');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = useMemo(() => {
    return (data?.issues ?? []).filter(
      (i) => (!sev || i.severity === sev) && (!code || i.code === code),
    );
  }, [data, sev, code]);

  const s = data?.summary ?? {};
  const byCode = s.by_code ?? {};

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-6xl space-y-5 px-4 py-8">
        <Link href="/dashboard" className="text-xs text-apple-muted hover:text-apple-text">
          ← Dashboard
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-apple-text">
              Tracking consistency
            </h1>
            <p className="mt-1 text-sm text-apple-muted">
              The Planner, the O&amp;M register and the O&amp;M active tabs are compared by PR
              number. Anything that disagrees is listed here.
            </p>
            {data?.planner_file && (
              <p className="mt-1 font-mono text-[11px] text-apple-muted">
                {data.planner_file} ↔ {data.om_file}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={loading}
            className="rounded-md border border-apple-border bg-white px-3 py-1.5 text-xs font-semibold text-apple-text hover:bg-apple-surface disabled:opacity-50"
          >
            {loading ? 'Checking…' : 'Re-run check'}
          </button>
        </div>

        {error && <ErrorBox message={error} />}

        {data?.ok && (
          <>
            <div className="grid gap-3 sm:grid-cols-4">
              <div className={`rounded-2xl border p-4 ${(s.errors ?? 0) > 0 ? 'border-red-300 bg-red-50' : 'border-apple-border bg-white'}`}>
                <div className="text-xs font-semibold uppercase tracking-wide text-apple-muted">Errors</div>
                <div className={`mt-1 text-3xl font-bold tabular-nums ${(s.errors ?? 0) > 0 ? 'text-red-700' : 'text-apple-text'}`}>
                  {s.errors ?? 0}
                </div>
                <p className="mt-1 text-[11px] text-apple-muted">Conflicting data — fix these first</p>
              </div>
              <div className={`rounded-2xl border p-4 ${(s.warnings ?? 0) > 0 ? 'border-amber-300 bg-amber-50' : 'border-apple-border bg-white'}`}>
                <div className="text-xs font-semibold uppercase tracking-wide text-apple-muted">Warnings</div>
                <div className="mt-1 text-3xl font-bold tabular-nums text-amber-700">{s.warnings ?? 0}</div>
                <p className="mt-1 text-[11px] text-apple-muted">One source is missing or differs</p>
              </div>
              <div className="rounded-2xl border border-apple-border bg-white p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-apple-muted">Notes</div>
                <div className="mt-1 text-3xl font-bold tabular-nums text-blue-600">{s.infos ?? 0}</div>
                <p className="mt-1 text-[11px] text-apple-muted">Expected gaps (not errors)</p>
              </div>
              <div className="rounded-2xl border border-apple-border bg-white p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-apple-muted">PRs checked</div>
                <div className="mt-1 text-3xl font-bold tabular-nums text-apple-text">
                  {s.total_checked ?? 0}
                </div>
                <p className="mt-1 text-[11px] text-apple-muted">Planner rows compared</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 text-xs">
              <button
                type="button"
                onClick={() => { setSev(''); setCode(''); }}
                className={`rounded-full px-3 py-1 font-semibold ring-1 ring-inset ${!sev && !code ? 'bg-primary text-white ring-primary' : 'bg-white text-apple-muted ring-apple-border'}`}
              >
                All {data.issues.length}
              </button>
              {(['error', 'warning', 'info'] as const).filter((v) => (s[`${v}s` as 'errors' | 'warnings' | 'infos'] ?? 0) > 0).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => { setSev(sev === v ? '' : v); setCode(''); }}
                  className={`rounded-full px-3 py-1 font-semibold ring-1 ring-inset ${SEVERITY_STYLE[v].badge} ${sev === v ? 'ring-2 ring-primary' : ''}`}
                >
                  {SEVERITY_STYLE[v].label} {s[`${v}s` as 'errors' | 'warnings' | 'infos']}
                </button>
              ))}
              {Object.entries(byCode).map(([c, n]) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => { setCode(code === c ? '' : c); setSev(''); }}
                  className={`rounded-full px-3 py-1 font-medium ring-1 ring-inset ${code === c ? 'ring-2 ring-primary' : 'ring-apple-border'} bg-white text-apple-muted`}
                >
                  {CODE_META[c]?.label ?? c} · {n}
                </button>
              ))}
            </div>

            {Object.entries(byCode).length > 0 && (
              <div className="rounded-xl border border-apple-border bg-white p-4">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-apple-muted">
                  What each check means
                </div>
                <ul className="space-y-1 text-[11px] text-apple-muted">
                  {Object.keys(byCode).map((c) => (
                    <li key={c}>
                      <span className="font-semibold text-apple-text">
                        {CODE_META[c]?.label ?? c}
                      </span>{' '}
                      — {CODE_META[c]?.what ?? 'See the message on each row.'}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {loading && !data.issues.length && (
              <p className="text-sm text-apple-muted">Running the check… (first run parses both trackers)</p>
            )}

            <ul className="space-y-2">
              {rows.map((i: ConsistencyIssue, idx) => {
                const st = SEVERITY_STYLE[i.severity] ?? SEVERITY_STYLE.info;
                return (
                  <li key={`${i.code}-${i.pr_key}-${idx}`}
                      className="rounded-xl border border-apple-border bg-white p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${st.badge}`}>
                        {CODE_META[i.code]?.label ?? i.code}
                      </span>
                      {i.pr_key && (
                        <span className="font-mono text-xs font-semibold text-apple-text">{i.pr_key}</span>
                      )}
                      {i.field && (
                        <span className="text-[11px] text-apple-muted">field: {i.field}</span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-apple-text">{i.message}</p>
                    {(i.planner_value || i.om_value) && (
                      <p className="mt-1 text-[11px] text-apple-muted">
                        {i.planner_value !== null && (
                          <span className="mr-3">Planner: <strong>{i.planner_value || '—'}</strong></span>
                        )}
                        {i.om_value !== null && (
                          <span>O&amp;M: <strong>{i.om_value || '—'}</strong></span>
                        )}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>

            {rows.length === 0 && !loading && (
              <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                ✓ No inconsistencies for this filter.
              </p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
