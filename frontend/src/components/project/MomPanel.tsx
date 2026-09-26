'use client';

import { useEffect, useRef, useState } from 'react';
import { renderAsync } from 'docx-preview';
import ErrorBox from '@/components/ErrorBox';
import MomStatusBadge from '@/components/MomStatusBadge';
import { ApiError, addMomAgendaItem, deleteMomAgendaItem, downloadMom, generateMom, getMomDefaults, getMomDocxBlob, setMomStatus, updateMomAgendaItem } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { canDo } from '@/lib/useUser';
import { TRADE_OPTIONS as USER_TRADE_OPTIONS } from '@/lib/types';
import type { MomAgendaItem, MomAttendee, MomRecord, MomStatusUpdate, User } from '@/lib/types';

const inputClass =
  'mt-1 block w-full rounded-md border border-apple-border px-2.5 py-1.5 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary';

const secondaryButton =
  'rounded-md border border-apple-border bg-apple-surface px-3 py-1.5 text-sm font-medium text-apple-text hover:bg-apple-surface disabled:cursor-not-allowed disabled:opacity-50';

interface MeetingFields {
  meeting_title: string;
  meeting_location: string;
  meeting_number: string;
  meeting_date: string;
  meeting_time: string;
}

const EMPTY_MEETING: MeetingFields = {
  meeting_title: '',
  meeting_location: '',
  meeting_number: '',
  meeting_date: '',
  meeting_time: '',
};

const TRADE_OPTIONS = ['Civil/Architectural', 'Electrical', 'Plumbing', 'HVAC'];

// RBAC trade code -> agenda trade label (mirrors the backend mapping).
const AGENDA_TRADE_LABELS: Record<string, string> = {
  civil_arch: 'Civil/Architectural',
  electrical: 'Electrical',
  low_current: 'Low Current',
  plumbing: 'Plumbing',
  fire_protection: 'Fire Protection',
  hvac: 'HVAC',
  macc: 'MACC',
};

/** Agenda label for any trade code, including custom free-text trades. */
function agendaTradeLabel(trade: string): string {
  if (AGENDA_TRADE_LABELS[trade]) return AGENDA_TRADE_LABELS[trade];
  return trade
    .split('_')
    .map((word) => (word.length <= 3 ? word.toUpperCase() : word[0].toUpperCase() + word.slice(1)))
    .join(' ');
}

