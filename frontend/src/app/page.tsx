'use client';

import AuthGuard from '@/components/AuthGuard';
import Header from '@/components/Header';
import DashboardView from '@/components/DashboardView';
import { useUser } from '@/lib/useUser';
import Link from 'next/link';

export default function HomePage() {
  return (
    <AuthGuard>
      <HomeView />
    </AuthGuard>
  );
}

function HomeView() {
  const { user } = useUser();

  return (
    <div className="min-h-screen transition-colors duration-200 relative overflow-hidden">
      {/* Subtle Apple-style mesh gradient background */}
      <div className="absolute inset-0 z-0 opacity-40 dark:opacity-20 pointer-events-none" 
           style={{ background: 'radial-gradient(circle at 15% 50%, rgba(0,106,78,0.15), transparent 25%), radial-gradient(circle at 85% 30%, rgba(0,61,112,0.15), transparent 25%)' }}>
      </div>
      
      <Header user={user} />
      <main className="mx-auto max-w-7xl px-4 py-8 relative z-10">
        
        <div className="mb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-[39px] font-bold tracking-tight leading-none mb-2 text-apple-text">
              Executive Dashboard
            </h1>
            <p className="text-sm font-medium text-apple-muted">
              High-level overview of project lifecycles.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/dashboard/construction"
              className="rounded-full border border-apple-border bg-apple-surface/50 backdrop-blur-md px-5 py-2 text-sm font-medium text-apple-text transition-colors hover:bg-black/5 dark:hover:bg-white/10"
            >
              Construction Dashboard
            </Link>
            <Link
              href="/projects"
              className="rounded-full bg-primary px-5 py-2 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90"
            >
              View Project Register →
            </Link>
          </div>
        </div>

        {/* PowerBI Style Dashboard */}
        <DashboardView />

      </main>
    </div>
  );
}
