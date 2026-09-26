'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getDashboardStats } from '@/lib/api';
import type { DashboardStats } from '@/lib/types';

export default function DashboardView() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const data = await getDashboardStats();
        setStats(data);
      } catch (e) {
        console.error("Failed to load dashboard stats", e);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  if (loading) {
    return <div className="p-8 text-center text-sm font-medium text-apple-muted animate-pulse">Loading Dashboard Metrics…</div>;
  }

  if (!stats) return null;

  const activeConstruction =
    (stats.by_stage.WORK_PERMIT || 0) + (stats.by_stage.CONSTRUCTION || 0);
  const closedOut = stats.by_stage.CLOSEOUT || 0;
  const inDesign =
    stats.totals.projects -
    activeConstruction -
    closedOut -
    (stats.by_stage.PROCUREMENT || 0);

  const cards = [
    {
      label: 'Total Projects',
      value: stats.totals.projects,
      href: '/projects',
      accent: 'text-apple-text',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
        </svg>
      ),
    },
    {
      label: 'ICR Fast-Track',
      value: stats.by_disposition.ICR || 0,
      href: '/projects?disposition=ICR',
      accent: 'text-orange-500',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      ),
    },
    {
      label: 'Active Construction',
      value: activeConstruction,
      href: '/projects?stage=WORK_PERMIT,CONSTRUCTION',
      accent: 'text-primary',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 21v-7m0-4V3m8 18v-9m0-4V3m8 18v-5m0-4V3M2 14h4m4-6h4m4 8h4" />
        </svg>
      ),
    },
    {
      label: 'Closed Out',
      value: closedOut,
      href: '/projects?stage=CLOSEOUT',
      accent: 'text-status-approved',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
  ];

  return (
    <div className="mb-8 space-y-6">
      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((c) => (
          <Link
            key={c.label}
            href={c.href}
            className="group rounded-2xl border border-apple-border bg-apple-surface/50 p-5 shadow-sm backdrop-blur-md transition-all hover:border-primary hover:shadow-apple-float"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-apple-muted">{c.label}</p>
                <p className={`mt-2 text-3xl font-bold tabular-nums ${c.accent}`}>{c.value}</p>
              </div>
              <span className="text-apple-muted transition-colors group-hover:text-primary">{c.icon}</span>
            </div>
          </Link>
        ))}
      </div>

      {/* Design / procurement context strip */}
      <div className="flex flex-wrap items-center gap-x-8 gap-y-2 rounded-2xl border border-apple-border bg-apple-surface/30 px-5 py-3 text-xs font-medium text-apple-muted backdrop-blur-md">
        <span>
          In design / pre-construction: <strong className="text-apple-text tabular-nums">{Math.max(0, inDesign)}</strong>
        </span>
        <span>
          In procurement: <strong className="text-apple-text tabular-nums">{stats.by_stage.PROCUREMENT || 0}</strong>
        </span>
        <span>
          With EAR number: <strong className="text-apple-text tabular-nums">{stats.totals.ear}</strong>
        </span>
      </div>

      {/* Drill-down Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Disposition Status Table */}
        <div className="rounded-2xl border border-apple-border bg-apple-surface/50 p-6 shadow-sm backdrop-blur-md">
          <h3 className="text-lg font-semibold mb-4 text-apple-text">
            Disposition Status Breakdown
          </h3>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-apple-muted">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">Disposition</th>
                  <th className="px-3 py-2 text-center font-semibold">Count</th>
                  <th className="px-3 py-2 text-right font-semibold">View</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(stats.by_disposition).map(([disposition, count]) => {
                  const label = disposition === 'ICR' ? 'ICR' : disposition === 'PROJECT' ? 'Project' : disposition;
                  return (
                    <tr key={disposition} className="border-b border-apple-border/20 hover:bg-apple-surface/50">
                      <td className="px-3 py-2 font-medium text-apple-text">
                        {label}
                      </td>
                      <td className="px-3 py-2 text-center font-medium">
                        {count}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <a
                          href={`/projects?disposition=${disposition}`}
                          className="text-primary hover:underline text-sm"
                        >
                          View {count} projects
                        </a>
                      </td>
                    </tr>
                  );
                })}
                {Object.keys(stats.by_disposition).length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-3 py-6 text-center text-apple-muted">
                      No disposition data yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Phase Distribution Table */}
        <div className="rounded-2xl border border-apple-border bg-apple-surface/50 p-6 shadow-sm backdrop-blur-md">
          <h3 className="text-lg font-semibold mb-4 text-apple-text">
            Project Lifecycle Distribution
          </h3>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wider text-apple-muted">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">Stage</th>
                  <th className="px-3 py-2 text-center font-semibold">Count</th>
                  <th className="px-3 py-2 text-right font-semibold">View</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(stats.by_stage).map(([stage, count]) => {
                  const label = stage.replace(/_/g, ' ');
                  return (
                    <tr key={stage} className="border-b border-apple-border/20 hover:bg-apple-surface/50">
                      <td className="px-3 py-2 font-medium text-apple-text">
                        {label}
                      </td>
                      <td className="px-3 py-2 text-center font-medium">
                        {count}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <a
                          href={`/projects?stage=${stage}`}
                          className="text-primary hover:underline text-sm"
                        >
                          View {count} projects
                        </a>
                      </td>
                    </tr>
                  );
                })}
                {Object.keys(stats.by_stage).length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-3 py-6 text-center text-apple-muted">
                      No stage data yet
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}