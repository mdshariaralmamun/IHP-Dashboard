'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import ErrorBox from '@/components/ErrorBox';
import StageBadge from '@/components/StageBadge';
import { ApiError, getBoard, setSummaryStatus, updateProject } from '@/lib/api';
import type { Board, BoardRow } from '@/lib/api';
import {
  BarList,
  Donut,
  KpiCard,
  PbiCanvas,
  SlicerBar,
  VisualCard,
} from '@/components/powerbi/PowerBI';

const STATUS_STYLES: Record<string, string> = {
  none: 'bg-slate-100 text-slate-600 ring-slate-300',
  draft: 'bg-amber-100 text-amber-800 ring-amber-300',
  sent: 'bg-blue-100 text-blue-800 ring-blue-300',
  acknowledged: 'bg-emerald-100 text-emerald-800 ring-emerald-300',
  disputed: 'bg-red-100 text-red-800 ring-red-300',
  done: 'bg-emerald-100 text-emerald-800 ring-emerald-300',
};

/** Does a row survive the page's current cross-filter? */
function passes(row: BoardRow, filter: string | null): boolean {
  if (!filter) return true;
  if (filter === 'my_court') return row.my_court;
  if (filter === 'pi_court') return !row.my_court && !!row.waiting_on;
  if (filter === 'done') return !row.my_court && !row.waiting_on;
  if (filter === 'unassigned') return !row.owner_username;
  if (filter === 'mom_sent') return row.mom.status === 'sent';
  if (filter === 'mom_acknowledged') return row.mom.status === 'acknowledged';
  if (filter === 'mom_pending_send') return row.mom.status === 'none' || row.mom.status === 'draft';
  if (filter === 'summary_sent') return row.summary.status === 'sent';
  if (filter === 'summary_acknowledged') return row.summary.status === 'acknowledged';
  if (filter === 'summary_pending_send')
    return row.summary.status === 'none' || row.summary.status === 'draft';
  if (filter.indexOf('wait:') === 0) return (row.waiting_on ?? '') === filter.slice(5);
  if (filter.indexOf('owner:') === 0) return (row.owner_username ?? '') === filter.slice(6);
  return true;
}

function DocChip({ label, doc }: { label: string; doc: BoardRow['mom'] }) {
  const style = STATUS_STYLES[doc.status] ?? STATUS_STYLES.none;
  return (
    <span
      title={doc.action ?? label}
      className={'inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset ' + style}
    >
      {label}: {doc.status}
      {doc.court === 'IHP' ? ' ★' : ''}
    </span>
  );
}

/**
 * The EAR / Design / Procore board, laid out as a cross-filtering dashboard.
 *
 * Every visual answers one question: whose move is it? A document that is
 * missing or still a draft is OUR move - those rows blink, because that is
 * today's work. Clicking a KPI, a slice, a bar or a chip narrows the whole
 * page around that selection; clicking it again clears it.
 */
