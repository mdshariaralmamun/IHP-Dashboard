'use client';

import { useCallback, useEffect, useState } from 'react';
import ErrorBox from '@/components/ErrorBox';
import {
  addPunchItem,
  deletePunchItem,
  getCloseout,
  updatePunchItem,
} from '@/lib/api';
import type { PunchListItem, PunchListItemInput, User } from '@/lib/types';
import { canDo } from '@/lib/useUser';

const SEVERITIES: PunchListItem['severity'][] = ['minor', 'major', 'critical'];
const STATUSES: PunchListItem['status'][] = ['open', 'in_progress', 'resolved', 'verified'];

const STATUS_STYLES: Record<PunchListItem['status'], string> = {
  open: 'bg-red-100 text-red-700 ring-red-300',
  in_progress: 'bg-amber-100 text-amber-700 ring-amber-300',
  resolved: 'bg-green-100 text-green-700 ring-green-300',
  verified: 'bg-blue-100 text-blue-700 ring-blue-300',
};

const SEVERITY_STYLES: Record<PunchListItem['severity'], string> = {
  minor: 'bg-gray-100 text-gray-700 ring-gray-300',
  major: 'bg-orange-100 text-orange-700 ring-orange-300',
  critical: 'bg-red-100 text-red-700 ring-red-300',
};

const EMPTY_DRAFT: PunchListItemInput = {
  trade: '',
  description: '',
  location: '',
  severity: 'minor',
  assigned_to: '',
  due_date: '',
};

export default function PunchListPanel({
  projectId,
  currentUser,
  onChanged,
}: {
  projectId: number;
  currentUser: User | null;
  onChanged?: () => void;
}) {
  const [items, setItems] = useState<PunchListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState<PunchListItemInput>(EMPTY_DRAFT);

  const canManage = canDo(currentUser, 'closeout.manage');

  const load = useCallback(async () => {
    setError(null);
    try {
      const rec = await getCloseout(projectId);
      setItems(rec.punch_items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the punch list.');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await load();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed.');
    } finally {
      setBusy(null);
    }
  }

  async function handleAdd() {
    if (!draft.description.trim()) {
      setError('Punch item description is required.');
      return;
    }
    await run('add', () =>
      addPunchItem(projectId, {
        trade: draft.trade || 'General',
        description: draft.description,
        location: draft.location || undefined,
        severity: draft.severity,
        assigned_to: draft.assigned_to || null,
        due_date: draft.due_date || null,
      }),
    );
    setDraft(EMPTY_DRAFT);
  }

  const openCount = items.filter((p) => p.status === 'open' || p.status === 'in_progress').length;
  const doneCount = items.filter((p) => p.status === 'resolved' || p.status === 'verified').length;

  const inputCls =
    'w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text focus:border-primary focus:outline-none dark:bg-white/5';

  return (
    <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-bold text-apple-text">Punch List</h3>
          <p className="mt-0.5 text-xs text-apple-muted">
            Defects and outstanding work found after WCC/WCH. Clear every item to fully close the project.
          </p>
        </div>
        <div className="flex gap-2 text-xs font-semibold">
          <span className="rounded-full bg-red-50 px-3 py-1 text-red-700 ring-1 ring-red-200">Open: {openCount}</span>
          <span className="rounded-full bg-green-50 px-3 py-1 text-green-700 ring-1 ring-green-200">Cleared: {doneCount}</span>
          <span className="rounded-full bg-apple-surface px-3 py-1 text-apple-muted ring-1 ring-apple-border">Total: {items.length}</span>
        </div>
      </div>

      {error && <ErrorBox message={error} />}

      {canManage && (
        <div className="mb-5 rounded-lg border border-apple-border bg-apple-surface/60 p-4">
          <div className="grid gap-3 md:grid-cols-3">
            <input
              className={inputCls}
              placeholder="Trade (e.g. Electrical)"
              value={draft.trade ?? ''}
              onChange={(e) => setDraft({ ...draft, trade: e.target.value })}
            />
            <input
              className={inputCls}
              placeholder="Location (e.g. Bldg 3, Level 2)"
              value={draft.location ?? ''}
              onChange={(e) => setDraft({ ...draft, location: e.target.value })}
            />
            <select
              className={inputCls}
              value={draft.severity ?? 'minor'}
              onChange={(e) => setDraft({ ...draft, severity: e.target.value as PunchListItem['severity'] })}
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <input
              className={`${inputCls} md:col-span-2`}
              placeholder="Description of the defect / outstanding work *"
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
            <div className="grid grid-cols-2 gap-3">
              <input
                className={inputCls}
                placeholder="Assigned to"
                value={draft.assigned_to ?? ''}
                onChange={(e) => setDraft({ ...draft, assigned_to: e.target.value })}
              />
              <input
                type="date"
                className={inputCls}
                value={draft.due_date ?? ''}
                onChange={(e) => setDraft({ ...draft, due_date: e.target.value })}
              />
            </div>
          </div>
          <button
            type="button"
            disabled={busy === 'add'}
            onClick={() => void handleAdd()}
            className="mt-3 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {busy === 'add' ? 'Adding…' : '+ Add Punch Item'}
          </button>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-apple-muted">Loading punch list…</p>
      ) : items.length === 0 ? (
        <p className="rounded-md border border-dashed border-apple-border p-6 text-center text-sm text-apple-muted">
          No punch items yet. Everything found at handover goes here.
        </p>
      ) : (
        <ul className="space-y-3">
          {items.map((p) => (
            <li key={p.id} className="rounded-lg border border-apple-border p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${STATUS_STYLES[p.status] ?? ''}`}>
                      {p.status.replace(/_/g, ' ')}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${SEVERITY_STYLES[p.severity] ?? ''}`}>
                      {p.severity}
                    </span>
                    <span className="rounded-full bg-apple-surface px-2 py-0.5 text-xs text-apple-muted ring-1 ring-apple-border">
                      {p.trade}
                    </span>
                    {p.location && (
                      <span className="text-xs text-apple-muted">📍 {p.location}</span>
                    )}
                    {p.due_date && (
                      <span className="text-xs text-apple-muted">Due {new Date(p.due_date).toLocaleDateString()}</span>
                    )}
                  </div>
                  <p className="text-sm font-medium text-apple-text">{p.description}</p>
                  {p.assigned_to && (
                    <p className="mt-1 text-xs text-apple-muted">Assigned to: {p.assigned_to}</p>
                  )}
                </div>
                {canManage && (
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs text-apple-text focus:outline-none dark:bg-white/5"
                      value={p.status}
                      disabled={busy === `status-${p.id}`}
                      onChange={(e) =>
                        void run(`status-${p.id}`, () =>
                          updatePunchItem(projectId, p.id, { status: e.target.value as PunchListItem['status'] }),
                        )
                      }
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm('Delete this punch item?'))
                          void run(`del-${p.id}`, () => deletePunchItem(projectId, p.id));
                      }}
                      className="rounded-md border border-red-200 px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
