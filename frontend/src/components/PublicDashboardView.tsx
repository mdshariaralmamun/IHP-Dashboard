'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getPublicDashboard, type PublicDashboard } from '@/lib/api';

/** Colours per division, matching the internal dashboards. */
const DIVISION_COLOURS: Record<string, string> = {
  EAR: '#0A84FF',
  Design: '#5E5CE6',
  Construction: '#FF9F0A',
  'Close-up': '#30D158',
  Unassigned: '#8E8E93',
};

const WINDOW_TILES: { key: keyof PublicDashboard['windows']; label: string; accent: string }[] = [
  { key: 'overdue', label: 'Overdue', accent: 'text-red-600 dark:text-red-400' },
  { key: 'this_week', label: 'Due this week', accent: 'text-amber-600 dark:text-amber-400' },
  { key: 'on_hold', label: 'On hold', accent: 'text-orange-600 dark:text-orange-400' },
  { key: 'high_risk', label: 'High risk', accent: 'text-rose-600 dark:text-rose-400' },
  { key: 'behind_plan', label: 'Behind plan', accent: 'text-purple-600 dark:text-purple-400' },
  { key: 'design_gate', label: 'Design gates', accent: 'text-blue-600 dark:text-blue-400' },
];

const STAGE_LABELS: Record<string, string> = {
  INTAKE: 'Intake',
  MOM_SENT: 'MOM sent',
  MOM_CONFIRMED: 'MOM confirmed',
  DISPOSITION: 'Disposition',
  EAR_DRAFT: 'EAR draft',
  EAR_REVIEW: 'EAR review',
  EAR_APPROVED: 'EAR approved',
  SOW_DRAFT: 'SOW draft',
  SOW_REVIEW: 'SOW review',
  SOW_APPROVED: 'SOW approved',
  MTO_DRAFT: 'MTO draft',
  MTO_APPROVED: 'MTO approved',
  PROCUREMENT: 'Procurement',
  WORK_PERMIT: 'Work permit',
  CONSTRUCTION: 'Construction',
  CLOSEOUT: 'Closeout',
  PUNCH_LIST: 'Punch list',
  ICR_DONE: 'ICR done',
};

/**
 * Public, read-only portfolio overview.
 *
 * Deliberately aggregate-only: counts by division and stage plus delay
 * counters. No PR numbers, names, locations or documents are shown, and the
 * only action available is asking for access.
 */
export default function PublicDashboardView() {
  const [data, setData] = useState<PublicDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPublicDashboard()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load the overview'));
  }, []);

  const divisions = data
    ? Object.entries(data.by_division).map(([name, value]) => ({ name, value }))
    : [];
  const stages = data
    ? Object.entries(data.by_stage)
        .map(([name, value]) => ({ name: STAGE_LABELS[name] ?? name, value }))
        .sort((a, b) => b.value - a.value)
    : [];

  return (
    <div className="min-h-screen bg-apple-bg text-apple-text">
      <header className="border-b border-apple-border/60 bg-white/70 backdrop-blur-xl dark:bg-[#161618]/80">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4">
          <div className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/kaust_logo.png" alt="KAUST" className="h-9" />
            <div>
              <p className="text-sm font-semibold leading-tight">
                IHP Project Delivery Platform
              </p>
              <p className="text-[11px] text-apple-muted">
                Infrastructure &amp; Housing Projects · read-only overview
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/login"
              className="hidden rounded-full border border-apple-border px-4 py-2 text-sm font-medium text-apple-text transition hover:bg-black/5 sm:block dark:hover:bg-white/10"
            >
              Sign in
            </Link>
            <Link
              href="/request-access"
              className="rounded-full bg-primary px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:opacity-90"
            >
              Request access
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-8">
        <div className="mb-6">
          <h1 className="text-3xl font-bold tracking-tight">Portfolio overview</h1>
          <p className="mt-1 text-sm text-apple-muted">
            Aggregate progress across every live project. Detailed records are available to
            approved users only.
          </p>
        </div>

        {error && (
          <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
            {error}
          </p>
        )}

        {!data && !error && (
          <p className="py-16 text-center text-sm text-apple-muted">Loading overview…</p>
        )}

        {data && (
          <>
            <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <Kpi label="Projects" value={data.totals.projects} tone="text-apple-text" />
              {Object.entries(data.by_division).map(([division, value]) => (
                <Kpi
                  key={division}
                  label={division}
                  value={value}
                  tone="text-apple-text"
                  dot={DIVISION_COLOURS[division] ?? '#8E8E93'}
                />
              ))}
            </section>

            <section className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {WINDOW_TILES.map((tile) => (
                <div
                  key={tile.key}
                  className="rounded-xl border border-apple-border bg-white p-3 dark:bg-white/[0.04]"
                >
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-apple-muted">
                    {tile.label}
                  </p>
                  <p className={'mt-1 text-2xl font-bold ' + tile.accent}>
                    {data.windows[tile.key]}
                  </p>
                </div>
              ))}
            </section>

            <section className="mt-6 grid gap-4 lg:grid-cols-2">
              <Card title="Projects by division">
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={divisions}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={60}
                      outerRadius={100}
                      paddingAngle={2}
                    >
                      {divisions.map((entry) => (
                        <Cell
                          key={entry.name}
                          fill={DIVISION_COLOURS[entry.name] ?? '#8E8E93'}
                        />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-2 flex flex-wrap justify-center gap-3">
                  {divisions.map((entry) => (
                    <span key={entry.name} className="flex items-center gap-1.5 text-xs">
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ background: DIVISION_COLOURS[entry.name] ?? '#8E8E93' }}
                      />
                      {entry.name} · {entry.value}
                    </span>
                  ))}
                </div>
              </Card>

              <Card title="Workflow stage distribution">
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={stages} layout="vertical" margin={{ left: 12, right: 12 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                    <XAxis type="number" tick={{ fontSize: 11 }} />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={110}
                      tick={{ fontSize: 11 }}
                    />
                    <Tooltip />
                    <Bar dataKey="value" fill="var(--color-primary)" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </section>

            <section className="mt-6 rounded-xl border border-apple-border bg-white p-5 dark:bg-white/[0.04]">
              <h2 className="text-sm font-semibold">Need the full picture?</h2>
              <p className="mt-1 text-sm text-apple-muted">
                Project registers, minutes, EAR/SOW documents and the construction board are
                behind a personal account. Request access and an administrator will send you a
                private link.
              </p>
              <Link
                href="/request-access"
                className="mt-3 inline-block rounded-full bg-primary px-5 py-2 text-sm font-semibold text-white transition hover:opacity-90"
              >
                Request access
              </Link>
            </section>

            <p className="mt-6 text-center text-[11px] text-apple-muted">
              Read-only overview · generated {data.generated_at}
              {data.planner_sync ? ' · Planner sync ' + data.planner_sync : ''}
            </p>
          </>
        )}
      </main>
    </div>
  );
}

function Kpi({
  label,
  value,
  tone,
  dot,
}: {
  label: string;
  value: number;
  tone: string;
  dot?: string;
}) {
  return (
    <div className="rounded-xl border border-apple-border bg-white p-4 dark:bg-white/[0.04]">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-apple-muted">
        {dot && <span className="h-2 w-2 rounded-full" style={{ background: dot }} />}
        {label}
      </p>
      <p className={'mt-1 text-3xl font-bold ' + tone}>{value}</p>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-apple-border bg-white p-4 dark:bg-white/[0.04]">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </div>
  );
}
