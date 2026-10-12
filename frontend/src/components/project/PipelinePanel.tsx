'use client';

import { useCallback, useEffect, useState } from 'react';
import { getPipeline, setPipelineStage } from '@/lib/api';
import type { PipelineResponse, PipelineStageRow } from '@/lib/api';
import { VisualCard } from '@/components/powerbi/PowerBI';

const STATUS_STYLE: Record<string, string> = {
  not_started: 'bg-slate-100 text-slate-600',
  in_progress: 'bg-blue-100 text-blue-800',
  awaiting_feedback: 'bg-amber-100 text-amber-800',
  pending_approval: 'bg-amber-100 text-amber-800',
  under_review: 'bg-blue-100 text-blue-800',
  revise_and_resubmit: 'bg-red-100 text-red-800',
  approved_as_noted: 'bg-emerald-100 text-emerald-800',
  approved: 'bg-emerald-100 text-emerald-800',
  confirmed: 'bg-emerald-100 text-emerald-800',
  done: 'bg-emerald-100 text-emerald-800',
};

/**
 * The five-stage delivery spine.
 *
 * One row per stage with its status, so "where is this PR?" is answered in one
 * place. The gates are enforced by the API, not here: a stage that may not
 * start yet shows why instead of offering a status that would be refused.
 */
export default function PipelinePanel({ projectId }: { projectId: number }) {
  const [data, setData] = useState<PipelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});

  const load = useCallback(() => {
    getPipeline(projectId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load the pipeline'));
  }, [projectId]);

  useEffect(load, [load]);

  async function apply(row: PipelineStageRow, status: string) {
    setBusy(row.stage);
    setError(null);
    try {
      const next = await setPipelineStage(projectId, row.stage, {
        status,
        note: notes[row.stage] !== undefined ? notes[row.stage] : row.note,
      });
      setData(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not set the stage');
    } finally {
      setBusy(null);
    }
  }

  const stages = data?.stages ?? [];

  return (
    <VisualCard
      title={'Delivery pipeline'}
      subtitle={
        data
          ? 'Stage ' + data.current_stage + ' of 5 · MTO ' + (data.mto_unlocked ? 'unlocked' : 'locked until Procore approves')
          : 'the five milestone gates for this PR'
      }
    >
      {error && (
        <p className="mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}
      <ul className="space-y-2">
        {stages.map((row) => (
          <li
            key={row.stage}
            className="rounded-lg border border-slate-200 px-3 py-2 dark:border-white/10"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-bold text-white">
                {row.stage}
              </span>
              <span className="text-sm font-semibold text-apple-text">{row.label}</span>
              <span
                className={
                  'rounded-full px-2 py-0.5 text-[10px] font-semibold ' +
                  (STATUS_STYLE[row.status] ?? 'bg-slate-100 text-slate-600')
                }
              >
                {row.status.replace(/_/g, ' ')}
              </span>
              {row.stage === 5 && !data?.mto_unlocked && (
                <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-700">
                  LOCKED
                </span>
              )}
              <select
                value={row.status}
                disabled={busy === row.stage || (row.blocked_reason !== null && row.status === 'not_started')}
                onChange={(e) => void apply(row, e.target.value)}
                className="ml-auto rounded border border-slate-200 px-2 py-1 text-[11px] dark:border-white/10 dark:bg-white/5"
              >
                {row.allowed_statuses.map((option) => (
                  <option key={option} value={option}>
                    {option.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </div>
            {row.blocked_reason && row.status === 'not_started' && (
              <p className="mt-1 text-[11px] font-medium text-amber-700">{row.blocked_reason}</p>
            )}
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <input
                defaultValue={row.note ?? ''}
                onChange={(e) => setNotes((prev) => ({ ...prev, [row.stage]: e.target.value }))}
                placeholder={
                  row.stage === 4
                    ? 'Procore submittal date / reference (upload the submittal PDF in the Data room)'
                    : 'Note — reviewer, date, what is outstanding'
                }
                className="min-w-[16rem] flex-1 rounded border border-slate-200 px-2 py-1 text-[11px] dark:border-white/10 dark:bg-white/5"
              />
              <button
                type="button"
                disabled={busy === row.stage}
                onClick={() => void apply(row, row.status)}
                className="rounded border border-slate-200 px-2 py-1 text-[10px] font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-white/10"
              >
                Save note
              </button>
              {row.updated_at && (
                <span className="text-[10px] text-apple-muted">
                  updated {row.updated_at.slice(0, 10)}
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
      {!data && !error && <p className="text-xs text-apple-muted">Loading the pipeline…</p>}
    </VisualCard>
  );
}
