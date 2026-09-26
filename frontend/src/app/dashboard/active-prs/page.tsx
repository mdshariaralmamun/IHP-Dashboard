'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { getOmActivePrs } from '@/lib/api';
import type { OmActiveResponse, OmActivePr } from '@/lib/api';
import { useUser } from '@/lib/useUser';

/** Category -> label + colours. Equipment work is NOT part of IHP counts. */
const CATEGORY_META: Record<string, { label: string; hint: string; cls: string }> = {
  CONSTRUCTION: {
    label: 'Construction Project',
    hint: 'Counted as IHP active work',
    cls: 'bg-emerald-100 text-emerald-800 ring-emerald-300',
  },
  EQUIPMENT_INSTALLATION: {
    label: 'Equipment Installation',
    hint: 'Equipment installation — excluded from IHP counts (no modification / utility tie-in)',
    cls: 'bg-amber-100 text-amber-800 ring-amber-300',
  },
  EQUIPMENT_ASSESSMENT: {
    label: 'Assessment of Lab Equipment',
    hint: 'Equipment installation — excluded from IHP counts',
    cls: 'bg-orange-100 text-orange-800 ring-orange-300',
  },
  ASEPC_PROPOSAL: {
    label: 'ASEPC Proposal Request',
    hint: 'Assessment / proposal stage (EAR phase)',
    cls: 'bg-purple-100 text-purple-800 ring-purple-300',
  },
  ICR: { label: 'ICR', hint: 'Equipment installation — ICR closeout', cls: 'bg-gray-100 text-gray-700 ring-gray-300' },
  UNKNOWN: { label: 'Unclassified', hint: 'No classification in the tracker', cls: 'bg-red-100 text-red-700 ring-red-300' },
};

export default function ActivePrsPage() {
  return (
    <AuthGuard>
      <ActivePrs />
    </AuthGuard>
  );
}

function ActivePrs() {
  const { user } = useUser();
  const [data, setData] = useState<OmActiveResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>('');

  useEffect(() => {
    getOmActivePrs()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'));
  }, []);

  const groups = useMemo(() => {
    const g: Record<string, OmActivePr[]> = {};
    (data?.items ?? []).forEach((r) => {
      g[r.category] = g[r.category] ?? [];
      g[r.category].push(r);
    });
    return g;
  }, [data]);

  const s = data?.summary ?? {};
  const order = ['CONSTRUCTION', 'EQUIPMENT_INSTALLATION', 'EQUIPMENT_ASSESSMENT', 'ASEPC_PROPOSAL', 'ICR', 'UNKNOWN'];

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-6xl space-y-5 px-4 py-8">
        <Link href="/dashboard" className="text-xs text-apple-muted hover:text-apple-text">
          ← Dashboard
        </Link>
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-apple-text">
            Active PRs — O&amp;M tracker
          </h1>
          <p className="mt-1 text-sm text-apple-muted">
            Classified by the tracker&apos;s <strong>IHP Classification of Request</strong> column.
            Only Construction Projects count as IHP active work.
          </p>
          {data?.source && (
            <p className="mt-1 font-mono text-[11px] text-apple-muted">
              source: {data.source}
            </p>
          )}
        </div>

        {error && <ErrorBox message={error} />}
        {!data && !error && <p className="text-sm text-apple-muted">Loading…</p>}

        {data && (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
                <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
                  IHP active (counted)
                </div>
                <div className="mt-1 text-3xl font-bold tabular-nums text-emerald-800">
                  {s.ihp_active_count ?? 0}
                </div>
                <p className="mt-1 text-[11px] text-emerald-700">Construction Projects</p>
              </div>
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
                <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                  Equipment installation (excluded)
                </div>
                <div className="mt-1 text-3xl font-bold tabular-nums text-amber-800">
                  {s.equipment_branch_count ?? 0}
                </div>
                <p className="mt-1 text-[11px] text-amber-700">
                  Installation + lab-equipment assessment — no modification, no utility tie-in
                </p>
              </div>
              <div className="rounded-2xl border border-purple-200 bg-purple-50 p-5">
                <div className="text-xs font-semibold uppercase tracking-wide text-purple-700">
                  ASEPC proposals
                </div>
                <div className="mt-1 text-3xl font-bold tabular-nums text-purple-800">
                  {s.assessment_count ?? 0}
                </div>
                <p className="mt-1 text-[11px] text-purple-700">Assessment / proposal stage</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 text-xs">
              <button
                type="button"
                onClick={() => setFilter('')}
                className={`rounded-full px-3 py-1 font-semibold ring-1 ring-inset ${
                  filter === '' ? 'bg-primary text-white ring-primary' : 'bg-white text-apple-muted ring-apple-border dark:bg-white/[0.06]'
                }`}
              >
                All {s.total ?? 0}
              </button>
              {order.filter((c) => groups[c]).map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setFilter(filter === c ? '' : c)}
                  className={`rounded-full px-3 py-1 font-semibold ring-1 ring-inset ${
                    filter === c ? 'ring-2 ring-primary' : ''
                  } ${CATEGORY_META[c]?.cls ?? ''}`}
                >
                  {CATEGORY_META[c]?.label ?? c} · {groups[c].length}
                </button>
              ))}
            </div>

            {order.filter((c) => groups[c] && (!filter || filter === c)).map((c) => (
              <section key={c} className="rounded-2xl border border-apple-border bg-white p-5 dark:bg-white/[0.04]">
                <div className="mb-1 flex flex-wrap items-baseline gap-2">
                  <h2 className="text-sm font-bold text-apple-text">
                    {CATEGORY_META[c]?.label ?? c}
                  </h2>
                  <span className="rounded-full bg-apple-surface px-2 py-0.5 text-xs font-semibold text-apple-muted">
                    {groups[c].length}
                  </span>
                </div>
                <p className="mb-3 text-[11px] italic text-apple-muted">
                  {CATEGORY_META[c]?.hint}
                </p>
                <ul className="space-y-2">
                  {groups[c].map((r) => (
                    <li key={r.pr_key + r.source_tab} className="rounded-xl border border-apple-border p-3">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <div className="min-w-0">
                          <span className="font-mono text-xs font-semibold text-apple-muted">
                            {r.pr_key}
                          </span>
                          <span className="ml-2 text-sm font-medium text-apple-text">
                            {r.title ?? '—'}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-2 text-[11px] text-apple-muted">
                          {r.status && (
                            <span className="rounded-full bg-apple-surface px-2 py-0.5">{r.status}</span>
                          )}
                          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-blue-700">
                            {r.source_tab}
                          </span>
                          {r.request_date && <span>{r.request_date.slice(0, 10)}</span>}
                          {(r as { tag?: string }).tag && (
                            <span
                              className={
                                (r as { tag?: string }).tag === 'Upcoming EAR'
                                  ? 'rounded-full bg-purple-100 px-2 py-0.5 font-semibold text-purple-800'
                                  : (r as { tag?: string }).tag === 'Equipment installation'
                                    ? 'rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-800'
                                    : 'rounded-full bg-apple-surface px-2 py-0.5 text-apple-muted'
                              }
                            >
                              {(r as { tag?: string }).tag}
                            </span>
                          )}
                        </div>
                      </div>
                      {r.remarks && (
                        <p className="mt-1.5 text-xs text-apple-muted">
                          <span className="font-semibold">IHP Remarks:</span> {r.remarks}
                        </p>
                      )}
                      {r.location && (
                        <p className="mt-0.5 text-[11px] text-apple-muted">📍 {r.location}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </>
        )}
      </main>
    </div>
  );
}
