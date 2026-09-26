'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { autoImportTrackers, getConsistency, getOmActivePrs, getTrackerSources, listProjects } from '@/lib/api';
import type { ConsistencyResponse, OmActiveResponse } from '@/lib/api';
import type { TrackerSources } from '@/lib/api';
import { canDo, useUser } from '@/lib/useUser';
import { EAR_STATUS_LABELS, EAR_STATUS_ORDER, PHASES, PRIORITY_STYLES } from '@/lib/types';
import type { ProjectSummary } from '@/lib/types';

/**
 * Dashboard tile order — the Planner's own lifecycle buckets, in delivery
 * sequence. EAR comes first, then Design, then Construction.
 */
const BUCKETS: { key: string; label: string; hint: string; accent: string }[] = [
  { key: 'EAR', label: 'EAR Projects', hint: 'Engineering Assessment & Review', accent: 'bg-indigo-500' },
  { key: 'DESIGN', label: 'Design Projects', hint: 'SOW / BOQ approved', accent: 'bg-blue-500' },
  { key: 'PROCORE', label: 'Procore', hint: 'Quotation / PO processing', accent: 'bg-cyan-500' },
  { key: 'PTW/WICF', label: 'PTW / WICF', hint: 'Permit to Work', accent: 'bg-teal-500' },
  { key: 'CONSTRUCTION', label: 'Construction Projects', hint: 'Field execution', accent: 'bg-orange-500' },
  { key: 'SHUTDOWN', label: 'Shutdown', hint: 'Outage-window work', accent: 'bg-red-500' },
  { key: 'QUALITY INSPECTION', label: 'Quality Inspection', hint: 'QA / inspections', accent: 'bg-pink-500' },
  { key: 'WCC', label: 'WCC', hint: 'Work Completion Certificate', accent: 'bg-emerald-500' },
  { key: 'WCH', label: 'WCH', hint: 'Work Completion Handover', accent: 'bg-green-700' },
];

export default function DashboardPage() {
  return (
    <AuthGuard>
      <BucketDashboard />
    </AuthGuard>
  );
}

