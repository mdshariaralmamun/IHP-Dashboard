'use client';

import { use, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { ApiError, listProjects, setProjectStage, updateProject } from '@/lib/api';
import { stageName, STAGE_IDS } from '@/lib/stages';
import { canDo, useUser } from '@/lib/useUser';
import type { ProjectSummary } from '@/lib/types';

/** Workflow statuses a project can be moved to from the dashboard. */
// The stage list comes from lib/stages so a new stage (CANCELLED) appears
// here, in the register and in the badge without being added three times.
const STATUS_OPTIONS = STAGE_IDS;

const STATUS_COLORS: string[] = [
  'bg-slate-100 text-slate-700',
  'bg-amber-100 text-amber-800',
  'bg-indigo-100 text-indigo-800',
  'bg-blue-100 text-blue-800',
  'bg-cyan-100 text-cyan-800',
  'bg-teal-100 text-teal-800',
  'bg-orange-100 text-orange-800',
  'bg-pink-100 text-pink-800',
  'bg-emerald-100 text-emerald-800',
  'bg-green-100 text-green-800',
];

/** One bucket's detail dashboard: status counts, inline status edit, drill-down. */
export default function BucketDetailPage({
  params,
}: {
  params: Promise<{ bucket: string }>;
}) {
  const { bucket } = use(params);
  return (
    <AuthGuard>
      <BucketDetail bucket={decodeURIComponent(bucket)} />
    </AuthGuard>
  );
}

function BucketDetail({ bucket }: { bucket: string }) {
  const { user } = useUser();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  // A stage change needs a reason, so the select only picks the target and a
  // small inline form collects the why before anything is written.
  const [pending, setPending] = useState<{ project: ProjectSummary; stage: string } | null>(null);
  const [why, setWhy] = useState('');
  const [search, setSearch] = useState('');
  const [stage, setStage] = useState('');
  const [trade, setTrade] = useState('');

  const canEdit = canDo(user, 'projects.edit');

  const load = useCallback(() => {
    listProjects({ bucket })
      .then(setProjects)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'));
  }, [bucket]);

  useEffect(() => {
    load();
  }, [load]);

  // A PR removed from the newest Planner is not in this bucket any more;
  // counting it here made the drill-down disagree with the dashboard tile.
  const live = useMemo(
    () => (projects ?? []).filter((p) => !p.planner_removed),
    [projects],
  );

  const statusCounts = useMemo(() => {
    const c: Record<string, number> = {};
    live.forEach((p) => {
      c[p.stage] = (c[p.stage] ?? 0) + 1;
    });
    return c;
  }, [live]);

  const stages = useMemo(
    () => Array.from(new Set(live.map((p) => p.stage))).sort(), [live]);
  const trades = useMemo(
    () => Array.from(new Set(live.flatMap((p) => p.trades ?? []))).sort(),
    [live]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return live.filter((p) => {
      if (stage && p.stage !== stage) return false;
      if (trade && !(p.trades ?? []).includes(trade)) return false;
      if (q && ![p.pr_number, p.title, p.pi_name, p.location]
          .some((v) => (v ?? '').toLowerCase().includes(q))) return false;
      return true;
    });
  }, [live, search, stage, trade]);

  async function applyStageChange() {
    if (!pending) return;
    const { project, stage } = pending;
    setBusyId(project.id);
    setError(null);
    setNotice(null);
    try {
      await setProjectStage(project.id, stage, { justification: why });
      setNotice(`${project.pr_number} → ${stageName(stage)}`);
      setPending(null);
      setWhy('');
      load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(
          `${project.pr_number}: the workflow has no path from ${stageName(project.stage)} ` +
          `to ${stageName(stage)}. Open the project and use the phase panel to override it ` +
          `with the reason.`,
        );
        setPending(null);
      } else {
        setError(e instanceof Error ? e.message : 'Could not change status');
      }
    } finally {
      setBusyId(null);
    }
  }

  async function changeBucket(project: ProjectSummary, newBucket: string) {
    setBusyId(project.id);
    setError(null);
    try {
      await updateProject(project.id, { planner_bucket: newBucket } as never);
      setNotice(`${project.pr_number} moved to bucket ${newBucket}`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change bucket');
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-6xl space-y-5 px-4 py-8">
        <Link href="/dashboard" className="text-xs text-apple-muted hover:text-apple-text">
          ← Dashboard
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-2xl font-bold tracking-tight text-apple-text">
            {bucket} <span className="text-apple-muted">· {rows.length} projects</span>
          </h1>
          <div className="flex flex-wrap gap-2">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search PR, title, PI, location…"
              className="w-64 rounded-lg border border-apple-border bg-white px-3 py-1.5 text-sm"
            />
            <select value={stage} onChange={(e) => setStage(e.target.value)}
                    className="rounded-lg border border-apple-border bg-white px-2 py-1.5 text-sm">
              <option value="">All statuses</option>
              {stages.map((s) => <option key={s}>{s}</option>)}
            </select>
            <select value={trade} onChange={(e) => setTrade(e.target.value)}
                    className="rounded-lg border border-apple-border bg-white px-2 py-1.5 text-sm">
              <option value="">All trades</option>
              {trades.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
        </div>

        {/* How many projects in which status — clickable chips filter the list */}
        {projects && projects.length > 0 && (
          <div className="rounded-xl border border-apple-border bg-white p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-apple-muted">
              Status breakdown
            </div>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setStage('')}
                className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                  stage === '' ? 'bg-primary text-white ring-primary' : 'bg-apple-surface text-apple-text ring-apple-border'
                }`}
              >
                All {projects.length}
              </button>
              {Object.entries(statusCounts).sort((a, b) => b[1] - a[1]).map(([s, n], i) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStage(stage === s ? '' : s)}
                  className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition ${
                    stage === s ? 'ring-primary ring-2' : 'ring-transparent'
                  } ${STATUS_COLORS[i % STATUS_COLORS.length]}`}
                >
                  {s.replace(/_/g, ' ')} · {n}
                </button>
              ))}
            </div>
          </div>
        )}

        {notice && (
          <p className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            {notice}
          </p>
        )}
        {error && <ErrorBox message={error} />}
        {!projects && !error && <p className="text-sm text-apple-muted">Loading…</p>}
        {projects && rows.length === 0 && (
          <p className="text-sm text-apple-muted">No projects match.</p>
        )}

        <ul className="space-y-3">
          {rows.map((p) => {
            const pct = p.completion_pct ?? 0;
            return (
              <li key={p.id}
                  className="rounded-2xl border border-apple-border bg-white p-4 shadow-sm">
                <Link href={`/projects/${p.id}`} className="block transition hover:opacity-80">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div>
                      <span className="font-mono text-xs font-semibold text-apple-muted">
                        {p.pr_number}
                      </span>
                      <span className="ml-2 font-semibold text-apple-text">{p.title}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      <span className="text-apple-muted">{p.location ?? '—'}</span>
                      {p.pi_name && <span className="text-apple-muted">PI: {p.pi_name}</span>}
                    </div>
                  </div>

                  <div className="mt-3 flex items-center gap-2">
                    <span className={pct > 0 ? 'text-emerald-500' : 'text-apple-muted'}>
                      {pct >= 100 ? '✔' : pct > 0 ? '▲' : '•'}
                    </span>
                    <div className="h-2 flex-1 rounded-full bg-apple-surface">
                      <div className="h-full rounded-full bg-emerald-500"
                           style={{ width: `${pct}%` }} />
                    </div>
                    <span className="w-10 text-right text-xs tabular-nums text-apple-muted">
                      {pct}%
                    </span>
                  </div>

                  <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                    {(p.trades ?? []).map((t) => (
                      <span key={t} className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">
                        {t}
                      </span>
                    ))}
                    {p.division && (
                      <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">
                        {p.division}
                      </span>
                    )}
                    {p.priority && (
                      <span className="rounded bg-purple-50 px-1.5 py-0.5 text-purple-700">
                        {p.priority}
                      </span>
                    )}
                  </div>
                </Link>

                {/* Inline status + bucket editing */}
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-apple-border pt-3">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-apple-muted">
                    Status
                  </span>
                  <select
                    value={p.stage}
                    disabled={!canEdit || busyId === p.id}
                    onChange={(e) => {
                      setPending({ project: p, stage: e.target.value });
                      setWhy('');
                      setError(null);
                    }}
                    className="rounded-md border border-apple-border bg-white px-2 py-1 text-xs font-medium text-apple-text disabled:opacity-60"
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>{stageName(s)}</option>
                    ))}
                    {!STATUS_OPTIONS.includes(p.stage) && (
                      <option value={p.stage}>{p.stage}</option>
                    )}
                  </select>

                  <span className="ml-2 text-[11px] font-semibold uppercase tracking-wide text-apple-muted">
                    Bucket
                  </span>
                  <select
                    value={p.planner_bucket ?? ''}
                    disabled={!canEdit || busyId === p.id}
                    onChange={(e) => void changeBucket(p, e.target.value)}
                    className="rounded-md border border-apple-border bg-white px-2 py-1 text-xs font-medium text-apple-text disabled:opacity-60"
                  >
                    <option value="">—</option>
                    {['EAR', 'DESIGN', 'PROCORE', 'PTW/WICF', 'CONSTRUCTION', 'SHUTDOWN',
                      'QUALITY INSPECTION', 'WCC', 'WCH'].map((b) => (
                      <option key={b} value={b}>{b}</option>
                    ))}
                  </select>

                  {busyId === p.id && (
                    <span className="text-[11px] text-apple-muted">saving…</span>
                  )}
                  {!canEdit && (
                    <span className="text-[11px] italic text-apple-muted">
                      read-only (needs projects.edit)
                    </span>
                  )}

                  {pending?.project.id === p.id && (
                    <div className="mt-1 flex w-full flex-wrap items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5">
                      <span className="text-[11px] font-semibold text-amber-900">
                        {p.pr_number} → {stageName(pending.stage)} — why?
                      </span>
                      <input
                        value={why}
                        onChange={(e) => setWhy(e.target.value)}
                        placeholder="Reason (saved to the audit trail)"
                        className="min-w-[220px] flex-1 rounded border border-amber-200 bg-white px-2 py-1 text-xs text-apple-text"
                      />
                      <button
                        type="button"
                        disabled={why.trim().length < 3 || busyId === p.id}
                        onClick={() => void applyStageChange()}
                        className="rounded bg-primary px-3 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
                      >
                        Move
                      </button>
                      <button
                        type="button"
                        onClick={() => { setPending(null); setWhy(''); }}
                        className="rounded border border-apple-border px-2 py-1 text-xs text-apple-text hover:bg-apple-surface"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </main>
    </div>
  );
}
