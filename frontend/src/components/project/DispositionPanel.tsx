'use client';

import { useState } from 'react';
import ErrorBox from '@/components/ErrorBox';
import { setDisposition } from '@/lib/api';
import { canDo } from '@/lib/useUser';
import type { ProjectDetail, User } from '@/lib/types';

export default function DispositionPanel({
  project,
  currentUser,
  onChanged,
}: {
  project: ProjectDetail;
  currentUser: User | null;
  onChanged: () => void;
}) {
  const canManage = canDo(currentUser, 'disposition.manage');
  const isIcr = project.disposition === 'ICR';
  const isProject = project.disposition === 'PROJECT';
  const isUnset = project.disposition === null || project.disposition === undefined;

  const [pick, setPick] = useState<'ICR' | 'PROJECT'>(
    isIcr ? 'ICR' : isProject ? 'PROJECT' : 'PROJECT',
  );
  const [justification, setJustification] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await setDisposition(project.id, pick, justification);
      setJustification('');
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set disposition.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-apple-muted">
        Disposition
      </h2>
      <p className="mb-4 text-xs text-apple-muted">
        Classify the PR as ICR (Instrument / Component / Repair — utility-only
        work that fast-tracks to MTO) or PROJECT (full lab modification that
        goes through EAR → SOW → MTO). Once set, the workflow branches.
      </p>

      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {!isUnset && (
        <div className="mb-4 rounded-md border border-apple-border bg-apple-surface/50 px-4 py-3 text-sm">
          <span className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
            Current
          </span>
          <p className="mt-1 text-base font-semibold text-apple-text">
            {project.disposition}
          </p>
          <p className="mt-1 text-xs text-apple-muted">
            {isIcr
              ? 'EAR and SOW are skipped; the project routes directly to MTO.'
              : 'Project progresses through EAR, SOW, MTO, procurement, work permit, construction, closeout.'}
          </p>
        </div>
      )}

      {canManage && (
        <div className="space-y-4">
          <fieldset className="space-y-2">
            <legend className="text-xs font-medium text-apple-muted">
              Choose a disposition
            </legend>
            <label className="flex items-start gap-3 rounded-md border border-apple-border px-3 py-2 text-sm hover:bg-apple-surface/50">
              <input
                type="radio"
                name="disposition"
                value="ICR"
                checked={pick === 'ICR'}
                onChange={() => setPick('ICR')}
                className="mt-0.5"
              />
              <span>
                <span className="block font-medium text-apple-text">ICR</span>
                <span className="text-xs text-apple-muted">
                  Utility connection / instrument replacement. Skips EAR and
                  SOW; flows through MTO → Project Control → EAT hand-offs.
                </span>
              </span>
            </label>
            <label className="flex items-start gap-3 rounded-md border border-apple-border px-3 py-2 text-sm hover:bg-apple-surface/50">
              <input
                type="radio"
                name="disposition"
                value="PROJECT"
                checked={pick === 'PROJECT'}
                onChange={() => setPick('PROJECT')}
                className="mt-0.5"
              />
              <span>
                <span className="block font-medium text-apple-text">Project</span>
                <span className="text-xs text-apple-muted">
                  Full lab modification requiring engineering assessment.
                  Flows through EAR → SOW → MTO → procurement → work permit →
                  construction → closeout.
                </span>
              </span>
            </label>
          </fieldset>

          <div>
            <label
              htmlFor="disposition-justification"
              className="block text-xs font-medium text-apple-muted"
            >
              Justification
            </label>
            <textarea
              id="disposition-justification"
              rows={3}
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder="Briefly explain why this branch was selected (audited)."
              className="mt-1 block w-full rounded-md border border-apple-border px-2.5 py-1.5 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={busy || (!isUnset && pick === project.disposition)}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-apple-surface disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy
                ? 'Saving…'
                : isUnset
                  ? 'Set disposition'
                  : 'Update disposition'}
            </button>
            {!isUnset && (
              <span className="text-xs text-apple-muted">
                Changing the disposition re-branches the workflow.
              </span>
            )}
          </div>
        </div>
      )}

      {!canManage && isUnset && (
        <p className="text-sm text-apple-muted">
          A planning user will set the disposition after reviewing the PR.
        </p>
      )}
    </section>
  );
}