function BucketDashboard() {
  const { user } = useUser();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<TrackerSources | null>(null);
  const [omActive, setOmActive] = useState<OmActiveResponse | null>(null);
  const [consistency, setConsistency] = useState<ConsistencyResponse | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    listProjects()
      .then(setProjects)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'));
  }, []);

  useEffect(() => {
    load();
    getTrackerSources().then(setSources).catch(() => setSources(null));
    getOmActivePrs().then(setOmActive).catch(() => setOmActive(null));
    getConsistency().then(setConsistency).catch(() => setConsistency(null));
  }, [load]);

  const isAdmin = canDo(user, 'users.manage');

  async function handleSync() {
    setSyncing(true);
    setNotice(null);
    setError(null);
    try {
      const res = await autoImportTrackers();
      setNotice(
        `Synced ${res.planner_file} (${res.planner_date ?? 'undated'}) — ` +
        `${res.rows_processed} planner rows` +
        (res.om_file ? `, ${res.om_rows} O&M rows` : ''),
      );
      load();
      getTrackerSources().then(setSources).catch(() => undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sync failed');
    } finally {
      setSyncing(false);
    }
  }

  // Bucket totals and division totals are kept in SEPARATE maps on purpose:
  // "EAR" is both a Planner bucket and a division name, so one shared map
  // would count every EAR project twice (26 bucket + 26 division = 52).
  const bucketCounts = useMemo(() => {
    const c: Record<string, number> = {};
    (projects ?? []).forEach((p) => {
      // Only rows present in the newest Planner snapshot are counted, so
      // stale/removed PRs never inflate a total.
      if (!p.in_latest_planner) return;
      if (p.planner_bucket) c[p.planner_bucket] = (c[p.planner_bucket] ?? 0) + 1;
    });
    return c;
  }, [projects]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    (projects ?? []).forEach((p) => {
      if (!p.in_latest_planner) return;
      if (p.phase) c[p.phase] = (c[p.phase] ?? 0) + 1;
    });
    return c;
  }, [projects]);

  /**
   * Per-division breakdown for the cards.
   *
   * `statuses` groups by the WORKFLOW stage - the project's real current
   * status, and the one users can change - not by the last Planner note
   * (a project sitting at SOW_APPROVED often has "EAR Approved" as its last
   * note, which read as if it were still in EAR).
   * `buckets` shows which Planner buckets make up the division total, so
   * membership is always verifiable.
   */
  const phaseBreakdown = useMemo(() => {
    const byPhase: Record<string, { statuses: Record<string, number>; buckets: Record<string, number> }> = {};
    (projects ?? []).forEach((p) => {
      if (!p.in_latest_planner) return;
      const ph = p.phase;
      if (!ph) return;
      byPhase[ph] = byPhase[ph] ?? { statuses: {}, buckets: {} };
      const status = (p.stage || 'INTAKE').replace(/_/g, ' ');
      byPhase[ph].statuses[status] = (byPhase[ph].statuses[status] ?? 0) + 1;
      const b = p.planner_bucket ?? '(none)';
      byPhase[ph].buckets[b] = (byPhase[ph].buckets[b] ?? 0) + 1;
    });
    const out: Record<string, { statuses: [string, number][]; buckets: [string, number][] }> = {};
    Object.entries(byPhase).forEach(([ph, v]) => {
      out[ph] = {
        statuses: Object.entries(v.statuses).sort((a, b) => b[1] - a[1]),
        buckets: Object.entries(v.buckets).sort((a, b) => b[1] - a[1]),
      };
    });
    return out;
  }, [projects]);

  /**
   * EAR funnel: how many EAR projects sit at each step
   * (On Hold / WBS Request / EAR Issued / EAR Approved / Awaiting Summary).
   */
  const earFunnel = useMemo(() => {
    const c: Record<string, number> = {};
    (projects ?? []).forEach((p) => {
      if (!p.in_latest_planner || p.phase !== 'EAR') return;
      const key = p.ear_substatus ?? 'in_progress';
      c[key] = (c[key] ?? 0) + 1;
    });
    return EAR_STATUS_ORDER.filter((k) => c[k]).map(
      (k) => [EAR_STATUS_LABELS[k] ?? k, c[k]] as [string, number],
    );
  }, [projects]);

  const priorityCounts = useMemo(() => {
    const c: Record<string, number> = {};
    (projects ?? []).forEach((p) => {
      if (p.priority) c[p.priority] = (c[p.priority] ?? 0) + 1;
    });
    return c;
  }, [projects]);

  const typeCounts = useMemo(() => {
    const c: Record<string, number> = {};
    (projects ?? []).forEach((p) => {
      if (p.project_type) c[p.project_type] = (c[p.project_type] ?? 0) + 1;
    });
    return c;
  }, [projects]);

  const flagCounts = useMemo(() => {
    const c: Record<string, number> = {};
    (projects ?? []).forEach((p) => {
      (p.flags ?? []).forEach((f) => {
        c[f] = (c[f] ?? 0) + 1;
      });
    });
    return Object.fromEntries(Object.entries(c).sort((a, b) => b[1] - a[1]));
  }, [projects]);

  const total = projects?.length ?? 0;
  // Bucketed = rows carrying a Planner bucket in the current snapshot.
  const bucketed = Object.values(bucketCounts).reduce((a, b) => a + b, 0);

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-apple-text">
              IHP Project Dashboard
            </h1>
            <p className="mt-1 text-sm text-apple-muted">
              {bucketed} bucketed of {total} projects — click a bucket to open its dashboard
            </p>
          </div>
          <div className="flex gap-4">
            <Link
              href="/dashboard/active-prs"
              className="text-xs font-semibold text-primary hover:underline"
            >
              Active PRs (O&amp;M classification) →
            </Link>
            <Link
              href="/dashboard/construction"
              className="text-xs text-apple-muted hover:text-apple-text"
            >
              Construction &amp; Materials →
            </Link>
          </div>
        </div>

        {/* Tracker sync banner: which dated source file the app is using */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-apple-border bg-white px-4 py-3">
          <div className="text-xs text-apple-muted">
            <span className="font-semibold text-apple-text">Auto-tracked source:</span>{' '}
            {sources?.planner_latest ? (
              <>
                <span className="font-mono">{sources.planner_latest}</span>
                {sources.planner_date && (
                  <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700">
                    {sources.planner_date}
                  </span>
                )}
              </>
            ) : (
              <span className="italic">no planner file resolved</span>
            )}
            {sources?.om_latest && (
              <div className="mt-1">
                <span className="font-semibold text-apple-text">O&amp;M sheet:</span>{' '}
                <span className="font-mono">{sources.om_latest}</span>
                {sources.om_date && (
                  <span className="ml-2 rounded bg-blue-50 px-1.5 py-0.5 font-medium text-blue-700">
                    {sources.om_date}
                  </span>
                )}
              </div>
            )}
            <div className="mt-1 text-[11px] italic">
              Always the newest _DDMMYYYY export (.xlsx or .md) — no manual upload needed.
            </div>
          </div>
          {isAdmin && (
            <button
              type="button"
              onClick={() => void handleSync()}
              disabled={syncing}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              {syncing ? 'Syncing…' : 'Sync latest tracker'}
            </button>
          )}
        </div>

        {notice && (
          <p className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            {notice}
          </p>
        )}

        {/* Blinking inconsistency alert — shown only when the trackers disagree */}
        {consistency?.ok && ((consistency.summary.errors ?? 0) > 0 || (consistency.summary.warnings ?? 0) > 0) && (
          <Link
            href="/dashboard/consistency"
            className="block rounded-xl border-2 border-amber-400 bg-amber-50 p-4 transition hover:bg-amber-100"
          >
            <div className="flex flex-wrap items-center gap-3">
              <span className="relative flex h-3 w-3 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-500 opacity-75" />
                <span className="relative inline-flex h-3 w-3 rounded-full bg-amber-600" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-sm font-bold text-amber-900">
                  <span className="animate-pulse">⚠ Tracking inconsistency detected</span>
                  {(consistency.summary.errors ?? 0) > 0 && (
                    <span className="rounded-full bg-red-600 px-2 py-0.5 text-[11px] font-bold text-white">
                      {consistency.summary.errors} error{consistency.summary.errors === 1 ? '' : 's'}
                    </span>
                  )}
                  {(consistency.summary.warnings ?? 0) > 0 && (
                    <span className="rounded-full bg-amber-600 px-2 py-0.5 text-[11px] font-bold text-white">
                      {consistency.summary.warnings} warning{consistency.summary.warnings === 1 ? '' : 's'}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] text-amber-800">
                  The Planner and the O&amp;M tracker disagree — click to see every affected PR.
                </p>
              </div>
              <span className="text-xs font-semibold text-amber-900">Review →</span>
            </div>
          </Link>
        )}
        {consistency?.ok && (consistency.summary.errors ?? 0) === 0 && (consistency.summary.warnings ?? 0) === 0 && (
          <Link
            href="/dashboard/consistency"
            className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-semibold text-emerald-800"
          >
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Tracking consistent — {consistency.summary.total_checked ?? 0} PRs cross-checked
          </Link>
        )}
        {error && <ErrorBox message={error} />}
        {!projects && !error && (
          <p className="text-sm text-apple-muted">Loading projects…</p>
        )}

        {/* The three lifecycle divisions — click to drill into the register */}
        <div>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-apple-muted">
            Project divisions
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {PHASES.map((ph) => {
              const n = counts[ph.key] ?? 0;
              const bd = phaseBreakdown[ph.key];
              const isEar = ph.key === 'EAR';
              // EAR breaks down by its own funnel (On Hold / EAR Issued /
              // WBS Request / EAR Approved / Awaiting Summary); the other
              // divisions break down by workflow status.
              const top = isEar ? earFunnel : (bd?.statuses ?? []);
              const composition = bd?.buckets ?? [];
              return (
                <Link
                  key={ph.key}
                  href={`/projects?phase=${encodeURIComponent(ph.key)}`}
                  className="group rounded-2xl border-2 border-apple-border bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-primary hover:shadow-md"
                >
                  <div className="flex items-baseline justify-between">
                    <span className="text-base font-bold text-apple-text">{ph.label}</span>
                    <span className="text-3xl font-bold tabular-nums text-primary">{n}</span>
                  </div>
                  <p className="mt-1 text-xs text-apple-muted">{ph.hint}</p>
                  {/* Which Planner buckets make up this division */}
                  <div className="mt-2 flex flex-wrap gap-1">
                    {composition.map(([b, c]) => (
                      <span
                        key={b}
                        className="rounded bg-apple-surface px-1.5 py-0.5 text-[10px] font-medium text-apple-muted"
                      >
                        {b} · {c}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3 space-y-1 border-t border-apple-border pt-2">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-apple-muted">
                      {isEar ? 'EAR status' : 'Status'}
                    </div>
                    {top.slice(0, isEar ? 6 : 3).map(([status, c]) => (
                      <div key={status} className="flex items-center justify-between text-[11px]">
                        <span
                          className={
                            isEar && status === EAR_STATUS_LABELS.on_hold
                              ? 'truncate font-semibold text-red-600'
                              : 'truncate text-apple-muted'
                          }
                        >
                          {status}
                        </span>
                        <span className="font-semibold tabular-nums text-apple-text">{c}</span>
                      </div>
                    ))}
                    {top.length === 0 && (
                      <span className="text-[11px] italic text-apple-muted">no statuses yet</span>
                    )}
                  </div>
                  {/* O&M-derived EAR work is tagged here, never added to the total */}
                  {isEar && (omActive?.summary.upcoming_ear_count ?? 0) > 0 && (
                    <div className="mt-2 flex items-center justify-between border-t border-dashed border-purple-200 pt-2 text-[11px]">
                      <span className="font-semibold text-purple-700">Upcoming EAR</span>
                      <span className="rounded-full bg-purple-100 px-2 py-0.5 font-bold text-purple-800">
                        {omActive?.summary.upcoming_ear_count}
                      </span>
                    </div>
                  )}
                  <span className="mt-3 inline-block text-[11px] font-medium text-primary">
                    View all {n} projects →
                  </span>
                </Link>
              );
            })}
          </div>
        </div>

        {/* Priority + flag summary from the Notes/Labels analysis */}
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-apple-border bg-white p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-apple-muted">
              Priority breakdown
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(priorityCounts).sort((a, b) => b[1] - a[1]).map(([p, c]) => (
                <span
                  key={p}
                  className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${
                    PRIORITY_STYLES[p.toLowerCase()] ?? 'bg-gray-100 text-gray-700 ring-gray-300'
                  }`}
                >
                  {p} · {c}
                </span>
              ))}
              {Object.keys(priorityCounts).length === 0 && (
                <span className="text-xs italic text-apple-muted">no priorities yet</span>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-apple-border bg-white p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-apple-muted">
              Project type &amp; flags
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(typeCounts).map(([t, c]) => (
                <span key={t} className={`rounded-full px-3 py-1 font-semibold ring-1 ring-inset ${
                  t === 'ASEPC'
                    ? 'bg-purple-100 text-purple-800 ring-purple-300'
                    : 'bg-emerald-100 text-emerald-800 ring-emerald-300'
                }`}>
                  {t} · {c}
                </span>
              ))}
              {Object.entries(flagCounts).slice(0, 6).map(([f, c]) => (
                <span key={f} className="rounded-full bg-apple-surface px-3 py-1 font-medium text-apple-text ring-1 ring-inset ring-apple-border">
                  {f} · {c}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* O&M-derived work: tagged separately, never counted in the divisions */}
        {omActive?.summary && (
          <Link
            href="/dashboard/active-prs"
            className="block rounded-xl border border-purple-200 bg-purple-50 p-4 transition hover:shadow-md"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-purple-700">
                  From the O&amp;M tracker (tagged, not counted above)
                </div>
                <p className="mt-1 text-[11px] text-purple-700">
                  EAR above counts <strong>Planner data only</strong>. Assessment-stage PRs that
                  the Planner has not picked up yet are tagged <strong>Upcoming EAR</strong>.
                </p>
              </div>
              <div className="flex gap-3 text-center">
                <div className="rounded-lg bg-white px-4 py-2">
                  <div className="text-2xl font-bold tabular-nums text-purple-800">
                    {omActive.summary.upcoming_ear_count ?? 0}
                  </div>
                  <div className="text-[10px] font-semibold uppercase text-purple-700">Upcoming EAR</div>
                </div>
                <div className="rounded-lg bg-white px-4 py-2">
                  <div className="text-2xl font-bold tabular-nums text-amber-700">
                    {omActive.summary.equipment_branch_count ?? 0}
                  </div>
                  <div className="text-[10px] font-semibold uppercase text-amber-700">Equipment installation</div>
                </div>
                <div className="rounded-lg bg-white px-4 py-2">
                  <div className="text-2xl font-bold tabular-nums text-emerald-700">
                    {omActive.summary.ihp_active_count ?? 0}
                  </div>
                  <div className="text-[10px] font-semibold uppercase text-emerald-700">IHP Construction</div>
                </div>
              </div>
            </div>
          </Link>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {BUCKETS.map((b) => (
            <Link
              key={b.key}
              href={`/dashboard/bucket/${encodeURIComponent(b.key)}`}
              className="group rounded-2xl border border-apple-border bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
            >
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-semibold uppercase tracking-wide text-apple-muted group-hover:text-apple-text">
                  {b.label}
                </span>
                <span className="text-3xl font-bold tabular-nums text-apple-text">
                  {bucketCounts[b.key] ?? 0}
                </span>
              </div>
              <p className="mt-2 text-xs text-apple-muted">{b.hint}</p>
              <div className="mt-3 h-1.5 rounded-full bg-apple-surface">
                <div
                  className={`h-full rounded-full transition-all ${b.accent}`}
                  style={{ width: `${total ? ((bucketCounts[b.key] ?? 0) / total) * 100 : 0}%` }}
                />
              </div>
              <span className="mt-2 inline-block text-[11px] font-medium text-primary opacity-0 transition group-hover:opacity-100">
                Open dashboard →
              </span>
            </Link>
          ))}

          <Link
            href="/projects"
            className="rounded-2xl border border-dashed border-apple-border bg-white/50 p-5 transition hover:bg-white"
          >
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-semibold uppercase tracking-wide text-apple-muted">
                All / Unbucketed
              </span>
              <span className="text-3xl font-bold tabular-nums text-apple-text">
                {total - bucketed}
              </span>
            </div>
            <p className="mt-2 text-xs text-apple-muted">
              Projects without a planner bucket (manual, demo, upcoming)
            </p>
          </Link>
        </div>
      </main>
    </div>
  );
}
