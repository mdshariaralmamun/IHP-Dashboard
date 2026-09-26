'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import {
  createCrewAssignment,
  deleteCrewAssignment,
  getConstructionDashboard,
  getConstructionLive,
  getConstructionOverview,
  getCrewLoad,
  notifyCrewAssignment,
  uploadAttachments,
} from '@/lib/api';
import type {
  ConstructionLiveResponse,
  ConstructionOverview,
  CrewLoad,
  ScheduleItem,
} from '@/lib/api';
import { PRIORITY_STYLES } from '@/lib/types';
import type { ConstructionDashboardKpis } from '@/lib/types';
import { canDo, useUser } from '@/lib/useUser';

/** Finish windows, in display order. */
const WINDOWS: { key: string; label: string; accent: string; dot: string }[] = [
  { key: 'overdue', label: 'Overdue', accent: 'border-red-300 bg-red-50', dot: 'bg-red-500' },
  { key: 'today', label: 'Due today', accent: 'border-orange-300 bg-orange-50', dot: 'bg-orange-500' },
  { key: 'week', label: 'Due this week', accent: 'border-amber-300 bg-amber-50', dot: 'bg-amber-500' },
  { key: 'two_weeks', label: 'Next 2 weeks', accent: 'border-yellow-200 bg-yellow-50', dot: 'bg-yellow-500' },
  { key: 'three_weeks', label: 'Next 3 weeks', accent: 'border-lime-200 bg-lime-50', dot: 'bg-lime-500' },
  { key: 'month', label: 'Within the month', accent: 'border-emerald-200 bg-emerald-50', dot: 'bg-emerald-500' },
  { key: 'later', label: 'Later', accent: 'border-apple-border bg-white', dot: 'bg-slate-400' },
];

const RISK_STYLE: Record<string, string> = {
  high: 'bg-red-600 text-white',
  medium: 'bg-amber-500 text-white',
  low: 'bg-emerald-100 text-emerald-800',
};

const SHIFT_STYLE: Record<string, string> = {
  over: 'bg-red-600 text-white',
  full: 'bg-emerald-600 text-white',
  partial: 'bg-amber-500 text-white',
  idle: 'bg-apple-surface text-apple-muted',
};

export default function ConstructionDashboardPage() {
  return (
    <AuthGuard>
      <ConstructionLiveView />
    </AuthGuard>
  );
}

