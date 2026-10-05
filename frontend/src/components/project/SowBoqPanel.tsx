'use client';

import { downloadIcrMto } from '@/lib/api';

import { useEffect, useState } from 'react';
import ErrorBox from '@/components/ErrorBox';
import { addBoqItem, createSowRevision, exportBoqExcel, getSowSuggestions, updateSowStatus } from '@/lib/api';
import type { SowSuggestion } from '@/lib/api';
import { formatDate } from '@/lib/format';
import { canDo } from '@/lib/useUser';
import type { BoqItem, ProjectDetail, SowRecord, User } from '@/lib/types';

const TRADES = [
  'civil_arch',
  'electrical',
  'low_current',
  'plumbing',
  'fire_protection',
  'hvac',
];

export default function SowBoqPanel({
  project,
  currentUser,
  onChanged,
}: {
  project: ProjectDetail;
  currentUser: User | null;
  onChanged: () => void;
}) {
  const canManageSow = canDo(currentUser, 'sow.manage');
  const canManageBoq = canDo(currentUser, 'boq.manage');
  const isIcr = project.disposition === 'ICR';

  const sowRecords: SowRecord[] = project.sow_records ?? [];
  const boqItems: BoqItem[] = (project.boq_items ?? []).filter(
    (b) => (b as BoqItem & { mto_kind?: string }).mto_kind !== 'construction',
  );

  const [revisionName, setRevisionName] = useState('');
  const [scopeText, setScopeText] = useState('');
  const [procoreComments, setProcoreComments] = useState('');
  const [boqDraft, setBoqDraft] = useState({
    trade: 'civil_arch',
    item_code: '',
    description: '',
    unit: 'EA',
    quantity: '',
    unit_rate: '',
    supplier_lead_time_days: '',
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportMsg, setExportMsg] = useState<string | null>(null);
  // Trade-wise suggestions mined from similar archived SOWs (review, then add).
  const [suggestions, setSuggestions] = useState<{ trade: string; suggestions: SowSuggestion[] }[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [showPreview, setShowPreview] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getSowSuggestions(project.id)
      .then((res) => {
        if (!cancelled) setSuggestions(res.trades ?? []);
      })
      .catch(() => {
        if (!cancelled) setSuggestions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, boqItems.length]);

  /** Accept one suggestion into the design BOQ for its trade. */
  async function acceptSuggestion(trade: string, text: string) {
    await run(`sug-${text.slice(0, 20)}`, () =>
      addBoqItem(project.id, {
        trade,
        item_code: '',
        description: text,
        unit: 'EA',
        quantity: 1,
      }),
    );
    setSuggestions((prev) =>
      prev
        .map((t) =>
          t.trade === trade
            ? { ...t, suggestions: t.suggestions.filter((s) => s.text !== text) }
            : t,
        )
        .filter((t) => t.suggestions.length > 0),
    );
  }

  const TRADE_LABELS: Record<string, string> = {
    civil_arch: 'Civil / Architectural',
    electrical: 'Electrical',
    low_current: 'Low Current / Telecommunication',
    plumbing: 'Plumbing',
    hvac: 'HVAC',
    fire_protection: 'Fire Sprinkler System',
    tgm: 'TGM / Gas Detection',
    macc: 'MACC',
  };
  const tradeLabelOf = (t: string) => TRADE_LABELS[t] ?? t.replace(/_/g, ' ');
  /** Live preview grouping: current design BOQ lines per trade. */
  const previewByTrade = boqItems.reduce<Record<string, BoqItem[]>>((acc, it) => {
    const key = it.trade || 'general';
    acc[key] = acc[key] ?? [];
    acc[key].push(it);
    return acc;
  }, {});
  const latestSow = sowRecords.length > 0 ? sowRecords[sowRecords.length - 1] : null;

  if (isIcr) {
    return (
      <section className="rounded-lg border border-apple-border bg-apple-surface p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-apple-text">
          ICR — materials take-off (MTO)
        </h3>
        <p className="mt-1 text-xs text-apple-muted">
          This PR is ICR-classified: it runs <strong>MOM → ICR hand-off →
          materials</strong> and skips EAR / SOW / BOQ. The MTO is built from the
          data room — the engineer&apos;s material list, the utility matrix, the
          supplier quotations — so upload those first, press{' '}
          <strong>Analyze with AI</strong>, then generate the MTO here.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void run('mto', () => downloadIcrMto(project.id))}
            className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {busy === 'mto' ? 'Generating…' : 'Generate MTO (materials take-off)'}
          </button>
          <span className="text-[11px] text-apple-muted">
            Filled from the brief above; quantities come from the uploaded material list.
          </span>
        </div>
        {error && (
          <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}
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

  async function handleCreateSow() {
    if (!revisionName.trim()) {
      setError('Enter a revision name (e.g. Rev-0).');
      return;
    }
    const res = await run('sow-create', () =>
      createSowRevision(project.id, {
        revision_name: revisionName,
        scope_text: scopeText,
        procore_comments: procoreComments || null,
      }),
    );
    if (res) {
      setRevisionName('');
      setScopeText('');
      setProcoreComments('');
    }
  }

  async function handleSowStatus(sowId: number, status: 'draft' | 'in_review' | 'approved') {
    await run(`sow-status-${sowId}-${status}`, () => updateSowStatus(project.id, sowId, status));
  }

  async function handleAddBoq() {
    if (!boqDraft.item_code.trim() || !boqDraft.description.trim()) {
      setError('Item code and description are required.');
      return;
    }
    const res = await run('boq-add', () =>
      addBoqItem(project.id, {
        trade: boqDraft.trade,
        item_code: boqDraft.item_code.trim(),
        description: boqDraft.description.trim(),
        unit: boqDraft.unit.trim() || undefined,
        quantity: boqDraft.quantity ? Number(boqDraft.quantity) : undefined,
        unit_rate: boqDraft.unit_rate ? Number(boqDraft.unit_rate) : undefined,
        supplier_lead_time_days: boqDraft.supplier_lead_time_days
          ? Number(boqDraft.supplier_lead_time_days)
          : null,
      }),
    );
    if (res) {
      setBoqDraft({
        trade: boqDraft.trade,
        item_code: '',
        description: '',
        unit: boqDraft.unit,
        quantity: '',
        unit_rate: '',
        supplier_lead_time_days: '',
      });
    }
  }

  async function handleExport() {
    setExportMsg(null);
    setBusy('boq-export');
    setError(null);
    try {
      await exportBoqExcel(project.id, project.pr_number);
      setExportMsg('BOQ exported.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed.');
    } finally {
      setBusy(null);
    }
  }

  const boqTotal = boqItems.reduce((sum, i) => sum + (i.total_rate || 0), 0);

  return (
    <section className="p-4 border rounded border-apple-surface text-apple-text space-y-4">
      {/* SOW revisions */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-apple-muted mb-2">
          Scope of Work (SOW)
        </p>
        <p className="text-sm text-apple-muted">
          Rev-0 / Rev-1 / Rev-2 with Procore review comments. Approved SOWs
          gate the MTO stage.
        </p>

        {error && (
          <div className="mb-2">
            <ErrorBox message={error} />
          </div>
        )}

        {canManageSow && (
          <div className="mb-3">
            <div className="grid grid-cols-1 gap-2">
              <div>
                <label className="block text-xs font-medium text-apple-muted">
                  Revision name
                </label>
                <input
                  type="text"
                  value={revisionName}
                  onChange={(e) => setRevisionName(e.target.value)}
                  placeholder="e.g. Rev-0"
                  className="w-full rounded-sm border border-apple-border/50 bg-white px-2 py-1 text-sm text-apple-text placeholder:text-apple-muted focus:border-apple-primary focus:outline-none dark:bg-[#1c1c1e] dark:text-apple-text"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-apple-muted">
                  Procore comments (optional)
                </label>
                <input
                  type="text"
                  value={procoreComments}
                  onChange={(e) => setProcoreComments(e.target.value)}
                  placeholder="Reviewer feedback"
                  className="w-full rounded-sm border border-apple-border/50 bg-white px-2 py-1 text-sm text-apple-text placeholder:text-apple-muted focus:border-apple-primary focus:outline-none dark:bg-[#1c1c1e] dark:text-apple-text"
                />
              </div>
            </div>
            <button
              type="button"
              onClick={handleCreateSow}
              disabled={busy !== null}
              className="rounded-sm bg-primary px-2 py-1 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {busy === 'sow-create' ? 'Creating…' : 'Create revision'}
            </button>
          </div>
        )}

        {sowRecords.length === 0 ? (
          <p className="text-sm text-apple-muted">No SOW revisions yet.</p>
        ) : (
          <ul className="text-sm text-apple-text space-y-1">
            {sowRecords.map((sow) => (
              <li key={sow.id} className="border-t border-apple-border/20 py-1">
                <span className="font-medium text-apple-text">{sow.revision_name}</span>
                <span className="text-apple-muted text-xs"> {formatDate(sow.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Proposal review status: draft -> in review -> approved */}
      {canManageSow && latestSow && (
        <div className="rounded border border-apple-border p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-apple-muted">
              Proposal review — {latestSow.revision_name}
            </div>
            <span className="rounded-full bg-apple-surface px-2 py-0.5 text-[11px] font-semibold text-apple-text">
              {latestSow.status === 'approved'
                ? 'Approved (final)'
                : latestSow.status === 'in_review'
                  ? 'In review'
                  : 'Draft'}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              { key: 'draft', label: 'Save as draft' },
              { key: 'in_review', label: 'Send for review' },
              { key: 'approved', label: 'Approve (final)' },
            ].map((s) => (
              <button
                key={s.key}
                type="button"
                disabled={busy !== null || latestSow.status === s.key}
                onClick={() =>
                  void run(`sow-status-${s.key}`, () =>
                    updateSowStatus(project.id, latestSow.id, s.key as 'draft' | 'in_review' | 'approved'),
                  )
                }
                className={
                  latestSow.status === s.key
                    ? 'rounded border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700'
                    : 'rounded border border-apple-border bg-apple-surface px-3 py-1.5 text-xs font-medium text-apple-text hover:bg-apple-surface/70 disabled:opacity-50'
                }
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Trade-wise suggestions from similar archived SOWs */}
      {canManageSow && suggestions.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50/50 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-amber-800">
                Suggested scope — from similar projects in the archive
              </div>
              <p className="text-[11px] text-amber-700">
                Review each line, then add the ones that apply. Nothing is added automatically.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowSuggestions((v) => !v)}
              className="text-[11px] font-medium text-amber-800 underline"
            >
              {showSuggestions ? 'Hide' : 'Show'}
            </button>
          </div>
          {showSuggestions && (
            <div className="space-y-3">
              {suggestions.map((group) => (
                <div key={group.trade}>
                  <div className="text-[11px] font-bold uppercase tracking-wide text-amber-900">
                    {tradeLabelOf(group.trade)}
                  </div>
                  <ul className="mt-1 space-y-1">
                    {group.suggestions.map((s) => (
                      <li
                        key={s.text}
                        className="flex items-start justify-between gap-2 rounded bg-white px-2 py-1.5 dark:bg-white/[0.06]"
                      >
                        <span className="min-w-0 text-xs text-apple-text">
                          {s.text}
                          {s.source_pr && (
                            <span className="ml-1 text-[10px] text-apple-muted">({s.source_pr})</span>
                          )}
                        </span>
                        <button
                          type="button"
                          disabled={busy !== null}
                          onClick={() => void acceptSuggestion(group.trade, s.text)}
                          className="shrink-0 rounded bg-primary px-2 py-0.5 text-[11px] font-semibold text-white disabled:opacity-50"
                        >
                          + Add
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Live preview of the SOW as it will be generated */}
      <div className="rounded border border-apple-border p-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-xs font-semibold uppercase tracking-wider text-apple-muted">
            Live preview — Scope of Work
          </div>
          <button
            type="button"
            onClick={() => setShowPreview((v) => !v)}
            className="text-[11px] font-medium text-apple-muted underline"
          >
            {showPreview ? 'Hide' : 'Show'}
          </button>
        </div>
        {/* Document preview: stays a white "paper" sheet in both themes, so the
            text colour is fixed dark rather than theme-driven. */}
        {showPreview && (
          <div className="paper-surface rounded bg-white p-4 text-gray-900">
            <div className="text-base font-bold">SCOPE OF WORK</div>
            <div className="mt-0.5 text-xs font-semibold">
              PR # {project.pr_number} &nbsp;|&nbsp; EAR # {project.ear_number ?? '—'} &nbsp;|&nbsp;{' '}
              {latestSow?.revision_name ?? 'Rev-0'}
            </div>
            <div className="text-xs">{project.title}</div>
            <div className="text-xs">LOCATION: {project.location ?? '—'}</div>
            <div className="mt-2 text-sm font-bold">1. Introduction</div>
            <p className="text-xs text-apple-muted">
              King Abdullah University of Science &amp; Technology (KAUST) intends to avail the
              services of the In-House Projects team for the subject scope.
            </p>
            <div className="mt-2 text-sm font-bold">2. Scope of Work</div>
            {Object.keys(previewByTrade).length === 0 && (
              <p className="text-xs italic text-apple-muted">
                No lines yet — add from the suggestions above or enter items below.
              </p>
            )}
            {Object.entries(previewByTrade).map(([trade, items], i) => (
              <div key={trade} className="mt-2">
                <div className="text-xs font-bold">
                  2.{i + 1} {tradeLabelOf(trade)}
                </div>
                <ul className="ml-4 list-disc text-xs">
                  {items.map((it) => (
                    <li key={it.id}>
                      {it.description}
                      {it.quantity || it.unit ? (
                        <span className="text-apple-muted">
                          {' '}
                          — {it.quantity ?? ''} {it.unit ?? ''}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* BOQ / Design MTO */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-apple-muted mb-2">
          Design BOQ / MTO
        </p>
        <p className="text-sm text-apple-muted">
          Design-stage line items. Reconciled against the construction MTO at
          the start of construction.
        </p>

        {exportMsg && (
          <div className="mb-2 rounded-sm border border-emerald-200 bg-emerald-50/50 p-2 text-xs text-emerald-800">
            {exportMsg}
          </div>
        )}

        {canManageBoq && (
          <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
            <select
              value={boqDraft.trade}
              onChange={(e) => setBoqDraft((p) => ({ ...p, trade: e.target.value }))}
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            >
              {TRADES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={boqDraft.item_code}
              onChange={(e) => setBoqDraft((p) => ({ ...p, item_code: e.target.value }))}
              placeholder="Item code"
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            />
            <input
              type="text"
              value={boqDraft.description}
              onChange={(e) => setBoqDraft((p) => ({ ...p, description: e.target.value }))}
              placeholder="Description"
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            />
            <input
              type="text"
              value={boqDraft.unit}
              onChange={(e) => setBoqDraft((p) => ({ ...p, unit: e.target.value }))}
              placeholder="Unit"
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            />
            <input
              type="number"
              min={0}
              value={boqDraft.quantity}
              onChange={(e) => setBoqDraft((p) => ({ ...p, quantity: e.target.value }))}
              placeholder="Qty"
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            />
            <input
              type="number"
              min={0}
              value={boqDraft.unit_rate}
              onChange={(e) => setBoqDraft((p) => ({ ...p, unit_rate: e.target.value }))}
              placeholder="Unit rate (SAR)"
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            />
            <input
              type="number"
              min={0}
              value={boqDraft.supplier_lead_time_days}
              onChange={(e) => setBoqDraft((p) => ({ ...p, supplier_lead_time_days: e.target.value }))}
              placeholder="Lead time (days)"
              className="rounded-sm border border-apple-border/50 px-2 py-1 text-sm"
            />
            <button
              type="button"
              onClick={handleAddBoq}
              disabled={busy !== null}
              className="rounded-sm bg-primary px-2 py-1 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {busy === 'boq-add' ? 'Adding…' : 'Add'}
            </button>
          </div>
        )}

        {boqItems.length === 0 ? (
          <p className="text-sm text-apple-muted">No BOQ line items yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="text-sm text-apple-text">
              <thead className="text-apple-muted text-xs uppercase">
                <tr>
                  <th className="px-3 py-2">Trade</th>
                  <th className="px-3 py-2">Code</th>
                  <th className="px-3 py-2">Description</th>
                  <th className="px-3 py-2 text-center">Qty</th>
                  <th className="px-3 py-2 text-right">Unit (SAR)</th>
                  <th className="px-3 py-2 text-right">Total (SAR)</th>
                  <th className="px-3 py-2 text-center">Lead (d)</th>
                </tr>
              </thead>
              <tbody>
                {boqItems.map((item) => (
                  <tr key={item.id} className="border-b border-apple-border/20">
                    <td className="px-3 py-2">{item.trade}</td>
                    <td className="px-3 py-2 font-mono text-apple-text">{item.item_code}</td>
                    <td className="px-3 py-2">{item.description}</td>
                    <td className="px-3 py-2 text-center">{item.quantity}</td>
                    <td className="px-3 py-2 text-right">{item.unit_rate}</td>
                    <td className="px-3 py-2 text-right font-medium">{item.total_rate?.toFixed(2)} SAR</td>
                    <td className="px-3 py-2 text-center">{item.supplier_lead_time_days ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={7} className="px-3 py-2 text-right text-xs font-semibold uppercase text-apple-muted">
                    Total
                  </td>
                  <td className="px-3 py-2 text-right text-sm font-semibold text-apple-text">
                    {boqTotal.toFixed(2)} SAR
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}