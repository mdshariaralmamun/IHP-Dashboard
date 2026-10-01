'use client';

import { useState } from 'react';
import { ApiError, setProjectStage } from '@/lib/api';
import { STAGES, stageName } from '@/lib/stages';
import type { ProjectDetail } from '@/lib/types';

/**
 * Move a project from one phase to another, with a reason that is kept.
 *
 * The backend walks the shortest legal path through the workflow and writes
 * the justification onto every hop. When the workflow has no path to the
 * target it answers 409; for an admin this panel then offers the explicit
 * direct move, which is still justified and is recorded as `stage:override`
 * so a bypassed workflow never looks like a normal transition.
 *
 * The examples in the hint are the real reasons that come up: assessment
 * cancelled for budget, a duplicate PR to be combined, equipment work that
 * belongs to the other branch, a scope reduced after a site visit.
 */
export default function StageChangePanel({
  project,
  canForce,
  onChanged,
}: {
  project: ProjectDetail;
  /** users.manage — what the backend requires to force an unconnected move. */
  canForce: boolean;
  onChanged: () => void;
}) {
  const [target, setTarget] = useState('');
  const [justification, setJustification] = useState('');
  const [force, setForce] = useState(false);
  const [needsForce, setNeedsForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const options = STAGES.filter((s) => s.id !== project.stage);
  const ready = Boolean(target) && justification.trim().length >= 3 && !busy;

  function reset() {
    setTarget('');
    setJustification('');
    setForce(false);
    setNeedsForce(false);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    setNotice(null);
    const movedTo = target;
    try {
      await setProjectStage(project.id, movedTo, { justification, force });
      setNotice(`${project.pr_number} moved to ${stageName(movedTo)}.`);
      reset();
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && !force) {
        // The workflow has no path: offer the override instead of a dead end.
        setNeedsForce(true);
      } else {
        setError(e instanceof Error ? e.message : 'Could not change the stage.');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-apple-border bg-apple-surface p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-apple-text">Move to another phase</h3>
      <p className="mt-1 text-xs text-apple-muted">
        Current phase: <span className="font-semibold text-apple-text">{stageName(project.stage)}</span>.
        The reason is saved to the audit trail — write it so it still makes sense in six months.
      </p>

      <div className="mt-3 grid gap-3 md:grid-cols-[220px_1fr_auto]">
        <select
          value={target}
          onChange={(e) => { setTarget(e.target.value); setNeedsForce(false); }}
          className="rounded-md border border-apple-border bg-apple-surface px-3 py-2 text-sm text-apple-text focus:outline-none focus:ring-2 focus:ring-primary/40"
        >
          <option value="">Choose a phase…</option>
          {options.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}{s.terminal ? ' (final)' : ''}
            </option>
          ))}
        </select>

        <input
          type="text"
          value={justification}
          onChange={(e) => setJustification(e.target.value)}
          placeholder="Why? e.g. Assessment cancelled — budget pulled; PI re-initiates under a new PR"
          className="rounded-md border border-apple-border bg-apple-surface px-3 py-2 text-sm text-apple-text placeholder:text-apple-muted focus:outline-none focus:ring-2 focus:ring-primary/40"
        />

        <button
          type="button"
          onClick={() => void submit()}
          disabled={!ready}
          className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {busy ? 'Moving…' : force ? 'Force move' : 'Move phase'}
        </button>
      </div>

      {needsForce && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <p className="font-semibold">
            The workflow has no {stageName(project.stage)} → {stageName(target)} step.
          </p>
          {canForce ? (
            <label className="mt-2 flex items-start gap-2">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                className="mt-0.5"
              />
              <span>
                Move it directly anyway. This is recorded as an <strong>override</strong>, not a
                normal transition, together with the reason above.
              </span>
            </label>
          ) : (
            <p className="mt-1">
              Only an admin can move a project the workflow does not connect.
            </p>
          )}
        </div>
      )}

      {error && (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}
      {notice && (
        <p className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          {notice}
        </p>
      )}
    </div>
  );
}
