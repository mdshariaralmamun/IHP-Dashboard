'use client';

import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import Header from '@/components/Header';
import PhaseBoard from '@/components/PhaseBoard';
import { useUser } from '@/lib/useUser';

/** The Design board: whose move is it, and what blinks because it is ours. */
export default function DesignBoardPage() {
  const { user } = useUser();
  return (
    <AuthGuard>
      <div className="min-h-screen bg-apple-surface/50">
        <Header user={user} />
        <main className="mx-auto max-w-7xl space-y-4 px-4 py-8">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-apple-text">Design board</h1>
              <p className="mt-1 text-sm text-apple-muted">MOM and Project Summary sent/pending, whose court each PR is in, assignment, follow-up and one-click email to the PI. Click any visual to cross-filter.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
            <Link
              key="ear"
              href="/dashboard/ear"
              className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 hover:border-primary hover:text-primary dark:border-white/10 dark:bg-white/5"
            >
              EAR board
            </Link>
            <Link
              key="procore"
              href="/dashboard/procore"
              className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 hover:border-primary hover:text-primary dark:border-white/10 dark:bg-white/5"
            >
              Procore board
            </Link>
            </div>
          </div>
          <PhaseBoard phase='design' />
        </main>
      </div>
    </AuthGuard>
  );
}
