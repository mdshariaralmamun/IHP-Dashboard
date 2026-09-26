'use client';

import { useState } from 'react';
import ErrorBox from '@/components/ErrorBox';
import { recordWorkPermit, updateConstruction } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { canDo } from '@/lib/useUser';
import type { ConstructionOut, ProjectDetail, User } from '@/lib/types';

const STATUS_OPTIONS = ['planned', 'in_progress', 'completed', 'on_hold'];

export default function ConstructionPanel({
  project,
  currentUser,
  onChanged,
}: {
  project: ProjectDetail;
  currentUser: User | null;
  onChanged: () => void;
}) {
  const canManage = canDo(currentUser, 'construction.manage');
  const canPermit = canDo(currentUser, 'work_permit.manage');
  const isIcr = project.disposition === 'ICR';

  const construction: ConstructionOut | null = project.construction ?? null;
  const [status, setStatus] = useState(construction?.status ?? 'planned');
  const [wcfRef, setWcfRef] = useState('');
  const [wcfNotes, setWcfNotes] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  if (isIcr) {
    return (
      <section className="p-4 border rounded border-apple-surface text-apple-text">
        <p className="text-sm text-apple-muted">
          This project is ICR-classified and does not go through construction.
          MTO and hand-off milestones are tracked in the ICR panel.
        </p>
      </section>
    );
  }

  async function run<T>(key: string, action: () => Promise<T>): Promise<T | undefined> {
    if (busy) return undefined;
    setBusy(key);
    setError(null);
    setInfo(null);
    try {
      const result = await action();
      onChanged();
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed.');
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  async function handleStatusChange() {
    await run(`status-${status}`, () => updateConstruction(project.id, { status }));
  }

  async function handleFilePermit() {
    if (!canPermit) return;
    const existingWcf = (construction?.wcf_data ?? {}) as Record<string, unknown>;
    const next: Record<string, unknown> = {
      ...existingWcf,
      permit_number: wcfRef || (existingWcf.permit_number as string) || '',
      notes: wcfNotes || (existingWcf.notes as string) || '',
    };
    await run('work-permit', () => recordWorkPermit(project.id, next));
    setInfo('Work permit recorded.');
  }

  const wcf = (construction?.wcf_data ?? {}) as Record<string, unknown>;

  return (
    <section className="p-4 border rounded border-apple-surface text-apple-text">
      <p className="text-xs font-medium uppercase tracking-wider text-apple-muted/60 mb-2">
        Construction Execution
      </p>

      {error && (
        <div className="mb-2">
          <ErrorBox message={error} />
        </div>
      )}
      {info && (
        <div className="mb-2 rounded-sm border border-apple-surface/50 bg-apple-surface/50 px-2 py-1 text-xs text-apple-text">
          {info}
        </div>
      )}

      {construction && (
        <div className="mb-3 grid grid-cols-1 gap-2">
          <div className="rounded-sm border border-apple-surface/50 px-2 py-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-apple-muted/60">Status</span>
            <p className="mt-0.5 text-sm font-medium text-apple-text">{construction.status}</p>
          </div>
          {construction.started_at && (
            <div className="rounded-sm border border-apple-surface/50 px-2 py-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-apple-muted/60">Started</span>
              <p className="mt-0.5 text-sm font-medium text-apple-text">
                {formatDateTime(construction.started_at)}
              </p>
            </div>
          )}
          {construction.completed_at && (
            <div className="rounded-sm border border-apple-surface/50 px-2 py-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-apple-muted/60">Completed</span>
              <p className="mt-0.5 text-sm font-medium text-apple-text">
                {formatDateTime(construction.completed_at)}
              </p>
            </div>
          )}
        </div>
      )}

      {canPermit && (
        <div className="mb-3 rounded-sm border border-amber-200 bg-amber-50/50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-amber-700/80 mb-1">
            Work permit / WCF
          </p>
          <div className="grid grid-cols-1 gap-2">
            <input
              type="text"
              value={wcfRef}
              onChange={(e) => setWcfRef(e.target.value)}
              placeholder={(wcf.permit_number as string) || 'WCF permit number'}
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            />
            <input
              type="text"
              value={wcfNotes}
              onChange={(e) => setWcfNotes(e.target.value)}
              placeholder="Filing notes (optional)"
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            />
          </div>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={handleFilePermit}
              disabled={busy !== null}
              className="rounded-sm bg-amber-600 px-2 py-1 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
            >
              {busy === 'work-permit' ? 'Filing…' : 'Record work permit'}
            </button>
            {(wcf.filed_at as string) && (
              <span className="text-xs text-apple-muted">
                Last filed {String(wcf.filed_at)}
              </span>
            )}
          </div>
        </div>
      )}

      {wcf && Object.keys(wcf).length > 0 && (
        <div className="mb-3 rounded-sm border border-apple-surface/50 bg-apple-surface/50 p-2 text-xs">
          <strong>WCF data:</strong> {JSON.stringify(wcf, null, 2).substring(0, 200)}...
        </div>
      )}

      {construction?.schedule_data && Object.keys(construction.schedule_data).length > 0 && (
        <div className="mb-3 rounded-sm border border-apple-surface/50 bg-apple-surface/50 p-2 text-xs">
          <strong>Schedule data:</strong> present
        </div>
      )}

      <p className="text-xs text-apple-muted/60">
        Construction tracking is aggregated on the dashboard.
      </p>
    </section>
  );
}