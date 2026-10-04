'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { listProjects, listTodos, updateTodo } from '@/lib/api';
import type { ProjectSummary, TodoListResponse, TodoRow } from '@/lib/types';
import { FOLLOWUP_BUCKETS } from '@/lib/types';
import { stageName } from '@/lib/stages';
import { canDo, useUser } from '@/lib/useUser';
import {
  BarList,
  DataTable,
  KpiCard,
  PbiCanvas,
  SlicerBar,
  VisualCard,
} from '@/components/powerbi/PowerBI';

/**
 * The full-picture to-do list.
 *
 * Every PR has one next step and any number of tasks. This page is the whole
 * picture in one place: what is open, who owns it, which bucket it is worked
 * in (MTO, EAR, Design, Procore, PTW/WICF, Construction, Shutdown, Quality
 * Inspection, WCC, WCH, ICR), what is overdue, and which next steps are
 * already scheduled. Clicking a KPI, a bucket chip or a bar cross-filters the
 * board; opening a task's PR is one click away.
 */
export default function TodoPage() {
  return (
    <AuthGuard>
      <TodoBoard />
    </AuthGuard>
  );
}

function TodoBoard() {
  const { user } = useUser();
  const [data, setData] = useState<TodoListResponse | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [buckets, setBuckets] = useState<string[]>([]);
  const [assignee, setAssignee] = useState('');
  const [onlyMine, setOnlyMine] = useState(false);
  const [showDone, setShowDone] = useState(false);
  const [query, setQuery] = useState('');

  const load = useCallback(() => {
    listTodos({ status: showDone ? 'all' : 'open' })
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load the to-do list'));
  }, [showDone]);

  useEffect(() => {
    load();
    listProjects()
      .then(setProjects)
      .catch(() => setProjects(null));
  }, [load]);

  const canEdit = canDo(user, 'projects.edit');
  const today = new Date().toISOString().slice(0, 10);

  const toggleBucket = (key: string) =>
    setBuckets((prev) => (prev.includes(key) ? prev.filter((b) => b !== key) : [...prev, key]));

  const rows = data?.rows ?? [];
  const q = query.trim().toLowerCase();

  const filtered = useMemo(
    () =>
      rows.filter((r) => {
        if (buckets.length && !buckets.includes(r.bucket ?? '(no bucket)')) return false;
        if (assignee && (r.assignee_username ?? '(unassigned)') !== assignee) return false;
        if (onlyMine && r.assignee_username !== user?.username) return false;
        if (!q) return true;
        return (
          (r.title + ' ' + r.pr_number + ' ' + r.project_title + ' ' + (r.note ?? ''))
            .toLowerCase()
            .indexOf(q) >= 0
        );
      }),
    [rows, buckets, assignee, onlyMine, q, user?.username],
  );

  const grouped = useMemo(() => {
    const map: Record<string, TodoRow[]> = {};
    filtered.forEach((r) => {
      const key = r.bucket ?? '(no bucket)';
      map[key] = map[key] ?? [];
      map[key].push(r);
    });
    return map;
  }, [filtered]);

  const orderedBuckets = useMemo(() => {
    const known = FOLLOWUP_BUCKETS.filter((b) => grouped[b]);
    const extra = Object.keys(grouped).filter((b) => !FOLLOWUP_BUCKETS.includes(b));
    return [...known, ...extra];
  }, [grouped]);

  // Projects whose next step is scheduled - the plan side of the picture.
  const scheduled = useMemo(() => {
    return (projects ?? [])
      .filter((p) => p.next_stage && !p.planner_removed)
      .filter((p) => !buckets.length || buckets.includes(p.next_stage_bucket ?? '(no bucket)'))
      .filter((p) =>
        !q
          ? true
          : (p.pr_number + ' ' + p.title + ' ' + (p.next_stage_owner ?? ''))
              .toLowerCase()
              .indexOf(q) >= 0,
      )
      .sort((a, b) => (a.next_stage_date ?? '9999').localeCompare(b.next_stage_date ?? '9999'));
  }, [projects, buckets, q]);

  async function tick(row: TodoRow) {
    setBusy(true);
    try {
      await updateTodo(row.id, { status: row.status === 'done' ? 'open' : 'done' });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update the task.');
    } finally {
      setBusy(false);
    }
  }

  const clear = () => {
    setBuckets([]);
    setAssignee('');
    setOnlyMine(false);
    setQuery('');
  };

  const counts = data?.counts;
  const bucketItems = FOLLOWUP_BUCKETS.map((b) => ({
    key: b,
    label: b,
    value: counts?.by_bucket?.[b] ?? 0,
  })).filter((b) => b.value > 0);
  const extraItems = Object.entries(counts?.by_bucket ?? {})
    .filter(([b]) => !FOLLOWUP_BUCKETS.includes(b))
    .map(([label, value]) => ({ key: label, label, value }));

  const assigneeItems = Object.entries(counts?.by_assignee ?? {})
    .sort((a, b) => b[1] - a[1])
    .map(([label, value], i) => ({
      key: label,
      label,
      value,
      color: ['#118DFF', '#12239E', '#E66C37', '#6B007B', '#E044A7', '#744EC2'][i % 6],
    }));

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-7xl space-y-4 px-4 py-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-apple-text">
              To-do list — every PR
            </h1>
            <p className="mt-1 text-sm text-apple-muted">
              The full picture: next step per PR, tasks by follow-up bucket, owner and due date.
              {data?.counts ? ' ' + data.counts.open + ' open across ' + data.counts.total + ' rows.' : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className="flex items-center gap-1.5 rounded-full border border-apple-border bg-white px-3 py-1 font-semibold text-apple-muted dark:bg-white/5">
              <input
                type="checkbox"
                checked={onlyMine}
                onChange={(e) => setOnlyMine(e.target.checked)}
              />
              Only mine
            </label>
            <label className="flex items-center gap-1.5 rounded-full border border-apple-border bg-white px-3 py-1 font-semibold text-apple-muted dark:bg-white/5">
              <input
                type="checkbox"
                checked={showDone}
                onChange={(e) => setShowDone(e.target.checked)}
              />
              Show finished
            </label>
          </div>
        </div>

        {error && <ErrorBox message={error} />}
        {!data && !error && <p className="text-sm text-apple-muted">Loading…</p>}

        {data && (
          <PbiCanvas>
            {/* KPI strip */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <KpiCard
                label="Open tasks"
                value={counts?.open ?? 0}
                hint="across every PR"
                accent="navy"
                active={buckets.length === 0 && !onlyMine && !assignee && !q}
                onClick={clear}
              />
              <KpiCard
                label="Overdue"
                value={counts?.overdue ?? 0}
                hint="past the due date"
                accent="red"
                icon="⏰"
              />
              <KpiCard
                label="Mine"
                value={counts?.mine ?? 0}
                hint={user?.username ?? ''}
                accent="blue"
                active={onlyMine}
                onClick={() => setOnlyMine((v) => !v)}
              />
              <KpiCard
                label="Scheduled next steps"
                value={scheduled.length}
                hint="stage + date + owner"
                accent="teal"
              />
              <KpiCard
                label="ICR tasks"
                value={counts?.by_bucket?.['ICR'] ?? 0}
                hint="equipment branch"
                accent="pink"
                active={buckets.includes('ICR')}
                onClick={() => toggleBucket('ICR')}
              />
              <KpiCard
                label="Finished"
                value={counts?.done ?? 0}
                hint={showDone ? 'shown' : 'tick "Show finished" to see them'}
                accent="green"
              />
            </div>

            {/* Slicers */}
            <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200/80 bg-white p-2.5 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
              <SlicerBar
                label="Bucket"
                items={[...bucketItems, ...extraItems]}
                selected={buckets}
                onToggle={toggleBucket}
                onClear={() => setBuckets([])}
              />
              <select
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-apple-text dark:border-white/10 dark:bg-white/5"
              >
                <option value="">All assignees</option>
                {Object.keys(counts?.by_assignee ?? {}).sort().map((who) => (
                  <option key={who} value={who}>
                    {who}
                  </option>
                ))}
              </select>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search task, PR or project…"
                className="ml-auto w-full max-w-xs rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-apple-text outline-none focus:border-primary dark:border-white/10 dark:bg-white/5"
              />
            </div>

            {/* Visuals */}
            <div className="mt-3 grid gap-3 lg:grid-cols-3">
              <VisualCard title="Open tasks by bucket" subtitle="click a bar to filter the board">
                <BarList
                  items={[...bucketItems, ...extraItems].map((b, i) => ({
                    key: b.key,
                    label: b.label,
                    value: b.value,
                    color: ['#118DFF', '#12239E', '#E66C37', '#6B007B', '#E044A7', '#744EC2', '#D9B300', '#D64550'][i % 8],
                  }))}
                  selected={buckets}
                  onSelect={toggleBucket}
                />
              </VisualCard>
              <VisualCard title="By assignee" subtitle="who is carrying what">
                <BarList
                  items={assigneeItems}
                  selected={assignee ? [assignee] : []}
                  onSelect={(key) => setAssignee(assignee === key ? '' : key)}
                />
              </VisualCard>
              <VisualCard
                title="Scheduled next steps"
                subtitle="the plan already agreed for each PR"
              >
                <DataTable
                  rows={scheduled.slice(0, 12)}
                  hrefFor={(p) => '/projects/' + p.id}
                  empty="No next step scheduled yet."
                  columns={[
                    {
                      key: 'pr',
                      label: 'PR',
                      render: (p) => <span className="font-mono font-semibold">{p.pr_number}</span>,
                    },
                    {
                      key: 'next',
                      label: 'Next stage',
                      render: (p) => stageName(p.next_stage),
                    },
                    {
                      key: 'bucket',
                      label: 'Bucket',
                      render: (p) => p.next_stage_bucket ?? '—',
                    },
                    {
                      key: 'owner',
                      label: 'Owner',
                      render: (p) => p.next_stage_owner ?? '—',
                    },
                    {
                      key: 'due',
                      label: 'Due',
                      render: (p) => (
                        <span
                          className={
                            p.next_stage_date && p.next_stage_date < today
                              ? 'font-semibold text-red-600'
                              : ''
                          }
                        >
                          {p.next_stage_date ?? '—'}
                        </span>
                      ),
                    },
                  ]}
                />
              </VisualCard>
            </div>

            {/* The board itself, grouped by follow-up bucket */}
            <VisualCard
              className="mt-3"
              title={'Tasks — ' + filtered.length + ' of ' + rows.length + ' rows'}
              subtitle={
                buckets.length || assignee || onlyMine || q
                  ? 'filtered' + (buckets.length ? ' · ' + buckets.join(', ') : '') + (assignee ? ' · ' + assignee : '') + (onlyMine ? ' · mine' : '')
                  : 'every row, grouped by the bucket it is worked in'
              }
              actions={
                (buckets.length > 0 || assignee || onlyMine || q) && (
                  <button
                    type="button"
                    onClick={clear}
                    className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-500 hover:bg-slate-50 dark:border-white/10"
                  >
                    Clear filters
                  </button>
                )
              }
            >
              {orderedBuckets.length === 0 ? (
                <p className="rounded-lg border border-dashed border-slate-200 p-8 text-center text-sm text-slate-400">
                  Nothing matches this selection.
                </p>
              ) : (
                <div className="space-y-4">
                  {orderedBuckets.map((bucket) => (
                    <div key={bucket}>
                      <div className="mb-1.5 flex items-center gap-2">
                        <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                          {bucket}
                        </h3>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-500">
                          {grouped[bucket].filter((r) => r.status !== 'done').length} open
                        </span>
                      </div>
                      <ul className="space-y-1">
                        {grouped[bucket].map((row) => (
                          <li
                            key={row.id}
                            className={
                              'flex flex-wrap items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ' +
                              (row.status === 'done'
                                ? 'border-slate-100 bg-slate-50/60 opacity-70'
                                : row.due_date && row.due_date < today
                                  ? 'border-red-200 bg-red-50/50'
                                  : 'border-slate-200 bg-white dark:border-white/10 dark:bg-white/[0.03]')
                            }
                          >
                            <input
                              type="checkbox"
                              checked={row.status === 'done'}
                              disabled={!canEdit || busy}
                              onChange={() => void tick(row)}
                            />
                            <span
                              className={
                                row.status === 'done'
                                  ? 'text-slate-400 line-through'
                                  : 'font-medium text-apple-text'
                              }
                            >
                              {row.title}
                            </span>
                            <Link
                              href={'/projects/' + row.project_id}
                              className="font-mono text-[11px] font-semibold text-primary hover:underline"
                            >
                              {row.pr_number}
                            </Link>
                            <span className="max-w-[20rem] truncate text-[11px] text-slate-400">
                              {row.project_title}
                            </span>
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                              {stageName(row.project_stage)}
                            </span>
                            {row.assignee_username ? (
                              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700">
                                {row.assignee_username}
                              </span>
                            ) : (
                              <span className="text-[10px] italic text-slate-400">unassigned</span>
                            )}
                            {row.due_date && (
                              <span
                                className={
                                  'text-[10px] ' +
                                  (row.due_date < today && row.status !== 'done'
                                    ? 'font-bold text-red-600'
                                    : 'text-slate-500')
                                }
                              >
                                due {row.due_date}
                              </span>
                            )}
                            {row.project_disposition === 'ICR' && (
                              <span className="rounded-full bg-pink-100 px-2 py-0.5 text-[10px] font-semibold text-pink-700">
                                ICR
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </VisualCard>
          </PbiCanvas>
        )}
      </main>
    </div>
  );
}
