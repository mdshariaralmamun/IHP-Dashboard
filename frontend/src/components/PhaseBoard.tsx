'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import ErrorBox from '@/components/ErrorBox';
import { ApiError, getBoard, setSummaryStatus, updateProject } from '@/lib/api';
import type { Board, BoardRow } from '@/lib/api';
import StageBadge from '@/components/StageBadge';

const STATUS_STYLES: Record<string, string> = {
  none: 'bg-slate-100 text-slate-600 ring-slate-300',
  draft: 'bg-amber-100 text-amber-800 ring-amber-300',
  sent: 'bg-blue-100 text-blue-800 ring-blue-300',
  acknowledged: 'bg-emerald-100 text-emerald-800 ring-emerald-300',
  disputed: 'bg-red-100 text-red-800 ring-red-300',
  done: 'bg-emerald-100 text-emerald-800 ring-emerald-300',
};

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
 * The EAR / Design / Procore board.
 *
 * Every row answers one question: whose move is it? A document that is missing
 * or still a draft is OUR move - those rows blink, because that is today's
 * work. A sent document is the PI's move; all we can do is follow up. Each row
 * carries the assign-to box, the follow-up note, a mailto that pre-writes what
 * is needed, and the design dates.
 */
export default function PhaseBoard({ phase }: { phase: 'ear' | 'design' | 'procore' }) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [onlyMine, setOnlyMine] = useState(false);

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

  const rows = (board?.rows ?? []).filter((r) => (onlyMine ? r.my_court : true));

  return (
    <div>
      {error && <ErrorBox message={error} onRetry={load} />}
      {!board && !error && <p className='text-sm text-apple-muted'>Loading…</p>}

      {board && (
        <>
          <div className='mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6'>
            <Tile label='In this phase' value={board.counts.total} />
            <Tile label='MY COURT (blink)' value={board.counts.my_court} accent='red' />
            <Tile label='MOM sent' value={board.counts.mom_sent} accent='blue' />
            <Tile label='MOM to send' value={board.counts.mom_pending_send} accent='amber' />
            <Tile label='Summary sent' value={board.counts.summary_sent} accent='blue' />
            <Tile label='Summary to send' value={board.counts.summary_pending_send} accent='amber' />
          </div>

          <label className='mb-3 flex items-center gap-2 text-xs text-apple-text'>
            <input
              type='checkbox'
              checked={onlyMine}
              onChange={(e) => setOnlyMine(e.target.checked)}
            />
            Only show what is in OUR court
          </label>

          {rows.length === 0 ? (
            <p className='rounded-lg border border-apple-border bg-apple-surface p-8 text-center text-sm text-apple-muted'>
              Nothing here.
            </p>
          ) : (
            <div className='space-y-2'>
              {rows.map((row) => (
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
        </>
      )}
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
      <div className='flex flex-wrap items-center gap-2'>
        <Link
          href={'/projects/' + row.id}
          className='font-mono text-sm font-bold text-apple-text hover:underline'
        >
          {row.pr_number}
        </Link>
        <span className='text-sm text-apple-text'>{row.title}</span>
        <StageBadge stage={row.stage} />
        {row.my_court ? (
          <span className='rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold text-white'>
            MY COURT — {row.next_action}
          </span>
        ) : row.waiting_on ? (
          <span className='rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-800 ring-1 ring-inset ring-blue-300'>
            WAITING ON {row.waiting_on}
          </span>
        ) : (
          <span className='rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800'>
            DONE
          </span>
        )}
        <span className='ml-auto text-xs text-apple-muted'>
          PI: {row.pi_name ?? '—'} · {row.location ?? '—'}
          {row.finish_date ? ' · ETC ' + row.finish_date : ''}
        </span>
      </div>

      <div className='mt-2 flex flex-wrap items-center gap-2'>
        <DocChip label='MOM' doc={row.mom} />
        <DocChip label='Summary' doc={row.summary} />
        <button
          type='button'
          onClick={() => void onCycleSummary(row)}
          disabled={busy}
          className='rounded border border-apple-border px-2 py-0.5 text-[10px] font-semibold text-apple-text hover:bg-apple-surface/70 disabled:opacity-50'
          title='draft → sent → acknowledged'
        >
          Advance summary
        </button>
        <a
          href={mailto}
          className='rounded border border-apple-border px-2 py-0.5 text-[10px] font-semibold text-apple-text hover:bg-apple-surface/70'
        >
          ✉ Email PI
        </a>
      </div>

      <div className='mt-2 grid gap-2 sm:grid-cols-[200px_1fr]'>
        <input
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          onBlur={() => owner !== (row.owner_username ?? '') && onPatch(row, { owner_username: owner || null })}
          placeholder='Assign to (engineer)'
          className='rounded border border-apple-border bg-apple-surface px-2 py-1 text-xs'
        />
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={() => note !== (row.followup_note ?? '') && onPatch(row, { followup_note: note || null })}
          placeholder='Follow-up note — what to do / current situation & reason'
          className='rounded border border-apple-border bg-apple-surface px-2 py-1 text-xs'
        />
      </div>
      {row.followup_note && (
        <p className='mt-1 text-[11px] text-apple-muted'>Note: {row.followup_note}</p>
      )}
    </div>
  );
}

function Tile({ label, value, accent }: { label: string; value: number; accent?: string }) {
  const cls: Record<string, string> = {
    red: 'text-red-700', blue: 'text-blue-700', amber: 'text-amber-700',
  };
  return (
    <div className='rounded-lg border border-apple-border bg-apple-surface p-3 shadow-sm'>
      <div className={'text-2xl font-bold tabular-nums ' + (accent ? cls[accent] : 'text-apple-text')}>
        {value}
      </div>
      <div className='mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-apple-muted'>
        {label}
      </div>
    </div>
  );
}
