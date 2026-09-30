'use client';

import { useState } from 'react';
import ErrorBox from '@/components/ErrorBox';
import {
  addPunchItem,
  deletePunchItem,
  startPunchList,
  updateCloseout,
  updatePunchItem,
} from '@/lib/api';
import { formatDate, formatDateTime } from '@/lib/format';
import { canDo } from '@/lib/useUser';
import type {
  CloseoutRecord,
  ProjectDetail,
  PunchListItem,
  PunchListItemInput,
  User,
} from '@/lib/types';

const STATUS_OPTIONS = ['open', 'in_progress', 'punch_list_review', 'completed', 'signed_off'];
const SEVERITY_OPTIONS = ['minor', 'major', 'critical'];

export default function CloseoutPanel({
  projectId,
  project,
  currentUser,
  onChanged,
}: {
  projectId: number;
  project: ProjectDetail;
  currentUser: User | null;
  onChanged: () => void;
}) {
  const canManage = canDo(currentUser, 'closeout.manage');
  const isIcr = project.disposition === 'ICR';

  const closeout: CloseoutRecord | null = project.closeout ?? null;
  const punchItems: PunchListItem[] = closeout?.punch_items ?? [];

  const [tcNotes, setTcNotes] = useState(closeout?.testing_commissioning_notes ?? '');
  const [asBuilt, setAsBuilt] = useState(closeout?.as_built_drawings_submitted ?? false);
  const [omManuals, setOmManuals] = useState(closeout?.o_and_m_manuals_submitted ?? false);
  const [warrantyProvider, setWarrantyProvider] = useState(closeout?.warranty_provider ?? '');
  const [warrantyNotes, setWarrantyNotes] = useState(closeout?.warranty_notes ?? '');
  const [clientSignoffBy, setClientSignoffBy] = useState(closeout?.client_signoff_by ?? '');
  const [clientFeedback, setClientFeedback] = useState(closeout?.client_feedback ?? '');
  const [status, setStatus] = useState(closeout?.status ?? 'open');

  const [punchDraft, setPunchDraft] = useState<PunchListItemInput>({
    trade: 'civil_arch',
    description: '',
    location: '',
    severity: 'minor',
    assigned_to: '',
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  if (isIcr) {
    return (
      <section className="p-4 border rounded border-apple-surface text-apple-text">
        <p className="text-sm text-apple-muted">
          ICR-classified projects end at the ICR hand-off stage. There is no
          construction closeout record for them.
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

  async function handleSave() {
    await run('save', () =>
      updateCloseout(projectId, {
        status,
        testing_commissioning_notes: tcNotes,
        as_built_drawings_submitted: asBuilt,
        o_and_m_manuals_submitted: omManuals,
        warranty_provider: warrantyProvider || null,
        warranty_notes: warrantyNotes || null,
        client_signoff_by: clientSignoffBy || null,
        client_feedback: clientFeedback || null,
      }),
    );
    setInfo('Closeout saved.');
  }

  async function handleAddPunch() {
    if (!punchDraft.description.trim()) {
      setError('Punch item description is required.');
      return;
    }
    await run('punch-add', () =>
      addPunchItem(projectId, {
        trade: punchDraft.trade,
        description: punchDraft.description,
        location: punchDraft.location || undefined,
        severity: punchDraft.severity,
        assigned_to: punchDraft.assigned_to || null,
      }),
    );
    setPunchDraft({
      trade: 'civil_arch',
      description: '',
      location: '',
      severity: 'minor',
      assigned_to: '',
    });
  }

  async function handlePunchStatus(item: PunchListItem, newStatus: PunchListItem['status']) {
    await run(`punch-status-${item.id}`, () =>
      updatePunchItem(projectId, item.id, { status: newStatus }),
    );
  }

  async function handleDeletePunch(item: PunchListItem) {
    if (!window.confirm('Delete this punch item?')) return;
    await run(`punch-delete-${item.id}`, () => deletePunchItem(projectId, item.id));
  }

  const openPunch = punchItems.filter((p) => p.status !== 'verified').length;
  const totalPunch = punchItems.length;

  return (
    <section className="p-4 border rounded border-apple-surface text-apple-text space-y-3">
      <p className="text-xs font-medium uppercase tracking-wider text-apple-muted mb-2">
        Project Closeout & Handover
      </p>
      <p className="text-sm text-apple-muted">
        T&C notes, as-builts and O&M submission, warranty terms, and
        the punch list of defects. Sign-off marks the project complete.
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

      {project.stage === 'CLOSEOUT' && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-orange-200 bg-orange-50 p-3">
          <p className="text-xs text-orange-800">
            WCC/WCH done? Move this project to the <strong>Punch List</strong> stage to track handover defects.
          </p>
          <button
            type="button"
            disabled={busy === 'start-punch'}
            onClick={() =>
              run('start-punch', async () => {
                await startPunchList(projectId);
                setInfo('Project moved to Punch List stage.');
              })
            }
            className="rounded-md bg-orange-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-orange-700 disabled:opacity-50"
          >
            {busy === 'start-punch' ? 'Moving…' : 'Start Punch List →'}
          </button>
        </div>
      )}

      {canManage && (
        <div className="mb-3 grid grid-cols-1 gap-2">
          <div>
            <label className="block text-xs font-medium text-apple-muted">Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-apple-muted">
              Warranty provider
            </label>
            <input
              type="text"
              value={warrantyProvider}
              onChange={(e) => setWarrantyProvider(e.target.value)}
              placeholder="e.g. Schneider Electric"
              className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-apple-muted">
              T&C notes
            </label>
            <textarea
              rows={3}
              value={tcNotes}
              onChange={(e) => setTcNotes(e.target.value)}
              placeholder="Equipment T&C results, performance verification, sign-offs…"
              className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={asBuilt}
                onChange={(e) => setAsBuilt(e.target.checked)}
              />
              As-built drawings submitted
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={omManuals}
                onChange={(e) => setOmManuals(e.target.checked)}
              />
              O&M manuals submitted
            </label>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-apple-muted">
                Client signoff (by)
              </label>
              <input
                type="text"
                value={clientSignoffBy}
                onChange={(e) => setClientSignoffBy(e.target.value)}
                placeholder="PI / end-user name"
                className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-apple-muted">
                Client feedback (optional)
              </label>
              <input
                type="text"
                value={clientFeedback}
                onChange={(e) => setClientFeedback(e.target.value)}
                placeholder="Comments, satisfaction note"
                className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
              />
            </div>
          </div>
          <div>
            <button
              type="button"
              onClick={handleSave}
              disabled={busy !== null}
              className="rounded-sm bg-primary px-2 py-1 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {busy === 'save' ? 'Saving…' : 'Save closeout'}
            </button>
          </div>
        </div>
      )}

      {/* Punch list */}
      {canManage && (
        <div className="mt-3">
          <p className="text-xs font-medium uppercase tracking-wider text-apple-muted mb-1">
            Punch list
          </p>
          {punchItems.length === 0 ? (
            <p className="text-sm text-apple-muted">
              No punch items yet. Add T&C defects here as they surface.
            </p>
          ) : (
            <ul className="text-sm text-apple-text space-y-1">
              {punchItems.map((p) => (
                <li key={p.id} className="border-b border-apple-border/20 py-1">
                  <span className="font-medium text-apple-text">{p.trade}</span>
                  <span>{p.description}</span>
                  {p.location && (
                    <span className="text-xs text-apple-muted">@ {p.location}</span>
                  )}
                  {p.assigned_to && (
                    <span className="text-xs text-apple-muted">→ {p.assigned_to}</span>
                  )}
                  {p.due_date && (
                    <span className="text-xs text-apple-muted">
                      due {formatDate(p.due_date)}
                    </span>
                  )}
                  {p.resolved_at && (
                    <span className="text-xs text-emerald-600">
                      resolved {formatDateTime(p.resolved_at)}
                    </span>
                  )}
                  {canManage && (
                    <>
                      {p.status !== 'resolved' && (
                        <button
                          type="button"
                          onClick={() => handlePunchStatus(p, 'resolved')}
                          className="rounded-sm border border-emerald-300 px-1 py-0.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                        >
                          Resolve
                        </button>
                      )}
                      {p.status !== 'verified' && (
                        <button
                          type="button"
                          onClick={() => handlePunchStatus(p, 'verified')}
                          className="rounded-sm border border-apple-border px-1 py-0.5 text-xs font-medium text-apple-text hover:bg-apple-surface/50 disabled:opacity-50"
                        >
                          Verify
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void handleDeletePunch(p)}
                        className="rounded-sm px-1 py-0.5 text-xs font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
                      >
                        Delete
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}