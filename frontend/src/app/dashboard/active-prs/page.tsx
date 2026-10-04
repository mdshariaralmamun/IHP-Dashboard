'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { getOmActivePrs, pullIcrProjects } from '@/lib/api';
import type { OmActiveResponse, OmActivePr, PullIcrResponse } from '@/lib/api';
import { useUser } from '@/lib/useUser';
import { KpiCard } from '@/components/powerbi/PowerBI';

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
  const [pulling, setPulling] = useState(false);
  const [pullResult, setPullResult] = useState<PullIcrResponse | null>(null);
  const [pullError, setPullError] = useState<string | null>(null);

  const load = () =>
    getOmActivePrs()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'));

  useEffect(() => {
    load();
  }, []);

  const onPull = async () => {
    setPulling(true);
    setPullError(null);
    try {
      const result = await pullIcrProjects();
      setPullResult(result);
      if (!result.ok && result.error) setPullError(result.error);
      await load();
    } catch (e) {
      setPullError(e instanceof Error ? e.message : 'Pull failed');
    } finally {
      setPulling(false);
    }
  };

  const groups = useMemo(() => {
    const g: Record<string, OmActivePr[]> = {};
    (data?.items ?? []).forEach((r) => {
      g[r.category] = g[r.category] ?? [];
      g[r.category].push(r);
    });
    return g;
  }, [data]);

  const s = data?.summary ?? {};
  const icrInApp = (data?.items ?? []).filter((i) => i.app_disposition === 'ICR').length;
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

        {/* ICR pull: the equipment tab is the ICR stream. */}
        {(groups.CONSTRUCTION?.length ?? 0) > 0 && (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="max-w-2xl">
                <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
                  ICR pull &mdash; from the O&amp;M equipment tab
                </div>
                <p className="mt-1 text-[11px] text-emerald-800">
                  Every <strong>Construction Project</strong> row above is ICR work that the app
                  does not hold yet. Pulling in classifies each PR as <strong>ICR</strong> and
                  routes it to MTO &rarr; Project Control &rarr; Equipment Assessment. Re-running
                  updates the existing PR in place &mdash; it never duplicates.
                </p>
              </div>
              <button
                type="button"
                onClick={onPull}
                disabled={pulling}
                className="rounded-xl bg-emerald-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-800 disabled:opacity-60"
              >
                {pulling ? 'Pulling...' : 'Pull ICR projects'}
              </button>
            </div>

            {pullError && (
              <p className="mt-3 rounded-lg bg-red-100 px-3 py-2 text-xs font-semibold text-red-800">
                {pullError}
              </p>
            )}

            {pullResult?.ok && (
              <div className="mt-3 space-y-2">
                <div className="flex flex-wrap gap-3 text-xs font-semibold">
                  <span className="rounded-full bg-white px-3 py-1 text-emerald-800 ring-1 ring-inset ring-emerald-300">
                    Created {pullResult.created}
                  </span>
                  <span className="rounded-full bg-white px-3 py-1 text-blue-800 ring-1 ring-inset ring-blue-300">
                    Updated {pullResult.updated}
                  </span>
                  <span className="rounded-full bg-white px-3 py-1 text-apple-muted ring-1 ring-inset ring-apple-border">
                    Already in place {pullResult.unchanged}
                  </span>
                  <span className="rounded-full bg-white px-3 py-1 text-apple-muted ring-1 ring-inset ring-apple-border">
                    {pullResult.total} construction rows
                  </span>
                </div>
                <ul className="space-y-1">
                  {pullResult.items.map((it) => (
                    <li
                      key={it.pr_key}
                      className="flex flex-wrap items-center gap-2 rounded-lg bg-white/70 px-3 py-1.5 text-[11px] text-emerald-900"
                    >
                      <span className="font-mono font-semibold">{it.pr_key}</span>
                      <span className="font-semibold uppercase tracking-wide">{it.action}</span>
                      <span className="min-w-0 flex-1 truncate">{it.title}</span>
                      <Link href={'/projects/' + it.project_id} className="font-semibold text-emerald-700 underline">
                        open
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {error && <ErrorBox message={error} />}
        {!data && !error && <p className="text-sm text-apple-muted">Loading…</p>}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KpiCard
                label="IHP active"
                value={s.ihp_active_count ?? 0}
                hint="construction projects (counted)"
                accent="green"
              />
              <KpiCard
                label="In app as ICR"
                value={icrInApp}
                hint="pulled from the equipment tab"
                accent="teal"
              />
              <KpiCard
                label="Equipment installation"
                value={s.equipment_branch_count ?? 0}
                hint="no modification / utility tie-in"
                accent="orange"
              />
              <KpiCard
                label="ASEPC proposals"
                value={s.assessment_count ?? 0}
                hint="assessment / proposal stage"
                accent="violet"
              />
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
                          {r.in_app && (
                            <span
                              className={
                                r.app_disposition === 'ICR'
                                  ? 'rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-800'
                                  : 'rounded-full bg-slate-100 px-2 py-0.5 font-semibold text-slate-700'
                              }
                            >
                              In app &middot; {r.app_disposition ?? 'PROJECT'}
                            </span>
                          )}
                          {r.request_date && <span>{r.request_date.slice(0, 10)}</span>}
                          {(r as { tag?: string }).tag && (
                            <span
                              className={
                                (r as { tag?: string }).tag === 'Upcoming EAR'
                                  ? 'rounded-full bg-purple-100 px-2 py-0.5 font-semibold text-purple-800'
                                  : (r as { tag?: string }).tag === 'Equipment installation'
                                    ? 'rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-800'
                                    : (r as { tag?: string }).tag === 'In app · ICR'
                                      ? 'rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-800'
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
