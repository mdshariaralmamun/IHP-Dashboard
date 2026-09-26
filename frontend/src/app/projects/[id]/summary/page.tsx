'use client';

import { use, useEffect, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { downloadProjectSummary, getProjectSummaryData } from '@/lib/api';
import type { ProjectSummaryData } from '@/lib/api';
import { useUser } from '@/lib/useUser';

/**
 * Project Summary - web view in the official IHP house format, with the
 * KAUST logo, and one-click conversion to Word or PDF.
 */
export default function SummaryPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <AuthGuard>
      <SummaryView projectId={Number(id)} />
    </AuthGuard>
  );
}

function SummaryView({ projectId }: { projectId: number }) {
  const { user } = useUser();
  const [data, setData] = useState<ProjectSummaryData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    getProjectSummaryData(projectId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'));
  }, [projectId]);

  async function download(format: 'docx' | 'pdf') {
    setBusy(format);
    setError(null);
    try {
      await downloadProjectSummary(projectId, format);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Download failed');
    } finally {
      setBusy(null);
    }
  }

  const cell = 'border border-gray-300 px-3 py-2 align-top';

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-4xl space-y-4 px-4 py-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link href={`/projects/${projectId}`} className="text-xs text-apple-muted hover:text-apple-text">
            ← Back to project
          </Link>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void download('docx')}
              disabled={busy !== null}
              className="rounded-md bg-primary px-4 py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              {busy === 'docx' ? 'Preparing…' : '⬇ Download Word'}
            </button>
            <button
              type="button"
              onClick={() => void download('pdf')}
              disabled={busy !== null}
              className="rounded-md border border-red-300 bg-red-50 px-4 py-2 text-xs font-semibold text-red-700 hover:bg-red-100 disabled:opacity-50"
            >
              {busy === 'pdf' ? 'Converting…' : '⬇ Download PDF'}
            </button>
          </div>
        </div>

        {error && <ErrorBox message={error} />}
        {!data && !error && <p className="text-sm text-apple-muted">Loading…</p>}

        {data && (
          <article className="paper-surface rounded-lg border border-gray-300 bg-white p-8 shadow-sm">
            {/* logo + date */}
            <div className="flex items-start justify-between gap-4">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/kaust_logo.png" alt="KAUST" className="h-14" />
              <div className="text-right text-xs text-gray-500">
                <p>Date: {data.date}</p>
                {data.to && <p className="mt-1 text-sm font-semibold text-gray-800">To: {data.to}</p>}
              </div>
            </div>

            {/* project info table */}
            <table className="mt-6 w-full border-collapse text-sm">
              <tbody>
                {[
                  ['Project Reference:', data.info.project_reference],
                  ['Division:', data.info.division],
                  ['Customer/ Proponent:', data.info.customer],
                  ['Contact:', data.info.contact],
                  ['Project Location', data.info.location],
                ].map(([k, v]) => (
                  <tr key={k}>
                    <td className={`${cell} w-56 bg-gray-50 font-semibold`}>{k}</td>
                    <td className={cell}>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* introduction */}
            <h2 className="mt-6 text-sm font-bold text-gray-900">Introduction</h2>
            <p className="mt-1 text-sm leading-relaxed text-gray-700">
              King Abdullah University of Science &amp; Technology (KAUST) intends to proceed
              with the subject project. This Project Summary describes the proposed scope of
              work to be executed by the In-House Projects (IHP) team, based on the site
              assessment and the requirements agreed with the proponent.
            </p>

            {/* scope by trade */}
            <h2 className="mt-5 text-sm font-bold text-gray-900">General Scope of Work</h2>
            {data.scope.length === 0 && (
              <p className="mt-1 text-sm italic text-gray-500">
                (Scope items appear once the BOQ/MTO is prepared.)
              </p>
            )}
            {data.scope.map((s) => (
              <div key={s.trade} className="mt-3">
                <h3 className="text-sm font-bold text-gray-800">{s.trade}</h3>
                <ul className="mt-1 list-disc pl-6 text-sm text-gray-700">
                  {s.items.map((it, i) => (
                    <li key={i}>{it}</li>
                  ))}
                </ul>
              </div>
            ))}

            {/* commercial */}
            <table className="mt-6 w-full border-collapse text-sm">
              <tbody>
                <tr>
                  <td className={`${cell} w-56 bg-gray-50 font-semibold`}>Scope:</td>
                  <td className={cell}>Attached</td>
                </tr>
                <tr>
                  <td className={`${cell} bg-gray-50 font-semibold`}>TOTAL ESTIMATED PROJECT COST</td>
                  <td className={cell}>Within IHP budget</td>
                </tr>
                <tr>
                  <td className={`${cell} bg-gray-50 font-semibold`}>WBS:</td>
                  <td className={cell}>—</td>
                </tr>
              </tbody>
            </table>

            {/* schedule */}
            <table className="mt-4 w-full border-collapse text-sm">
              <tbody>
                {Object.entries(data.schedule).map(([k, v]) => (
                  <tr key={k} className={k === 'Total' ? 'font-bold' : ''}>
                    <td className={`${cell} w-56 bg-gray-50 font-semibold`}>{k}</td>
                    <td className={cell}>{v} Weeks</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className="mt-8 text-center text-[10px] text-gray-400">
              Generated by the IHP Project Delivery platform — official IHP Project Summary format.
            </p>
          </article>
        )}
      </main>
    </div>
  );
}
