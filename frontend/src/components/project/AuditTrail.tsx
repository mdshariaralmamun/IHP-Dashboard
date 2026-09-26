import { formatDateTime } from '@/lib/format';
import type { AuditEntry } from '@/lib/types';

function formatDetail(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .map(([key, value]) => {
      const rendered =
        value === null || value === undefined
          ? '—'
          : typeof value === 'object'
            ? JSON.stringify(value)
            : String(value);
      return `${key}: ${rendered}`;
    })
    .join(' · ');
}

export default function AuditTrail({ entries }: { entries: AuditEntry[] }) {
  return (
    <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-apple-muted">
        Audit Trail
      </h2>
      {entries.length === 0 ? (
        <p className="text-sm text-apple-muted">No activity recorded yet.</p>
      ) : (
        <ul className="divide-y divide-apple-border">
          {entries.map((entry) => (
            <li key={entry.id} className="flex flex-wrap items-baseline gap-x-3 py-2.5 text-sm">
              <span className="whitespace-nowrap text-xs text-apple-muted">
                {formatDateTime(entry.created_at)}
              </span>
              <span className="font-medium text-apple-text">{entry.user}</span>
              <span className="text-apple-text">{entry.action}</span>
              {entry.detail && <span className="text-apple-muted">— {formatDetail(entry.detail)}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

