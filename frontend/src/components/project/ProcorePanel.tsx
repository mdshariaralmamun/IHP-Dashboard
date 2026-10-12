'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  addProcoreComment,
  deleteProcoreComment,
  downloadCommentLog,
  downloadProcoreBinder,
  generateProcoreRevision,
  getProcore,
  setProcoreState,
  updateProcoreComment,
  uploadProcoreSubmittal,
} from '@/lib/api';
import type { ProcoreCommentRow, ProcoreState } from '@/lib/api';
import { VisualCard } from '@/components/powerbi/PowerBI';

const FIELD =
  'w-full rounded-md border border-apple-border bg-transparent px-2 py-1 text-xs text-apple-text outline-none focus:border-blue-400';

const STATUS_STYLE: Record<string, string> = {
  'Under Review': 'bg-blue-100 text-blue-800',
  'Revise and Resubmit': 'bg-red-100 text-red-800',
  'Approved as Noted': 'bg-emerald-100 text-emerald-800',
  Approved: 'bg-emerald-100 text-emerald-800',
};

/**
 * The Procore review round-trip.
 *
 * Rev 0 goes out, the reviewers (HSE, FLP/Fire Protection, FMOM/Building
 * Management, Building Operations, CTPS, the Proponent PI) send comments, IHP
 * answers each one here, the Comment Log Sheet is exported, and the answered
 * package goes back as Rev 1. The Procore status is set by hand because that is
 * what Procore tells the team - the app does not guess it.
 */