export default function PhaseBoard({ phase }: { phase: 'ear' | 'design' | 'procore' }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState('');

  const load = useCallback(() => {
    getBoard(phase)
      .then(setBoard)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'));
  }, [phase]);

  useEffect(load, [load]);

  async function patch(row: BoardRow, fields: Record<string, string | null>) {
    setBusy(row.id);
    setError(null);
    try {
      await updateProject(row.id, fields);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not save.');
    } finally {
      setBusy(null);
    }
  }

  async function cycleSummary(row: BoardRow) {
    setBusy(row.id);
    try {
      const next =
        !row.summary_status || row.summary_status === 'none'
          ? 'draft'
          : row.summary_status === 'draft'
            ? 'sent'
            : row.summary_status === 'sent'
              ? 'acknowledged'
              : 'draft';
      await setSummaryStatus(row.id, next);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update the summary.');
    } finally {
      setBusy(null);
    }
  }

  const all = board?.rows ?? [];
  const counts = board?.counts;

  const courtSlices = useMemo(() => {
    const ihp = all.filter((r) => r.my_court).length;
    const pi = all.filter((r) => !r.my_court && !!r.waiting_on).length;
    const done = all.length - ihp - pi;
    return [
      { key: 'my_court', label: 'Our court', value: ihp, color: '#D64550' },
      { key: 'pi_court', label: 'With the PI', value: pi, color: '#118DFF' },
      { key: 'done', label: 'Complete', value: done, color: '#1AAB40' },
    ].filter((s) => s.value > 0);
  }, [all]);

  const waitingBars = useMemo(() => {
    const c: Record<string, number> = {};
    all.forEach((r) => {
      if (!r.waiting_on) return;
      c[r.waiting_on] = (c[r.waiting_on] ?? 0) + 1;
    });
    return Object.entries(c)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 7)
      .map(([label, value], i) => ({
        key: 'wait:' + label,
        label,
        value,
        color: ['#118DFF', '#12239E', '#E66C37', '#6B007B', '#E044A7', '#744EC2', '#D9B300'][i % 7],
      }));
  }, [all]);

  const ownerBars = useMemo(() => {
    const c: Record<string, number> = {};
    all.forEach((r) => {
      if (!r.owner_username) return;
      c[r.owner_username] = (c[r.owner_username] ?? 0) + 1;
    });
    const bars = Object.entries(c)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 7)
      .map(([label, value], i) => ({
        key: 'owner:' + label,
        label,
        value,
        color: ['#197278', '#1AAB40', '#118DFF', '#744EC2', '#D9B300'][i % 5],
      }));
    const unassigned = all.filter((r) => !r.owner_username).length;
    if (unassigned > 0) {
      bars.push({ key: 'unassigned', label: 'Unassigned', value: unassigned, color: '#D64550' });
    }
    return bars;
  }, [all]);

  const toggle = (key: string) =>
    setSelected((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  const active = (key: string) => selected.includes(key);

  const q = query.trim().toLowerCase();
  const visible = all
    .filter((r) => selected.every((f) => passes(r, f)))
    .filter((r) =>
      !q
        ? true
        : (r.pr_number + ' ' + r.title + ' ' + (r.pi_name ?? '') + ' ' + (r.location ?? ''))
            .toLowerCase()
            .indexOf(q) >= 0,
    );

  const clearAll = () => {
    setSelected([]);
    setQuery('');
  };

  if (!board) {
    return (
      <div>
        {error ? <ErrorBox message={error} onRetry={load} /> : (
          <p className="text-sm text-apple-muted">Loading…</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && <ErrorBox message={error} onRetry={load} />}

      <PbiCanvas>
        {/* --- KPI strip: every card cross-filters the page --- */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <KpiCard
            label="In this phase"
            value={counts?.total ?? 0}
            hint="live projects"
            accent="navy"
            active={selected.length === 0}
            onClick={clearAll}
          />
          <KpiCard
            label="My court"
            value={counts?.my_court ?? 0}
            hint="we must act"
            accent="red"
            icon="⚡"
            active={active('my_court')}
            onClick={() => toggle('my_court')}
          />
          <KpiCard
            label="MOM sent"
            value={counts?.mom_sent ?? 0}
            hint="with the PI"
            accent="blue"
            active={active('mom_sent')}
            onClick={() => toggle('mom_sent')}
          />
          <KpiCard
            label="MOM to send"
            value={counts?.mom_pending_send ?? 0}
            hint="not sent yet"
            accent="orange"
            active={active('mom_pending_send')}
            onClick={() => toggle('mom_pending_send')}
          />
          <KpiCard
            label="Summary sent"
            value={counts?.summary_sent ?? 0}
            hint="EAR summary"
            accent="teal"
            active={active('summary_sent')}
            onClick={() => toggle('summary_sent')}
          />
          <KpiCard
            label="Summary to send"
            value={counts?.summary_pending_send ?? 0}
            hint="needs sending"
            accent="gold"
            active={active('summary_pending_send')}
            onClick={() => toggle('summary_pending_send')}
          />
        </div>

        {/* --- Slicers --- */}
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200/80 bg-white p-2.5 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
          <SlicerBar
            label="Court"
            items={[
              { key: 'my_court', label: 'Our court', value: counts?.my_court ?? 0, color: '#D64550' },
              { key: 'pi_court', label: 'With the PI' },
              { key: 'done', label: 'Complete' },
              { key: 'unassigned', label: 'Unassigned' },
            ]}
            selected={selected}
            onToggle={toggle}
            onClear={() => setSelected([])}
          />
          <span className="hidden h-5 w-px bg-slate-200 dark:bg-white/10 sm:block" />
          <SlicerBar
            label="Docs"
            items={[
              { key: 'mom_acknowledged', label: 'MOM ack.', value: counts?.mom_acknowledged ?? 0 },
              {
                key: 'summary_acknowledged',
                label: 'Summary ack.',
                value: counts?.summary_acknowledged ?? 0,
              },
            ]}
            selected={selected}
            onToggle={toggle}
            onClear={() => setSelected([])}
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search PR, title, PI, location…"
            className="ml-auto w-full max-w-xs rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-apple-text outline-none focus:border-primary dark:border-white/10 dark:bg-white/5"
          />
        </div>

        {/* --- Visual grid --- */}
        <div className="mt-3 grid gap-3 lg:grid-cols-[1.1fr_1fr_1fr]">
          <VisualCard title="Whose court is it" subtitle="click a slice to filter">
            <Donut items={courtSlices} selected={selected} onSelect={toggle} centerLabel="projects" />
          </VisualCard>
          <VisualCard
            title="Waiting on"
            subtitle={waitingBars.length ? 'who we are blocked by' : 'nothing is blocked'}
          >
            <BarList items={waitingBars} selected={selected} onSelect={toggle} />
          </VisualCard>
          <VisualCard title="Assigned engineers" subtitle="workload on this phase">
            <BarList items={ownerBars} selected={selected} onSelect={toggle} />
          </VisualCard>
        </div>

        {/* --- The working list --- */}
        <VisualCard
          className="mt-3"
          title={'Action list — ' + visible.length + ' of ' + all.length}
          subtitle={
            selected.length || q
              ? 'filtered' + (selected.length ? ' · ' + selected.join(', ') : '') + (q ? ' · "' + query + '"' : '')
              : 'every live project in this phase'
          }
          actions={
            (selected.length > 0 || q) && (
              <button
                type="button"
                onClick={clearAll}
                className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-500 hover:bg-slate-50 dark:border-white/10"
              >
                Clear filters
              </button>
            )
          }
        >
          {visible.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 p-8 text-center text-sm text-slate-400">
              Nothing matches this selection.
            </p>
          ) : (
            <div className="space-y-2">
              {visible.map((row) => (
                <Row
                  key={row.id}
                  row={row}
                  busy={busy === row.id}
                  onPatch={patch}
                  onCycleSummary={cycleSummary}
                />
              ))}
            </div>
          )}
        </VisualCard>
      </PbiCanvas>
    </div>
  );
}

function Row({
  row, busy, onPatch, onCycleSummary,
}: {
  row: BoardRow;
  busy: boolean;
  onPatch: (row: BoardRow, fields: Record<string, string | null>) => void;
  onCycleSummary: (row: BoardRow) => void;
}) {
  const [owner, setOwner] = useState(row.owner_username ?? '');
  const [note, setNote] = useState(row.followup_note ?? '');

  const subject = row.pr_number + ' — ' + (row.next_action ?? 'status');
  const body =
    'Dear ' + (row.pi_name ?? 'Professor') + ',\n\n' +
    row.our_moves.map((m) => '- ' + m).join('\n') +
    '\n\nKind regards,\nIHP Design and Construction';
  const mailto =
    'mailto:' + (row.pi_email ?? '') +
    '?subject=' + encodeURIComponent(subject) +
    '&body=' + encodeURIComponent(body);

  return (
    <div
      className={'rounded-lg border p-4 shadow-sm ' + (
        row.my_court
          ? 'animate-pulse border-red-300 bg-red-50/60'
          : 'border-apple-border bg-apple-surface'
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={'/projects/' + row.id}
          className="font-mono text-sm font-bold text-apple-text hover:underline"
        >
          {row.pr_number}
        </Link>
        <span className="text-sm text-apple-text">{row.title}</span>
        <StageBadge stage={row.stage} />
        {row.my_court ? (
          <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold text-white">
            MY COURT — {row.next_action}
          </span>
        ) : row.waiting_on ? (
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-800 ring-1 ring-inset ring-blue-300">
            WAITING ON {row.waiting_on}
          </span>
        ) : (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
            DONE
          </span>
        )}
        <span className="ml-auto text-xs text-apple-muted">
          PI: {row.pi_name ?? '—'} · {row.location ?? '—'}
          {row.finish_date ? ' · ETC ' + row.finish_date : ''}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <DocChip label="MOM" doc={row.mom} />
        <DocChip label="Summary" doc={row.summary} />
        <button
          type="button"
          onClick={() => void onCycleSummary(row)}
          disabled={busy}
          className="rounded border border-apple-border px-2 py-0.5 text-[10px] font-semibold text-apple-text hover:bg-apple-surface/70 disabled:opacity-50"
          title="draft → sent → acknowledged"
        >
          Advance summary
        </button>
        <a
          href={mailto}
          className="rounded border border-apple-border px-2 py-0.5 text-[10px] font-semibold text-apple-text hover:bg-apple-surface/70"
        >
          ✉ Email PI
        </a>
      </div>

      <div className="mt-2 grid gap-2 sm:grid-cols-[200px_1fr]">
        <input
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          onBlur={() => owner !== (row.owner_username ?? '') && onPatch(row, { owner_username: owner || null })}
          placeholder="Assign to (engineer)"
          className="rounded border border-apple-border bg-apple-surface px-2 py-1 text-xs"
        />
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => note !== (row.followup_note ?? '') && onPatch(row, { followup_note: note || null })}
          placeholder="Follow-up note — what to do / current situation & reason"
          className="rounded border border-apple-border bg-apple-surface px-2 py-1 text-xs"
        />
      </div>
      {row.followup_note && (
        <p className="mt-1 text-[11px] text-apple-muted">Note: {row.followup_note}</p>
      )}
    </div>
  );
}