function ConstructionLiveView() {
  const { user } = useUser();
  const [live, setLive] = useState<ConstructionLiveResponse | null>(null);
  const [materials, setMaterials] = useState<ConstructionDashboardKpis | null>(null);
  const [overview, setOverview] = useState<ConstructionOverview | null>(null);
  const [crew, setCrew] = useState<CrewLoad | null>(null);
  const [day, setDay] = useState<string>(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [phaseFilter, setPhaseFilter] = useState('Construction');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({
    project_id: '',
    person_name: '',
    person_email: '',
    person_phone: '',
    shift: 'FULL' as 'AM' | 'PM' | 'FULL',
    hours: '8',
    task: '',
  });

  useEffect(() => {
    Promise.all([
      getConstructionLive(),
      getConstructionDashboard().catch(() => null),
      getConstructionOverview().catch(() => null),
    ])
      .then(([liveData, matData, ovData]) => {
        setLive(liveData);
        setMaterials(matData);
        setOverview(ovData);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  const loadCrew = useCallback(async (d: string) => {
    try {
      setCrew(await getCrewLoad(d));
    } catch {
      setCrew(null);
    }
  }, []);

  useEffect(() => {
    void loadCrew(day);
  }, [day, loadCrew]);

  const canManage = canDo(user, 'construction.manage');

  const visible = useMemo(() => {
    const filter = (rows: ScheduleItem[]) =>
      rows.filter((r) => {
        if (phaseFilter && r.phase !== phaseFilter) return false;
        if (priorityFilter && (r.priority ?? '') !== priorityFilter) return false;
        return true;
      });
    const out: Record<string, ScheduleItem[]> = {};
    WINDOWS.forEach((w) => {
      out[w.key] = live ? filter(live.windows[w.key] ?? []) : [];
    });
    return out;
  }, [live, phaseFilter, priorityFilter]);

  async function handleAssign() {
    if (!draft.project_id || !draft.person_name.trim()) {
      setError('Pick a project and enter the person name.');
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createCrewAssignment({
        project_id: Number(draft.project_id),
        person_name: draft.person_name.trim(),
        person_email: draft.person_email.trim() || null,
        person_phone: draft.person_phone.trim() || null,
        work_date: day,
        shift: draft.shift,
        hours: draft.hours ? Number(draft.hours) : null,
        task: draft.task.trim() || null,
      });
      setNotice('Assigned ' + created.person_name + ' to ' + created.pr_number + ' - ' + created.shift + ' (' + created.hours + 'h)');
      setDraft({ ...draft, person_name: '', task: '' });
      await loadCrew(day);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the assignment');
    } finally {
      setSaving(false);
    }
  }

  async function handleNotify(id: number) {
    setNotice(null);
    setError(null);
    try {
      const res = await notifyCrewAssignment(id, 'auto');
      if (res.sent) {
        setNotice('Notification sent by ' + res.channel + '.');
      } else {
        const missing = Object.entries(res.configured)
          .filter(([, v]) => !v)
          .map(([k]) => k)
          .join(', ');
        setNotice('No channel configured (' + missing + '). Message ready to copy:' + String.fromCharCode(10) + res.message);
      }
      await loadCrew(day);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Notification failed');
    }
  }

  async function handleRemove(id: number) {
    if (!window.confirm('Remove this assignment?')) return;
    try {
      await deleteCrewAssignment(id);
      await loadCrew(day);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove the assignment');
    }
  }

  async function handleGanttUpload(file: File) {
    const target = draft.project_id || (overview?.projects[0] ? String(overview.projects[0].id) : '');
    if (!target) {
      setError('Choose a project first.');
      return;
    }
    setSaving(true);
    try {
      await uploadAttachments(Number(target), [file]);
      setNotice('Gantt chart "' + file.name + '" uploaded to the project.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-[1400px] space-y-5 px-4 py-6 sm:px-6">
        <div>
          <Link href="/" className="text-xs text-apple-muted hover:text-apple-text">
            ← Executive Dashboard
          </Link>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-apple-text">
            Live Construction Schedule
          </h1>
          <p className="mt-1 text-sm text-apple-muted">
            Construction division only — Planner finish dates, urgency, the stage gate to
            clear, the prorated man-hours per day, and the daily crew work load.
            {live?.today && <span className="ml-1 font-medium">As of {live.today}.</span>}
          </p>
        </div>

        {error && <ErrorBox message={error} />}
        {notice && (
          <p className="whitespace-pre-wrap rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            {notice}
          </p>
        )}
        {loading && !live && <p className="text-sm text-apple-muted">Loading the schedule…</p>}

        {overview && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {[
              { label: 'Total', value: overview.total, cls: 'text-apple-text' },
              { label: 'Started', value: overview.started, cls: 'text-blue-700' },
              { label: 'Finished', value: overview.finished, cls: 'text-emerald-700' },
              { label: 'Pending', value: overview.pending, cls: 'text-amber-700' },
              { label: 'Planned hours', value: Math.round(overview.planned_hours).toLocaleString(), cls: 'text-apple-text' },
              { label: 'Remaining hours', value: Math.round(overview.remaining_hours).toLocaleString(), cls: 'text-apple-text' },
              { label: 'Over-allocated', value: crew ? crew.totals.over_allocated : 0, cls: 'text-red-700' },
            ].map((k) => (
              <div key={k.label} className="rounded-xl border border-apple-border bg-white p-3">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-apple-muted">
                  {k.label}
                </div>
                <div className={'mt-1 text-xl font-bold tabular-nums ' + k.cls}>{k.value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Daily work load: AM 07:00-11:00 + PM 12:00-16:00 = 8 h */}
        <section className="rounded-xl border border-apple-border bg-white p-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-sm font-bold text-apple-text">Daily work load</h2>
              <p className="mt-0.5 text-[11px] text-apple-muted">
                AM 07:00–11:00 (4 h) + PM 12:00–16:00 (4 h) = 8 h per person.
                {crew && (
                  <> · {crew.totals.people} people · {crew.totals.hours} h assigned · {crew.totals.over_allocated} over-allocated</>
                )}
              </p>
            </div>
            <input
              type="date"
              value={day}
              onChange={(e) => setDay(e.target.value)}
              className="rounded-md border border-apple-border bg-white px-2 py-1 text-xs"
            />
          </div>

          {canManage && (
            <div className="mt-3 grid gap-2 rounded-lg border border-apple-border bg-apple-surface/50 p-3 sm:grid-cols-6">
              <select
                value={draft.project_id}
                onChange={(e) => setDraft({ ...draft, project_id: e.target.value })}
                className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs sm:col-span-2"
              >
                <option value="">Select project…</option>
                {(overview?.projects ?? []).map((pr) => (
                  <option key={pr.id} value={pr.id}>
                    {pr.pr_number} — {pr.title.slice(0, 40)}
                  </option>
                ))}
              </select>
              <input placeholder="Person name" value={draft.person_name}
                onChange={(e) => setDraft({ ...draft, person_name: e.target.value })}
                className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs" />
              <input placeholder="Email" value={draft.person_email}
                onChange={(e) => setDraft({ ...draft, person_email: e.target.value })}
                className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs" />
              <input placeholder="Phone (+966…)" value={draft.person_phone}
                onChange={(e) => setDraft({ ...draft, person_phone: e.target.value })}
                className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs" />
              <div className="flex gap-2">
                <select value={draft.shift}
                  onChange={(e) => setDraft({ ...draft, shift: e.target.value as 'AM' | 'PM' | 'FULL' })}
                  className="w-full rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs">
                  <option value="FULL">FULL 8h</option>
                  <option value="AM">AM 4h</option>
                  <option value="PM">PM 4h</option>
                </select>
                <input value={draft.hours}
                  onChange={(e) => setDraft({ ...draft, hours: e.target.value })}
                  className="w-16 rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs" />
              </div>
              <input placeholder="Task / scope" value={draft.task}
                onChange={(e) => setDraft({ ...draft, task: e.target.value })}
                className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs sm:col-span-2" />
              <button type="button" onClick={() => void handleAssign()} disabled={saving}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
                {saving ? 'Saving…' : '+ Assign'}
              </button>
              <label className="cursor-pointer rounded-md border border-apple-border bg-white px-3 py-1.5 text-center text-xs font-medium text-apple-text">
                Upload Gantt
                <input type="file" className="hidden"
                  accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.mpp,.xml,.csv"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) void handleGanttUpload(f); }} />
              </label>
            </div>
          )}

          <div className="mt-3 space-y-2">
            {(crew?.people ?? []).length === 0 && (
              <p className="rounded-lg border border-dashed border-apple-border p-4 text-center text-xs italic text-apple-muted">
                No assignments for {day}. {canManage ? 'Use the form above to load the day.' : 'The construction admin assigns the crew.'}
              </p>
            )}
            {(crew?.people ?? []).map((person) => (
              <div key={person.person_name} className="rounded-lg border border-apple-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-apple-text">{person.person_name}</span>
                    <span className={'rounded-full px-2 py-0.5 text-[10px] font-bold ' + SHIFT_STYLE[person.status]}>
                      {person.status === 'over' ? 'OVER +' + person.over_hours + 'h' : person.status === 'full' ? 'FULL 8h' : person.status === 'partial' ? person.total_hours + 'h / 8h' : 'IDLE'}
                    </span>
                  </div>
                  <span className="text-[11px] text-apple-muted">
                    AM {person.am_hours}h · PM {person.pm_hours}h · total {person.total_hours}h
                  </span>
                </div>
                <div className="mt-2 flex gap-3">
                  <div className="flex-1">
                    <div className="mb-0.5 text-[9px] font-semibold uppercase text-apple-muted">AM 07–11</div>
                    <div className="h-2 rounded-full bg-apple-surface">
                      <div className={person.am_hours > 4 ? 'h-full rounded-full bg-red-500' : 'h-full rounded-full bg-blue-500'}
                        style={{ width: Math.min((person.am_hours / 4) * 100, 100) + '%' }} />
                    </div>
                  </div>
                  <div className="flex-1">
                    <div className="mb-0.5 text-[9px] font-semibold uppercase text-apple-muted">PM 12–16</div>
                    <div className="h-2 rounded-full bg-apple-surface">
                      <div className={person.pm_hours > 4 ? 'h-full rounded-full bg-red-500' : 'h-full rounded-full bg-indigo-500'}
                        style={{ width: Math.min((person.pm_hours / 4) * 100, 100) + '%' }} />
                    </div>
                  </div>
                </div>
                <ul className="mt-2 space-y-1">
                  {person.assignments.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-apple-surface/60 px-2 py-1 text-[11px]">
                      <span className="min-w-0">
                        <span className="font-mono font-semibold text-apple-muted">{a.pr_number}</span>{' '}
                        <span className="text-apple-text">{a.project_title?.slice(0, 46)}</span>{' '}
                        <span className="text-apple-muted">· {a.shift} {a.hours}h{a.task ? ' · ' + a.task : ''}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        {a.notified_at ? (
                          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">notified · {a.notify_channel}</span>
                        ) : (
                          <span className="rounded bg-apple-surface px-1.5 py-0.5 text-[10px] text-apple-muted">not notified</span>
                        )}
                        {canManage && (
                          <>
                            <button type="button" onClick={() => void handleNotify(a.id)}
                              className="rounded bg-primary px-1.5 py-0.5 text-[10px] font-semibold text-white">Notify</button>
                            <button type="button" onClick={() => void handleRemove(a.id)}
                              className="rounded border border-red-200 px-1.5 py-0.5 text-[10px] font-medium text-red-600">x</button>
                          </>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {(crew?.project_hours ?? []).length > 0 && (
            <div className="mt-3 rounded-lg bg-apple-surface/50 p-3">
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-apple-muted">
                Hours per project · {day}
              </div>
              <div className="flex flex-wrap gap-2 text-[11px]">
                {crew!.project_hours.map((ph) => (
                  <span key={ph.project_id} className="rounded-full bg-white px-2 py-0.5">
                    <span className="font-mono font-semibold">{ph.pr_number}</span> · {ph.hours}h
                  </span>
                ))}
              </div>
            </div>
          )}

          {!canManage && (
            <p className="mt-3 rounded-md border border-apple-border bg-apple-surface/60 px-3 py-2 text-[11px] italic text-apple-muted">
              Read-only view — assigning crew, notifying and uploading the Gantt chart are available to the construction admin.
            </p>
          )}
        </section>

        {live && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-9">
              {WINDOWS.map((w) => (
                <div key={w.key} className={'rounded-xl border p-3 ' + (w.key === 'later' ? 'border-apple-border bg-white' : w.accent)}>
                  <div className="flex items-center gap-1.5">
                    <span className={'h-2 w-2 rounded-full ' + w.dot} />
                    <span className="truncate text-[10px] font-semibold uppercase tracking-wide text-apple-muted">{w.label}</span>
                  </div>
                  <div className="mt-1 text-2xl font-bold tabular-nums text-apple-text">
                    {(visible[w.key] ?? []).length}
                  </div>
                </div>
              ))}
              <div className="rounded-xl border border-red-300 bg-red-50 p-3">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-red-700">Late / stopped</div>
                <div className="mt-1 text-2xl font-bold tabular-nums text-red-700">{live.risk.high}</div>
              </div>
              <div className="rounded-xl border border-purple-200 bg-purple-50 p-3">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-purple-700">Design gates</div>
                <div className="mt-1 text-2xl font-bold tabular-nums text-purple-700">{live.risk.design_blockers}</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-semibold uppercase tracking-wide text-apple-muted">Filter</span>
              <select value={phaseFilter} onChange={(e) => setPhaseFilter(e.target.value)}
                className="rounded-md border border-apple-border bg-white px-2 py-1 text-xs">
                <option value="">All divisions</option>
                <option value="Construction">Construction only</option>
                <option value="Design">Design (upstream)</option>
                <option value="EAR">EAR (upstream)</option>
              </select>
              <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}
                className="rounded-md border border-apple-border bg-white px-2 py-1 text-xs">
                <option value="">All priorities</option>
                <option value="Urgent">Urgent</option>
                <option value="Important">Important</option>
                <option value="Medium">Medium</option>
              </select>
              <span className="text-apple-muted">{live.total_scheduled} scheduled · {live.unscheduled} without a Planner date</span>
            </div>

            {live.design_blockers.length > 0 && (
              <section className="rounded-xl border-2 border-purple-300 bg-purple-50 p-4">
                <h2 className="text-sm font-bold text-purple-900">
                  Upstream gates — design, MTO & Procore approval
                </h2>
                <p className="mt-0.5 text-[11px] text-purple-700">
                  If these slip, the construction they feed slips too.
                </p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {live.design_blockers.slice(0, 6).map((it) => (
                    <Link key={it.id} href={'/projects/' + it.id}
                      className="rounded-lg border border-purple-200 bg-white p-3 transition hover:shadow-sm">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-mono text-xs font-semibold text-apple-muted">{it.pr_number}</span>
                        <span className="text-[11px] font-semibold text-purple-700">
                          {it.days_left !== null && it.days_left < 0 ? Math.abs(it.days_left) + 'd late' : it.days_left + 'd to gate'}
                        </span>
                      </div>
                      <p className="mt-0.5 truncate text-sm font-medium text-apple-text">{it.title}</p>
                      <p className="mt-0.5 text-[11px] text-apple-muted">
                        {it.bucket} → gate: {it.next_gate}
                        {it.required_hours_per_day !== null ? ' · ' + it.required_hours_per_day + ' h/day needed' : ''}
                      </p>
                    </Link>
                  ))}
                </div>
              </section>
            )}

            <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
              {WINDOWS.map((w) => {
                const rows = visible[w.key] ?? [];
                return (
                  <section key={w.key} className={'rounded-xl border p-3 ' + w.accent}>
                    <div className="mb-2 flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <span className={'h-2 w-2 rounded-full ' + w.dot} />
                        <h2 className="text-xs font-bold uppercase tracking-wide text-apple-text">{w.label}</h2>
                      </div>
                      <span className="rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-bold text-apple-text">{rows.length}</span>
                    </div>
                    {rows.length === 0 ? (
                      <p className="py-3 text-center text-[11px] italic text-apple-muted">Nothing in this window</p>
                    ) : (
                      <ul className="space-y-2">
                        {rows.map((it) => (
                          <li key={it.id}>
                            <Link href={'/projects/' + it.id}
                              className="block rounded-lg border border-apple-border bg-white p-3 transition hover:shadow-sm">
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <span className="font-mono text-[11px] font-semibold text-apple-muted">{it.pr_number}</span>
                                  <p className="truncate text-sm font-medium text-apple-text">{it.title}</p>
                                </div>
                                <span className={'shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-bold ' + RISK_STYLE[it.risk_level]}>
                                  {it.risk_level === 'high' ? 'LATE' : it.risk_level === 'medium' ? 'AT RISK' : 'OK'}
                                </span>
                              </div>
                              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px]">
                                {it.priority && (
                                  <span className={'rounded-full px-1.5 py-0.5 font-semibold ring-1 ring-inset ' + (PRIORITY_STYLES[it.priority.toLowerCase()] ?? 'bg-gray-100 text-gray-700 ring-gray-300')}>
                                    {it.priority}
                                  </span>
                                )}
                                <span className="rounded bg-apple-surface px-1.5 py-0.5 text-apple-muted">{it.bucket ?? it.phase}</span>
                                <span className="text-apple-muted">
                                  {it.finish_date}
                                  {it.days_left !== null ? (it.days_left < 0 ? ' · ' + Math.abs(it.days_left) + 'd late' : ' · ' + it.days_left + 'd left') : ''}
                                </span>
                              </div>
                              <div className="mt-1.5 flex items-center gap-2">
                                <div className="h-1.5 flex-1 rounded-full bg-apple-surface">
                                  <div className={it.risk_level === 'high' ? 'h-full rounded-full bg-red-500' : 'h-full rounded-full bg-emerald-500'}
                                    style={{ width: (it.completion_pct ?? 0) + '%' }} />
                                </div>
                                <span className="w-8 text-right text-[10px] tabular-nums text-apple-muted">{it.completion_pct ?? 0}%</span>
                              </div>
                              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-1 text-[10px] text-apple-muted">
                                <span>Gate: <strong className="text-apple-text">{it.next_gate}</strong></span>
                                {it.required_hours_per_day !== null && (
                                  <span>Needs <strong className="text-apple-text">{it.required_hours_per_day}</strong> h/day</span>
                                )}
                              </div>
                              <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px] text-apple-muted">
                                {it.location && <span>📍 {it.location}</span>}
                                {it.pi_name && <span>· PI: {it.pi_name}</span>}
                              </div>
                              {it.risks.length > 0 && (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {it.risks.map((r) => (
                                    <span key={r} className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700">{r}</span>
                                  ))}
                                </div>
                              )}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                );
              })}
            </div>

            {materials && (
              <section className="rounded-xl border border-apple-border bg-white p-4">
                <h2 className="mb-3 text-sm font-bold text-apple-text">Materials & permits (construction records)</h2>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                  {[
                    { label: 'Active construction', value: materials.active_construction_projects },
                    { label: 'Work permits', value: materials.active_work_permits },
                    { label: 'Materials tracked', value: materials.total_materials_tracked },
                    { label: 'Materials delivered', value: materials.materials_delivered },
                    { label: 'Delivery rate', value: Math.round((materials.delivery_rate ?? 0) * 100) + '%' },
                  ].map((k) => (
                    <div key={k.label} className="rounded-lg bg-apple-surface/60 p-3">
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-apple-muted">{k.label}</div>
                      <div className="mt-1 text-xl font-bold tabular-nums text-apple-text">{k.value}</div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <p className="pb-4 text-center text-[11px] text-apple-muted">
              Built for phones and tablets — open a project on site to record progress, permits and punch items.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
