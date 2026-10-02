'use client';

import { useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import StageBadge from '@/components/StageBadge';
import { getAreaReport } from '@/lib/api';
import type { AreaProjectRow, AreaReport } from '@/lib/api';
import { useUser } from '@/lib/useUser';

/**
 * Area-wise tracking: one location, the whole story.
 *
 * Type a room code (5-3610, 5-4910) or the shorthand (B5 L3 A1) and see the
 * building it resolves to, the PI working there now, the PIs who were there
 * before, and every project the area has carried - active and finished - with
 * the pins on the plan marking the spots.
 */
export default function AreasPage() {
  return (
    <AuthGuard>
      <AreasView />
    </AuthGuard>
  );
}

function AreasView() {
  const { user } = useUser();
  const [query, setQuery] = useState('');
  const [report, setReport] = useState<AreaReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await getAreaReport(query.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lookup failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-6xl space-y-5 px-4 py-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-apple-text">Areas &amp; labs</h1>
          <p className="mt-1 text-sm text-apple-muted">
            A room code or area, and everyone who has ever worked in it: the current PI, the
            previous ones, and the projects the area has carried.
          </p>
        </div>

        <form onSubmit={search} className="flex flex-wrap gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. 5-3610, 3-2610, or B5 L3 A1"
            className="min-w-[260px] flex-1 rounded-md border border-apple-border bg-apple-surface px-3 py-2 text-sm text-apple-text"
          />
          <button
            type="submit"
            disabled={busy || !query.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {busy ? 'Looking…' : 'Show the area'}
          </button>
        </form>

        {error && <ErrorBox message={error} onRetry={() => void search()} />}

        {report?.ok === false && report.error && (
          <ErrorBox message={report.error} />
        )}

        {report?.ok && (
          <>
            <div className="rounded-xl border border-apple-border bg-apple-surface p-5 shadow-sm">
              <h2 className="text-lg font-bold text-apple-text">{report.described}</h2>
              <div className="mt-3 grid gap-3 sm:grid-cols-4">
                <Tile label="Active now" value={report.active_count ?? 0} accent="blue" />
                <Tile label="Finished here" value={report.finished_count ?? 0} accent="emerald" />
                <Tile label="Current PI" value={report.current_pis?.length ?? 0} accent="amber" />
                <Tile label="Previous PI" value={report.previous_pis?.length ?? 0} accent="slate" />
              </div>
              {(report.current_pis?.length ?? 0) > 0 && (
                <p className="mt-3 text-sm text-apple-text">
                  <span className="font-semibold">Working here now: </span>
                  {report.current_pis!.join(', ')}
                </p>
              )}
              {(report.previous_pis?.length ?? 0) > 0 && (
                <p className="mt-1 text-sm text-apple-muted">
                  <span className="font-semibold">Previously: </span>
                  {report.previous_pis!.join(', ')}
                </p>
              )}
            </div>

            <ProjectTable title="Active projects" rows={report.active_projects ?? []} />
            <ProjectTable title="Finished projects" rows={report.finished_projects ?? []} />
          </>
        )}
      </main>
    </div>
  );
}

function Tile({ label, value, accent }: { label: string; value: number; accent: string }) {
  const cls: Record<string, string> = {
    blue: 'text-blue-700', emerald: 'text-emerald-700',
    amber: 'text-amber-700', slate: 'text-apple-text',
  };
  return (
    <div className="rounded-lg border border-apple-border bg-apple-surface/50 p-3">
      <div className={`text-2xl font-bold tabular-nums ${cls[accent]}`}>{value}</div>
      <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-apple-muted">
        {label}
      </div>
    </div>
  );
}

function ProjectTable({ title, rows }: { title: string; rows: AreaProjectRow[] }) {
  if (!rows.length) return null;
  return (
    <div className="rounded-xl border border-apple-border bg-apple-surface shadow-sm">
      <div className="border-b border-apple-border px-4 py-2 text-xs font-semibold uppercase tracking-wide text-apple-muted">
        {title} ({rows.length})
      </div>
      <table className="min-w-full divide-y divide-apple-border text-sm">
        <tbody className="divide-y divide-apple-border">
          {rows.map((row) => (
            <tr key={row.id} className="hover:bg-apple-surface/50">
              <td className="px-4 py-2 font-mono text-xs font-semibold text-apple-text">
                <Link href={`/projects/${row.id}`} className="hover:underline">
                  {row.pr_number}
                </Link>
              </td>
              <td className="px-4 py-2 text-apple-text">{row.title}</td>
              <td className="px-4 py-2 text-xs text-apple-muted">{row.pi_name ?? '—'}</td>
              <td className="px-4 py-2"><StageBadge stage={row.stage} /></td>
              <td className="px-4 py-2 text-xs text-apple-muted">{row.finish ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