export default function ProcorePanel({
  projectId,
  prNumber,
}: {
  projectId: number;
  prNumber: string;
}) {
  const [data, setData] = useState<ProcoreState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [statusDraft, setStatusDraft] = useState('');
  const [dateDraft, setDateDraft] = useState('');
  const [drafts, setDrafts] = useState<Record<number, Partial<ProcoreCommentRow>>>({});
  const [fresh, setFresh] = useState({
    reviewer: '',
    department: '',
    discipline: '',
    comment: '',
  });

  const load = useCallback(() => {
    getProcore(projectId)
      .then((state) => {
        setData(state);
        setStatusDraft(state.procore_status ?? '');
        setDateDraft(state.procore_submittal_date ?? '');
        setError(null);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Could not load the Procore review'),
      );
  }, [projectId]);

  useEffect(load, [load]);

  const reviewers = useMemo(() => data?.reviewers ?? [], [data]);
  const statuses = useMemo(() => data?.statuses ?? [], [data]);
  const revision = data?.revision ?? 0;
  const comments = data?.comments ?? [];

  async function guard(action: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      if (done) setNotice(done);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That step failed');
    } finally {
      setBusy(false);
    }
  }

  function edit(row: ProcoreCommentRow, patch: Partial<ProcoreCommentRow>) {
    setDrafts((prev) => ({ ...prev, [row.id]: { ...prev[row.id], ...patch } }));
  }

  function value(row: ProcoreCommentRow, key: keyof ProcoreCommentRow): string {
    const draft = drafts[row.id]?.[key];
    const raw = draft !== undefined ? draft : row[key];
    return raw === null || raw === undefined ? '' : String(raw);
  }

  const dirty = (row: ProcoreCommentRow) => Object.keys(drafts[row.id] ?? {}).length > 0;

  function saveRow(row: ProcoreCommentRow) {
    const patch = drafts[row.id];
    if (!patch) return;
    return guard(
      () => updateProcoreComment(projectId, row.id, patch),
      'Comment ' + row.item_no + ' saved.',
    ).then(() => setDrafts((prev) => ({ ...prev, [row.id]: {} })));
  }

  return (
    <VisualCard
      title="Procore review"
      subtitle={
        data
          ? 'Rev ' +
            revision +
            ' · ' +
            (data.open_comments || 0) +
            ' open of ' +
            comments.length +
            ' comment' +
            (comments.length === 1 ? '' : 's') +
            (data.procore_status ? ' · ' + data.procore_status : '')
          : 'reviewer comments, the comment log sheet, and the revision going back'
      }
    >
      {error && (
        <p className="mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}
      {notice && (
        <p className="mb-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          {notice}
        </p>
      )}

      <div className="mb-4 grid gap-2 sm:grid-cols-3">
        <label className="text-xs text-apple-muted">
          Procore status
          <select
            className={FIELD + ' mt-1'}
            value={statusDraft}
            onChange={(e) => setStatusDraft(e.target.value)}
          >
            <option value="">Not submitted yet</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-apple-muted">
          Submittal date
          <input
            type="date"
            className={FIELD + ' mt-1'}
            value={dateDraft}
            onChange={(e) => setDateDraft(e.target.value)}
          />
        </label>
        <div className="flex items-end gap-2">
          <button
            type="button"
            disabled={busy}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            onClick={() =>
              guard(
                () =>
                  setProcoreState(projectId, {
                    procore_status: statusDraft || null,
                    procore_submittal_date: dateDraft || null,
                  }),
                'Procore status saved.',
              )
            }
          >
            Save status
          </button>
          {data?.procore_status && (
            <span
              className={
                'rounded-full px-2 py-1 text-[11px] font-medium ' +
                (STATUS_STYLE[data.procore_status] ?? 'bg-slate-100 text-slate-600')
              }
            >
              {data.procore_status}
            </span>
          )}
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          className="rounded-md border border-apple-border px-3 py-1.5 text-xs font-medium text-apple-text hover:bg-apple-hover disabled:opacity-50"
          onClick={() =>
            guard(
              () => downloadProcoreBinder(projectId, revision),
              'Binder Rev ' + revision + ' downloaded.',
            )
          }
        >
          Download Procore Binder (Rev {revision})
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded-md border border-apple-border px-3 py-1.5 text-xs font-medium text-apple-text hover:bg-apple-hover disabled:opacity-50"
          onClick={() =>
            guard(
              () => generateProcoreRevision(projectId),
              'Revision ' + (revision + 1) + ' package started.',
            )
          }
        >
          Generate Revision {revision + 1} Package
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded-md border border-apple-border px-3 py-1.5 text-xs font-medium text-apple-text hover:bg-apple-hover disabled:opacity-50"
          onClick={() => guard(() => downloadCommentLog(projectId, prNumber, 'xlsx'))}
        >
          Comment Log Sheet (.xlsx)
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded-md border border-apple-border px-3 py-1.5 text-xs font-medium text-apple-text hover:bg-apple-hover disabled:opacity-50"
          onClick={() => guard(() => downloadCommentLog(projectId, prNumber, 'pdf'))}
        >
          Comment Log Sheet (.pdf)
        </button>
      </div>

      <label className="mb-4 block cursor-pointer rounded-lg border border-dashed border-apple-border px-3 py-4 text-center text-xs text-apple-muted hover:bg-apple-hover">
        <input
          type="file"
          accept="application/pdf"
          className="hidden"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (file) {
              setUploading(true);
              guard(() => uploadProcoreSubmittal(projectId, file), 'Stamped submittal uploaded.').finally(
                () => setUploading(false),
              );
            }
          }}
        />
        {uploading
          ? 'Uploading the stamped submittal…'
          : 'Drop the stamped Procore Submittal PDF here, or click to choose it'}
      </label>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-xs">
          <thead className="text-[11px] uppercase tracking-wide text-apple-muted">
            <tr>
              <th className="py-1 pr-2">#</th>
              <th className="py-1 pr-2">Reviewer</th>
              <th className="py-1 pr-2">Dept / Discipline</th>
              <th className="py-1 pr-2">Reviewer comment</th>
              <th className="py-1 pr-2">IHP response</th>
              <th className="py-1 pr-2">Action taken</th>
              <th className="py-1 pr-2">Status</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {comments.map((row) => (
              <tr key={row.id} className="border-t border-apple-border align-top">
                <td className="py-2 pr-2 text-apple-muted">
                  {row.item_no}
                  <div className="text-[10px]">Rev {row.revision}</div>
                </td>
                <td className="py-2 pr-2">
                  <select
                    className={FIELD}
                    value={value(row, 'reviewer')}
                    onChange={(e) => edit(row, { reviewer: e.target.value })}
                  >
                    <option value="">Select…</option>
                    {Array.from(new Set([...reviewers, row.reviewer].filter(Boolean))).map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                  <input
                    className={FIELD + ' mt-1'}
                    placeholder="or type a name"
                    value={value(row, 'reviewer')}
                    onChange={(e) => edit(row, { reviewer: e.target.value })}
                  />
                </td>
                <td className="py-2 pr-2">
                  <input
                    className={FIELD}
                    placeholder="Department"
                    value={value(row, 'department')}
                    onChange={(e) => edit(row, { department: e.target.value })}
                  />
                  <input
                    className={FIELD + ' mt-1'}
                    placeholder="Discipline"
                    value={value(row, 'discipline')}
                    onChange={(e) => edit(row, { discipline: e.target.value })}
                  />
                </td>
                <td className="py-2 pr-2">
                  <textarea
                    className={FIELD + ' min-h-[64px] resize-y'}
                    value={value(row, 'comment')}
                    onChange={(e) => edit(row, { comment: e.target.value })}
                  />
                </td>
                <td className="py-2 pr-2">
                  <textarea
                    className={FIELD + ' min-h-[64px] resize-y'}
                    placeholder="What IHP answers"
                    value={value(row, 'ihp_response')}
                    onChange={(e) => edit(row, { ihp_response: e.target.value })}
                  />
                </td>
                <td className="py-2 pr-2">
                  <textarea
                    className={FIELD + ' min-h-[64px] resize-y'}
                    placeholder="Where it changed (SOW § / drawing / BOQ item)"
                    value={value(row, 'action_taken')}
                    onChange={(e) => edit(row, { action_taken: e.target.value })}
                  />
                </td>
                <td className="py-2 pr-2">
                  <select
                    className={FIELD}
                    value={value(row, 'status') || 'open'}
                    onChange={(e) => edit(row, { status: e.target.value })}
                  >
                    <option value="open">Open</option>
                    <option value="closed">Closed</option>
                  </select>
                </td>
                <td className="py-2">
                  <div className="flex flex-col gap-1">
                    <button
                      type="button"
                      disabled={busy || !dirty(row)}
                      className="rounded-md bg-blue-600 px-2 py-1 text-[11px] font-medium text-white disabled:opacity-40"
                      onClick={() => saveRow(row)}
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      className="rounded-md border border-apple-border px-2 py-1 text-[11px] text-red-600 disabled:opacity-40"
                      onClick={() => guard(() => deleteProcoreComment(projectId, row.id))}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {comments.length === 0 && (
              <tr>
                <td colSpan={8} className="py-3 text-apple-muted">
                  No reviewer comments yet. Add the first one below when Procore sends
                  them back.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 rounded-lg border border-apple-border p-3">
        <p className="mb-2 text-xs font-medium text-apple-text">Add a reviewer comment</p>
        <div className="grid gap-2 sm:grid-cols-3">
          <select
            className={FIELD}
            value={fresh.reviewer}
            onChange={(e) => setFresh({ ...fresh, reviewer: e.target.value })}
          >
            <option value="">Reviewer…</option>
            {reviewers.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input
            className={FIELD}
            placeholder="Department"
            value={fresh.department}
            onChange={(e) => setFresh({ ...fresh, department: e.target.value })}
          />
          <input
            className={FIELD}
            placeholder="Discipline"
            value={fresh.discipline}
            onChange={(e) => setFresh({ ...fresh, discipline: e.target.value })}
          />
        </div>
        <textarea
          className={FIELD + ' mt-2 min-h-[72px] resize-y'}
          placeholder="The reviewer's comment, as received"
          value={fresh.comment}
          onChange={(e) => setFresh({ ...fresh, comment: e.target.value })}
        />
        <button
          type="button"
          disabled={busy || !fresh.comment.trim()}
          className="mt-2 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          onClick={() =>
            guard(() => addProcoreComment(projectId, fresh), 'Comment added.').then(() =>
              setFresh({ reviewer: '', department: '', discipline: '', comment: '' }),
            )
          }
        >
          Add comment
        </button>
      </div>
    </VisualCard>
  );
}