export default function MomPanel({
  projectId,
  mom,
  currentUser,
  onChanged,
}: {
  projectId: number;
  mom: MomRecord | null;
  currentUser: User | null;
  onChanged: () => void;
}) {
  const canManageMom = canDo(currentUser, 'mom.manage');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [disputeNote, setDisputeNote] = useState('');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [meeting, setMeeting] = useState<MeetingFields>(EMPTY_MEETING);
  const [attendees, setAttendees] = useState<MomAttendee[]>([]);
  const [agenda, setAgenda] = useState<MomAgendaItem[]>([]);
  const [detailsLoaded, setDetailsLoaded] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewBlob, setPreviewBlob] = useState<Blob | null>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const [newItem, setNewItem] = useState({ scope: '', action: '', etc: '' });

  const canAddAgenda = canDo(currentUser, 'mom.agenda') && !!currentUser?.trade;
  const tradeLabel = currentUser?.trade
    ? (USER_TRADE_OPTIONS.find((t) => t.value === currentUser.trade)?.label ?? currentUser.trade)
    : null;
  const ownAgendaTrade = currentUser?.trade ? agendaTradeLabel(currentUser.trade) : null;
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState({ scope: '', action: '', etc: '' });

  // Stale after every regeneration: force a refetch on the next preview.
  useEffect(() => {
    setPreviewBlob(null);
  }, [mom?.version]);

  useEffect(() => {
    if (!previewOpen || !previewBlob || !previewRef.current) return;
    const container = previewRef.current;
    container.innerHTML = '';
    renderAsync(previewBlob, container).catch(() => {
      setError('Could not render the MOM preview — download the DOCX instead.');
    });
  }, [previewOpen, previewBlob]);

  function handleAddAgendaItem() {
    if (!newItem.scope.trim()) {
      setError('Enter the scope text for your trade item.');
      return;
    }
    void run('agenda-add', async () => {
      await addMomAgendaItem(projectId, {
        scope: newItem.scope,
        action: newItem.action,
        etc: newItem.etc,
      });
      setNewItem({ scope: '', action: '', etc: '' });
    });
  }

  function handleStartEdit(index: number, item: MomAgendaItem) {
    setEditingIndex(index);
    setEditDraft({ scope: item.scope, action: item.action, etc: item.etc });
  }

  function handleSaveEdit(index: number) {
    if (!editDraft.scope.trim()) {
      setError('Scope text is required.');
      return;
    }
    void run(`agenda-edit-${index}`, async () => {
      await updateMomAgendaItem(projectId, index, editDraft);
      setEditingIndex(null);
    });
  }

  function handleDeleteItem(index: number) {
    if (!window.confirm('Delete this agenda item?')) return;
    void run(`agenda-delete-${index}`, () => deleteMomAgendaItem(projectId, index));
  }

  function handlePreviewToggle() {
    if (previewOpen) {
      setPreviewOpen(false);
      return;
    }
    setPreviewOpen(true);
    if (!previewBlob) {
      void run('preview', async () => setPreviewBlob(await getMomDocxBlob(projectId)));
    }
  }

  // Auto-fill: when the project has no MOM yet, seed the KAUST meeting
  // fields from the project itself (PR + name, location incl. O&M details,
  // meeting number, today's date). Values stay editable.
  const [autoFilled, setAutoFilled] = useState(false);
  useEffect(() => {
    if (detailsLoaded || mom?.details) return;
    let cancelled = false;
    void (async () => {
      try {
        const d = await getMomDefaults(projectId);
        if (cancelled) return;
        setMeeting((prev) => ({
          meeting_title: prev.meeting_title || d.meeting_title,
          meeting_location: prev.meeting_location || d.meeting_location,
          meeting_number: prev.meeting_number || d.meeting_number,
          meeting_date: prev.meeting_date || d.meeting_date,
          meeting_time: prev.meeting_time || d.meeting_time,
        }));
        setAutoFilled(true);
        setDetailsLoaded(true);
      } catch {
        if (!cancelled) setDetailsLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, mom, detailsLoaded]);

  /** Re-apply the project data over the current fields (admin convenience). */
  async function reapplyProjectData() {
    try {
      const d = await getMomDefaults(projectId);
      setMeeting({
        meeting_title: d.meeting_title,
        meeting_location: d.meeting_location,
        meeting_number: d.meeting_number,
        meeting_date: d.meeting_date,
        meeting_time: d.meeting_time,
      });
      setAutoFilled(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read the project defaults.');
    }
  }

  // Prefill the editor from the stored MOM details once they arrive.
  useEffect(() => {
    if (detailsLoaded || !mom?.details) return;
    const d = mom.details;
    setMeeting({
      meeting_title: d.meeting_title ?? '',
      meeting_location: d.meeting_location ?? '',
      meeting_number: d.meeting_number ?? '',
      meeting_date: d.meeting_date ?? '',
      meeting_time: d.meeting_time ?? '',
    });
    setAttendees(d.attendees ?? []);
    setAgenda(d.agenda ?? []);
    setDetailsLoaded(true);
  }, [mom, detailsLoaded]);

  async function run(actionKey: string, action: () => Promise<unknown>) {
    if (busy) return;
    setError(null);
    setBusy(actionKey);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed.');
    } finally {
      setBusy(null);
    }
  }

  function handleGenerate() {
    const payload = {
      meeting_title: meeting.meeting_title.trim() || null,
      meeting_location: meeting.meeting_location.trim() || null,
      meeting_number: meeting.meeting_number.trim() || null,
      meeting_date: meeting.meeting_date.trim() || null,
      meeting_time: meeting.meeting_time.trim() || null,
      attendees: attendees.filter((a) => a.name.trim() || a.title.trim() || a.email.trim()),
      agenda: agenda
        .filter(
          (a) =>
            a.scope.trim() || a.action.trim() || a.etc.trim() || (a.trade ?? '').trim(),
        )
        .map((a) => ({ ...a, trade: (a.trade ?? '').trim() || null })),
    };
    void run('generate', () => generateMom(projectId, payload));
  }

  function handleDownload(fmt: 'docx' | 'pdf') {
    void run(`download-${fmt}`, async () => {
      try {
        await downloadMom(projectId, fmt);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404 && fmt === 'pdf') {
          throw new ApiError(404, 'PDF export is not available for this MOM yet.');
        }
        throw err;
      }
    });
  }

  function handleStatus(status: MomStatusUpdate, note?: string) {
    void run(`status-${status}`, () => setMomStatus(projectId, status, note));
  }

  function submitDispute() {
    const note = disputeNote.trim();
    if (!note) {
      setError('A note is required when marking the MOM as disputed.');
      return;
    }
    setDisputeOpen(false);
    setDisputeNote('');
    handleStatus('disputed', note);
  }

  function updateMeeting(field: keyof MeetingFields) {
    return (e: React.ChangeEvent<HTMLInputElement>) =>
      setMeeting((prev) => ({ ...prev, [field]: e.target.value }));
  }

  function updateAttendee(index: number, field: keyof MomAttendee, value: string) {
    setAttendees((prev) =>
      prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    );
  }

  function updateAgenda(index: number, field: keyof MomAgendaItem, value: string | null) {
    setAgenda((prev) => prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }

  const meetingInputs: { field: keyof MeetingFields; label: string; placeholder: string }[] = [
    { field: 'meeting_title', label: 'Meeting Title', placeholder: 'e.g. PR-12623 kickoff' },
    { field: 'meeting_location', label: 'Meeting Location', placeholder: 'e.g. Bldg 5, Level 3' },
    { field: 'meeting_number', label: 'Meeting Number', placeholder: 'e.g. 01' },
    { field: 'meeting_date', label: 'Date', placeholder: 'e.g. 2026-09-10' },
    { field: 'meeting_time', label: 'Time', placeholder: 'e.g. 10:00' },
  ];

  return (
    <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-apple-muted">
          Minutes of Meeting (MOM)
        </h2>
        {canManageMom && (
          <button
            type="button"
            onClick={handleGenerate}
            disabled={busy !== null}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-apple-surface disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === 'generate'
              ? 'Generating…'
              : mom
                ? 'Regenerate MOM'
                : 'Generate MOM'}
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {canManageMom && (
        <div className="mb-4 rounded-md border border-apple-border">
          <button
            type="button"
            onClick={() => setDetailsOpen((open) => !open)}
            className="flex w-full items-center justify-between px-4 py-2 text-xs font-semibold uppercase tracking-wide text-apple-muted hover:bg-apple-surface/50"
          >
            <span>Meeting details (KAUST template)</span>
            <span>{detailsOpen ? '▲' : '▼'}</span>
          </button>
          {detailsOpen && (
            <div className="space-y-4 border-t border-apple-border px-4 py-3">
              {autoFilled && (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2">
                  <span className="text-[11px] text-emerald-800">
                    Auto-filled from this project (PR number, name &amp; location). Edit any
                    field, or re-apply the project data.
                  </span>
                  <button
                    type="button"
                    onClick={() => void reapplyProjectData()}
                    className="rounded border border-emerald-300 bg-white px-2 py-1 text-[11px] font-medium text-emerald-700 hover:bg-emerald-100"
                  >
                    ↺ Re-apply project data
                  </button>
                </div>
              )}
              <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
                {meetingInputs.map(({ field, label, placeholder }) => (
                  <div key={field}>
                    <label className="block text-xs font-medium text-apple-muted">{label}</label>
                    <input
                      type="text"
                      value={meeting[field]}
                      onChange={updateMeeting(field)}
                      placeholder={placeholder}
                      className={inputClass}
                    />
                  </div>
                ))}
              </div>

              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-medium text-apple-muted">Attendees</span>
                  <button
                    type="button"
                    onClick={() => setAttendees((prev) => [...prev, { name: '', title: '', email: '' }])}
                    className="text-xs font-medium text-apple-text underline"
                  >
                    + Add attendee
                  </button>
                </div>
                {attendees.length === 0 ? (
                  <p className="text-xs text-apple-muted">
                    Empty — defaults to the requester/PI when generating.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {attendees.map((row, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <input
                          type="text"
                          value={row.name}
                          onChange={(e) => updateAttendee(i, 'name', e.target.value)}
                          placeholder="Name"
                          className={inputClass}
                        />
                        <input
                          type="text"
                          value={row.title}
                          onChange={(e) => updateAttendee(i, 'title', e.target.value)}
                          placeholder="Title"
                          className={inputClass}
                        />
                        <input
                          type="text"
                          value={row.email}
                          onChange={(e) => updateAttendee(i, 'email', e.target.value)}
                          placeholder="Email"
                          className={inputClass}
                        />
                        <button
                          type="button"
                          onClick={() => setAttendees((prev) => prev.filter((_, j) => j !== i))}
                          className="shrink-0 text-sm text-red-600 hover:text-red-800"
                          title="Remove"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-medium text-apple-muted">
                    Agenda / Preliminary Scope of Work
                  </span>
                  <button
                    type="button"
                    onClick={() => setAgenda((prev) => [...prev, { scope: '', action: '', etc: '' }])}
                    className="text-xs font-medium text-apple-text underline"
                  >
                    + Add item
                  </button>
                </div>
                {agenda.length === 0 ? (
                  <p className="text-xs text-apple-muted">
                    Empty — defaults to the PR description when generating.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {agenda.map((row, i) => {
                      const isCustomTrade = !!row.trade && !TRADE_OPTIONS.includes(row.trade);
                      return (
                        <div key={i} className="flex items-center gap-2">
                          <span className="w-5 shrink-0 text-xs text-apple-muted">{i + 1}</span>
                          <select
                            value={
                              !row.trade ? '' : TRADE_OPTIONS.includes(row.trade) ? row.trade : '__other'
                            }
                            onChange={(e) => {
                              const v = e.target.value;
                              updateAgenda(i, 'trade', v === '' ? null : v === '__other' ? 'Other' : v);
                            }}
                            className={`${inputClass} sm:max-w-36`}
                            title="Trade"
                          >
                            <option value="">Trade…</option>
                            {TRADE_OPTIONS.map((t) => (
                              <option key={t} value={t}>
                                {t}
                              </option>
                            ))}
                            <option value="__other">Others…</option>
                          </select>
                          {isCustomTrade && (
                            <input
                              type="text"
                              value={row.trade ?? ''}
                              onChange={(e) => updateAgenda(i, 'trade', e.target.value)}
                              placeholder="Custom trade"
                              className={`${inputClass} sm:max-w-32`}
                            />
                          )}
                          <input
                            type="text"
                            value={row.scope}
                            onChange={(e) => updateAgenda(i, 'scope', e.target.value)}
                            placeholder="Scope / task description"
                            className={inputClass}
                          />
                          <input
                            type="text"
                            value={row.action}
                            onChange={(e) => updateAgenda(i, 'action', e.target.value)}
                            placeholder="Action by"
                            className={`${inputClass} sm:max-w-32`}
                          />
                          <input
                            type="text"
                            value={row.etc}
                            onChange={(e) => updateAgenda(i, 'etc', e.target.value)}
                            placeholder="ETC"
                            className={`${inputClass} sm:max-w-28`}
                          />
                          <button
                            type="button"
                            onClick={() => setAgenda((prev) => prev.filter((_, j) => j !== i))}
                            className="shrink-0 text-sm text-red-600 hover:text-red-800"
                            title="Remove"
                          >
                            ✕
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <p className="text-xs text-apple-muted">
                Applied on the next Generate/Regenerate. Blank fields fall back to project
                defaults. Revision No. and Document Code are assigned automatically.
              </p>
            </div>
          )}
        </div>
      )}

      {canAddAgenda && mom && (
        <div className="mb-4 rounded-md border border-apple-border px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
              Add scope item — your trade
            </span>
            {tradeLabel && (
              <span className="rounded-full bg-apple-surface px-2.5 py-0.5 text-xs font-medium text-apple-muted">
                {tradeLabel}
              </span>
            )}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={newItem.scope}
              onChange={(e) => setNewItem((prev) => ({ ...prev, scope: e.target.value }))}
              placeholder="Scope / task description"
              className={inputClass}
            />
            <input
              type="text"
              value={newItem.action}
              onChange={(e) => setNewItem((prev) => ({ ...prev, action: e.target.value }))}
              placeholder="Action by"
              className={`${inputClass} sm:max-w-32`}
            />
            <input
              type="text"
              value={newItem.etc}
              onChange={(e) => setNewItem((prev) => ({ ...prev, etc: e.target.value }))}
              placeholder="ETC"
              className={`${inputClass} sm:max-w-28`}
            />
            <button
              type="button"
              onClick={handleAddAgendaItem}
              disabled={busy !== null}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-apple-surface disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy === 'agenda-add' ? 'Adding…' : 'Add'}
            </button>
          </div>
          {(mom.details?.agenda?.length ?? 0) > 0 && (
            <ul className="mt-3 space-y-2 border-t border-apple-border pt-3">
              {mom.details!.agenda!.map((item, i) => {
                const own = ownAgendaTrade !== null && item.trade === ownAgendaTrade;
                if (editingIndex === i) {
                  return (
                    <li key={i} className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-apple-muted">{i + 1}.</span>
                      <input
                        type="text"
                        value={editDraft.scope}
                        onChange={(e) => setEditDraft((p) => ({ ...p, scope: e.target.value }))}
                        className={inputClass}
                      />
                      <input
                        type="text"
                        value={editDraft.action}
                        onChange={(e) => setEditDraft((p) => ({ ...p, action: e.target.value }))}
                        placeholder="Action by"
                        className={`${inputClass} sm:max-w-28`}
                      />
                      <input
                        type="text"
                        value={editDraft.etc}
                        onChange={(e) => setEditDraft((p) => ({ ...p, etc: e.target.value }))}
                        placeholder="ETC"
                        className={`${inputClass} sm:max-w-24`}
                      />
                      <button
                        type="button"
                        onClick={() => handleSaveEdit(i)}
                        disabled={busy !== null}
                        className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-white hover:bg-apple-surface disabled:opacity-50"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingIndex(null)}
                        className="text-xs text-apple-muted underline"
                      >
                        Cancel
                      </button>
                    </li>
                  );
                }
                return (
                  <li key={i} className="flex flex-wrap items-baseline gap-2 text-xs text-apple-muted">
                    <span className="text-apple-muted">{i + 1}.</span>
                    {item.trade && (
                      <span className="rounded bg-apple-surface px-1.5 py-0.5 text-apple-muted">
                        {item.trade}
                      </span>
                    )}
                    <span>{item.scope}</span>
                    {own && (
                      <span className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleStartEdit(i, item)}
                          disabled={busy !== null}
                          className="font-medium text-apple-text underline disabled:opacity-50"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteItem(i)}
                          disabled={busy !== null}
                          className="font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
                        >
                          Delete
                        </button>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          <p className="mt-2 text-xs text-apple-muted">
            Items appear in the document on the next MOM regeneration.
          </p>
        </div>
      )}

      {!mom ? (
        <p className="text-sm text-apple-muted">
          No MOM generated yet.
          {canManageMom
            ? ' Use “Generate MOM” to draft the minutes and the notification email.'
            : ' An administrator can generate it.'}
        </p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm text-apple-muted">
            <span className="font-medium text-apple-text">Version {mom.version}</span>
            <MomStatusBadge status={mom.status} />
            <span className="text-xs text-apple-muted">
              Updated {formatDateTime(mom.updated_at)}
            </span>
          </div>

          <div className="rounded-md border border-apple-border bg-apple-surface/50">
            <div className="border-b border-apple-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-apple-muted">
              Email draft
            </div>
            <div className="px-4 py-3">
              <p className="text-sm font-semibold text-apple-text">{mom.email_subject}</p>
              <pre className="mt-2 whitespace-pre-wrap font-sans text-sm text-apple-text">
                {mom.email_body}
              </pre>
            </div>
          </div>

          {mom.note && (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              <span className="font-semibold">Dispute note: </span>
              {mom.note}
            </div>
          )}

          {previewOpen && (
            <div className="rounded-md border border-apple-border bg-apple-border p-4">
              {busy === 'preview' && (
                <p className="py-8 text-center text-sm text-apple-muted">Loading preview…</p>
              )}
              <div
                ref={previewRef}
                className="max-h-[70vh] overflow-auto [&_.docx-wrapper]:bg-transparent"
              />
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-apple-border pt-4">
            <button
              type="button"
              onClick={handlePreviewToggle}
              disabled={busy !== null}
              className={secondaryButton}
            >
              {busy === 'preview' ? 'Loading…' : previewOpen ? 'Hide preview' : 'Preview'}
            </button>
            <button
              type="button"
              onClick={() => handleDownload('docx')}
              disabled={busy !== null}
              className={secondaryButton}
            >
              {busy === 'download-docx' ? 'Downloading…' : 'Download DOCX'}
            </button>
            <button
              type="button"
              onClick={() => handleDownload('pdf')}
              disabled={busy !== null}
              className={secondaryButton}
            >
              {busy === 'download-pdf' ? 'Downloading…' : 'Download PDF'}
            </button>

            {canManageMom && (
              <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
                <button
                  type="button"
                  onClick={() => handleStatus('sent')}
                  disabled={busy !== null || mom.status === 'sent'}
                  className={secondaryButton}
                >
                  Mark as sent
                </button>
                <button
                  type="button"
                  onClick={() => handleStatus('acknowledged')}
                  disabled={busy !== null || mom.status === 'acknowledged'}
                  className={secondaryButton}
                >
                  Acknowledged
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setError(null);
                    setDisputeOpen((open) => !open);
                  }}
                  disabled={busy !== null}
                  className="rounded-md border border-red-300 bg-apple-surface px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Disputed
                </button>
              </div>
            )}
          </div>

          {canManageMom && disputeOpen && (
            <div className="rounded-md border border-red-200 bg-red-50 p-4">
              <label
                htmlFor="dispute-note"
                className="block text-sm font-medium text-red-800"
              >
                Dispute note <span className="text-red-600">*</span>
              </label>
              <textarea
                id="dispute-note"
                rows={3}
                value={disputeNote}
                onChange={(e) => setDisputeNote(e.target.value)}
                placeholder="Describe what is being disputed…"
                className="mt-1 block w-full rounded-md border border-red-300 bg-apple-surface px-3 py-2 text-sm shadow-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500"
              />
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={submitDispute}
                  disabled={busy !== null || !disputeNote.trim()}
                  className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Confirm dispute
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setDisputeOpen(false);
                    setDisputeNote('');
                  }}
                  className={secondaryButton}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

