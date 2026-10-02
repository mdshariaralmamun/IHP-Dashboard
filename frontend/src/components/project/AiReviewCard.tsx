'use client';

import { useEffect, useState } from 'react';
import { ApiError, getAiReview, runAiReview } from '@/lib/api';
import type { AiReview, AiReviewFinding } from '@/lib/api';

const SEVERITY: Record<string, { label: string; cls: string }> = {
  critical: { label: 'Critical', cls: 'bg-red-100 text-red-800 ring-red-300' },
  major: { label: 'Major', cls: 'bg-amber-100 text-amber-800 ring-amber-300' },
  minor: { label: 'Minor', cls: 'bg-blue-100 text-blue-800 ring-blue-300' },
  info: { label: 'Info', cls: 'bg-slate-100 text-slate-700 ring-slate-300' },
};

const KIND_LABEL: Record<string, string> = {
  conflict: 'Documents disagree',
  deficiency: 'Design deficiency',
  calculation: 'Calculation',
  missing_input: 'Missing input',
  unclear: 'Unclear',
};

const ORDER = ['critical', 'major', 'minor', 'info'];

/**
 * The AI review of everything uploaded to this project.
 *
 * It reads the indexed documents (PR form, equipment specification, utility
 * matrix, invitation, drawings, calculations) plus the live register and
 * reports what has to be settled before the scope is committed: documents
 * that disagree, design gaps, arithmetic that does not add up, inputs nobody
 * supplied. Every finding names the document it came from and the fix.
 *
 * Nothing here is asserted as fact — a model misreads numbers, so a finding is
 * a question to the engineer with the evidence attached, and the resolution
 * stays human.
 */
export default function AiReviewCard({
  projectId,
  attachmentCount,
  canRun,
}: {
  projectId: number;
  /** Attachments on the project, to warn when they have not been read. */
  attachmentCount: number;
  canRun: boolean;
}) {
  const [review, setReview] = useState<AiReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAiReview(projectId)
      .then((data) => {
        if (!cancelled) setReview(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setReview(await runAiReview(projectId));
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'The review could not be run.',
      );
    } finally {
      setBusy(false);
    }
  }

  const findings = review?.findings ?? [];
  const sorted = [...findings].sort(
    (a, b) => ORDER.indexOf(String(a.severity)) - ORDER.indexOf(String(b.severity)),
  );
  const critical = findings.filter((f) => f.severity === 'critical').length;
  const readCount = review?.documents_indexed ?? 0;
  const unread = Math.max(0, attachmentCount - readCount);

  return (
    <div className="rounded-lg border border-apple-border bg-apple-surface p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-apple-text">AI review of the documents</h3>
          <p className="mt-1 text-xs text-apple-muted">
            Reads the PR form, specifications, utility matrix, invitation and drawings and
            reports what must be settled before the scope is committed.
          </p>
          {review?.generated_at && (
            <p className="mt-1 text-[11px] text-apple-muted">
              {new Date(review.generated_at).toLocaleString()}
              {review.model ? ` · ${review.model}` : ''}
              {review.confidence ? ` · confidence ${review.confidence}` : ''}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => void run()}
          disabled={busy || !canRun}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {busy ? 'Reviewing…' : review?.summary ? 'Re-run review' : 'Review the documents'}
        </button>
      </div>

      {!canRun && (
        <p className="mt-3 text-[11px] italic text-apple-muted">
          read-only (needs projects.edit)
        </p>
      )}
      {error && (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {unread > 0 && (
        <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {unread} of {attachmentCount} file{attachmentCount === 1 ? '' : 's'} have not been read
          yet — an administrator can index them from Settings → AI, then re-run this review.
        </p>
      )}

      {review?.summary && (
        <p className="mt-4 whitespace-pre-wrap text-sm text-apple-text">{review.summary}</p>
      )}

      {critical > 0 && (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-800">
          {critical} critical finding{critical === 1 ? '' : 's'} — do not commit the scope before
          they are closed.
        </p>
      )}

      {sorted.length > 0 && (
        <div className="mt-4 space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
            Findings ({sorted.length})
          </h4>
          {sorted.map((finding, index) => (
            <Finding key={finding.id ?? index} finding={finding} />
          ))}
        </div>
      )}

      {(review?.questions ?? []).length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
            Questions to answer
          </h4>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-apple-text">
            {(review?.questions ?? []).map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {(review?.missing_documents ?? []).length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
            Documents that should have been attached
          </h4>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-apple-text">
            {(review?.missing_documents ?? []).map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      )}

      {(review?.documents_read ?? []).length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
            Documents read ({readCount})
          </h4>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {(review?.documents_read ?? []).map((doc) => (
              <span
                key={doc.name}
                className="rounded bg-apple-surface/70 px-1.5 py-0.5 text-[11px] text-apple-muted ring-1 ring-inset ring-apple-border"
                title={doc.kind}
              >
                {doc.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Finding({ finding }: { finding: AiReviewFinding }) {
  const meta = SEVERITY[String(finding.severity)] ?? SEVERITY.minor;
  return (
    <div className="rounded-md border border-apple-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ring-1 ring-inset ${meta.cls}`}
        >
          {meta.label}
        </span>
        <span className="text-sm font-semibold text-apple-text">
          {finding.title ?? 'Finding'}
        </span>
        {finding.kind && (
          <span className="text-[11px] text-apple-muted">
            {KIND_LABEL[finding.kind] ?? finding.kind}
          </span>
        )}
      </div>
      {finding.detail && (
        <p className="mt-2 whitespace-pre-wrap text-xs text-apple-text">{finding.detail}</p>
      )}
      {finding.why && (
        <p className="mt-1 text-xs text-apple-muted">
          <span className="font-semibold">Why it matters: </span>
          {finding.why}
        </p>
      )}
      {finding.required_fix && (
        <p className="mt-1 text-xs text-apple-text">
          <span className="font-semibold">Required fix: </span>
          {finding.required_fix}
        </p>
      )}
      {(finding.documents ?? []).length > 0 && (
        <p className="mt-1 text-[11px] text-apple-muted">
          From: {(finding.documents ?? []).join(', ')}
        </p>
      )}
    </div>
  );
}
