'use client';

import { useState } from 'react';
import ErrorBox from '@/components/ErrorBox';
import { canDo } from '@/lib/useUser';
import {
  generateEarDoc,
  runEarAiReview,
  submitEarTradeInput,
  updateEar,
} from '@/lib/api';
import type { EarRecord, ProjectDetail, User } from '@/lib/types';

const TRADES = [
  'civil_arch',
  'electrical',
  'low_current',
  'plumbing',
  'fire_protection',
  'hvac',
];

export default function EarPanel({
  project,
  currentUser,
  onChanged,
}: {
  project: ProjectDetail;
  currentUser: User | null;
  onChanged: () => void;
}) {
  const canManage = canDo(currentUser, 'ear.manage');
  const canInput = canDo(currentUser, 'ear.input');
  const isIcr = project.disposition === 'ICR';

  const [summary, setSummary] = useState(project.ear?.summary ?? '');
  const [recommendations, setRecommendations] = useState(
    project.ear?.recommendations ?? '',
  );
  const [trade, setTrade] = useState<string>(currentUser?.trade ?? 'civil_arch');
  const [form, setForm] = useState({
    proposal: '',
    comments: '',
    missing_info: '',
    has_conflict: false,
    estimated_materials_cost: '0',
    estimated_manpower_cost: '0',
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewSummary, setReviewSummary] = useState<string | null>(null);

  const effectiveTrade =
    currentUser?.role !== 'admin' && currentUser?.trade
      ? currentUser.trade
      : trade;

  if (isIcr) {
    return (
      <section className="p-4 border rounded border-apple-surface text-apple-text">
        <p className="text-sm text-apple-muted">
          This project is ICR-classified and skips the EAR step. The MTO and
          ICR hand-off milestones are tracked in the Construction and ICR
          panels.
        </p>
      </section>
    );
  }

  async function run<T>(key: string, action: () => Promise<T>): Promise<T | undefined> {
    if (busy) return undefined;
    setBusy(key);
    setError(null);
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

  async function handleUpdate() {
    await run('update', () =>
      updateEar(project.id, { summary, recommendations }),
    );
  }

  async function handleStatus(status: 'draft' | 'under_review' | 'approved') {
    await run(`status-${status}`, () => updateEar(project.id, { status }));
  }

  async function handleSubmitTrade() {
    if (!form.proposal.trim()) {
      setError('Enter a proposal before submitting.');
      return;
    }
    const payload = {
      trade: effectiveTrade,
      proposal: form.proposal,
      comments: form.comments,
      missing_info: form.missing_info,
      has_conflict: form.has_conflict,
      estimated_materials_cost: Number(form.estimated_materials_cost) || 0,
      estimated_manpower_cost: Number(form.estimated_manpower_cost) || 0,
    };
    const res = await run('trade-input', () => submitEarTradeInput(project.id, payload));
    if (res) {
      setForm({
        proposal: '',
        comments: '',
        missing_info: '',
        has_conflict: false,
        estimated_materials_cost: '0',
        estimated_manpower_cost: '0',
      });
    }
  }

  async function handleAiReview() {
    const res = await run('ai-review', () => runEarAiReview(project.id));
    if (res) {
      setReviewSummary(
        `AI review recorded ${res.count} finding${res.count === 1 ? '' : 's'}.`,
      );
    }
  }

  async function handleGenerate() {
    const res = await run('generate', () => generateEarDoc(project.id));
    if (res?.docx_filename) {
      setReviewSummary(`Generated ${res.docx_filename}.`);
    }
  }

  const ear: EarRecord | null = project.ear ?? null;
  const tradeInputs = ear?.trade_inputs ?? [];
  const findings = ear?.ai_review_findings ?? [];

  return (
    <section className="p-4 border rounded border-apple-surface text-apple-text space-y-3">
      <p className="text-xs font-medium uppercase tracking-wider text-apple-muted/60 mb-2">
        Engineering Assessment Report (EAR)
      </p>
      <p className="text-sm text-apple-muted/60">
        Captures the high-level engineering assessment, per-trade proposals,
        budget envelope, and AI code-compliance review. Approved EARs gate the
        SOW stage.
      </p>

      {error && (
        <div className="mb-2">
          <ErrorBox message={error} />
        </div>
      )}
      {reviewSummary && (
        <div className="mb-2 rounded-sm border border-apple-surface/50 bg-apple-surface/50 px-2 py-1 text-xs text-apple-text">
          {reviewSummary}
        </div>
      )}

      {canManage && ear && (
        <div className="mb-3">
          <p className="text-xs font-medium text-apple-muted/60 mb-1">
            Executive summary
          </p>
          <textarea
            rows={3}
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
          />
          <p className="text-xs font-medium text-apple-muted/60 mb-1">
            Recommendations
          </p>
          <textarea
            rows={3}
            value={recommendations}
            onChange={(e) => setRecommendations(e.target.value)}
            className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
          />
        </div>
      )}

      {canManage && (
        <div className="mb-3">
          <p className="text-xs font-medium uppercase tracking-wider text-apple-muted/60 mb-1">
            Submit your trade proposal
          </p>
          {currentUser?.role !== 'admin' && (
            <p className="text-xs text-apple-muted/60">
              Trade: <span className="font-medium text-apple-text">{effectiveTrade}</span>
              (pinned to your account)
            </p>
          )}
          {currentUser?.role === 'admin' && (
            <div className="mb-2">
              <label className="block text-xs font-medium text-apple-muted/60">
                Trade
              </label>
              <select
                value={trade}
                onChange={(e) => setTrade(e.target.value)}
                className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
              >
                {TRADES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="space-y-2">
            <textarea
              rows={2}
              value={form.proposal}
              onChange={(e) => setForm((f) => ({ ...f, proposal: e.target.value }))}
              placeholder="Describe the trade proposal…"
              className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
            />
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <input
                type="text"
                value={form.comments}
                onChange={(e) =>
                  setForm((f) => ({ ...f, comments: e.target.value }))
                }
                placeholder="Comments / clarifications"
                className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
              />
              <input
                type="text"
                value={form.missing_info}
                onChange={(e) =>
                  setForm((f) => ({ ...f, missing_info: e.target.value }))
                }
                placeholder="Missing information"
                className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
              />
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <input
                type="number"
                min={0}
                value={form.estimated_materials_cost}
                onChange={(e) =>
                  setForm((f) => ({ ...f, estimated_materials_cost: e.target.value }))
                }
                placeholder="Materials cost (SAR)"
                className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
              />
              <input
                type="number"
                min={0}
                value={form.estimated_manpower_cost}
                onChange={(e) =>
                  setForm((f) => ({ ...f, estimated_manpower_cost: e.target.value }))
                }
                placeholder="Manpower cost (SAR)"
                className="rounded-sm border border-apple-border/50 px-2.5 py-1.5 text-sm"
              />
            </div>
            <label className="flex items-center gap-2 text-xs text-apple-muted/60">
              <input
                type="checkbox"
                checked={form.has_conflict}
                onChange={(e) =>
                  setForm((f) => ({ ...f, has_conflict: e.target.checked }))
                }
              />
              Flag as conflict (triggers AI review on next run)
            </label>
            <div>
              <button
                type="button"
                onClick={handleSubmitTrade}
                disabled={busy !== null}
                className="rounded-sm bg-primary px-2 py-1 text-sm font-medium text-white hover:bg-apple-surface/90 disabled:opacity-50"
              >
                {busy === 'trade-input' ? 'Submitting…' : 'Submit proposal'}
              </button>
            </div>
          </div>
        </div>
      )}

      {canManage && ear && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-apple-muted/60 mb-1">
            AI code-compliance review
          </p>
          {busy === 'ai-review' ? (
            <p className="text-xs text-apple-muted">Running…</p>
          ) : (
            <button
              type="button"
              onClick={handleAiReview}
              disabled={busy !== null}
              className="rounded-sm border border-apple-surface/50 px-2 py-1 text-xs font-medium text-apple-text hover:bg-apple-surface/50 disabled:opacity-50"
            >
              {busy !== null ? 'Running…' : 'Run review'}
            </button>
          )}
        </div>
      )}

      {findings.length === 0 ? (
        <p className="text-xs text-apple-muted/60">
          No findings recorded yet. Run a review to capture code / standards
          gaps against the trade proposals.
        </p>
      ) : (
        <ul className="text-xs text-apple-text space-y-1">
          {findings.map((finding, i) => (
            <li key={i} className="border-b border-apple-border/20 py-1">
              <span className="text-apple-muted/60 small">{finding.type}</span>
              {finding.trade && (
                <span className="text-apple-muted">{finding.trade}</span>
              )}
              <p className="mt-0.5 text-apple-text">{finding.description}</p>
              {finding.citation && (
                <p className="mt-0.5 text-apple-muted">{finding.citation}</p>
              )}
              {finding.resolution && (
                <p className="mt-0.5 text-apple-muted">
                  <span className="font-medium">Resolution:</span>{' '}
                  {finding.resolution}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}