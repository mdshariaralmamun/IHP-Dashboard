'use client';

import { use, useEffect, useState } from 'react';
import { ProjectSummary } from '@/lib/types';
import TrackerStepper from '@/components/TrackerStepper';

export default function PublicTrackerPage({ params }: { params: Promise<{ token: string }> }) {
  const resolvedParams = use(params);
  const token = resolvedParams.token;
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/projects/track/${token}`)
      .then(async (res) => {
        if (!res.ok) {
          setError('Project not found or link is invalid.');
          return;
        }
        const data = await res.json();
        setProject(data);
      })
      .catch(() => setError('Failed to load project.'))
      .finally(() => setLoading(false));
  }, [token]);

  if (loading) {
    return (
      <div className="min-h-screen bg-apple-surface/50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="min-h-screen bg-apple-surface/50 flex items-center justify-center p-4">
        <div className="bg-apple-surface p-8 rounded-xl shadow-sm text-center max-w-md w-full">
          <div className="w-16 h-16 bg-red-100 text-red-600 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
          </div>
          <h1 className="text-xl font-bold text-apple-text mb-2">Access Error</h1>
          <p className="text-apple-muted">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-apple-surface/50 flex flex-col">
      <header className="bg-apple-surface border-b border-apple-border px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-xl">
            IHP
          </div>
          <h1 className="text-xl font-semibold text-apple-text">Project Tracker</h1>
        </div>
      </header>
      
      <main className="flex-1 max-w-6xl w-full mx-auto p-6 flex flex-col gap-8">
        <section className="bg-apple-surface p-8 rounded-xl shadow-sm border border-apple-border">
          <div className="mb-6">
            <div className="flex items-center gap-3 mb-2">
              <span className="px-3 py-1 bg-apple-surface text-apple-muted text-sm font-medium rounded-full">
                PR: {project.pr_number}
              </span>
              {project.ear_number && (
                <span className="px-3 py-1 bg-blue-50 text-blue-700 text-sm font-medium rounded-full border border-blue-200">
                  EAR: {project.ear_number}
                </span>
              )}
            </div>
            <h2 className="text-3xl font-bold text-apple-text mb-2">{project.title}</h2>
            <p className="text-apple-muted">
              PI: <span className="font-semibold">{project.pi_name || 'N/A'}</span>
              {project.location && ` • Location: ${project.location}`}
            </p>
          </div>
          
          <div className="mt-10 mb-6">
            <h3 className="text-lg font-semibold text-apple-text mb-4">Project Progress</h3>
            <TrackerStepper project={project} />
          </div>
        </section>
      </main>
      
      <footer className="bg-apple-surface py-6 border-t border-apple-border mt-auto text-center text-apple-muted text-sm">
        <p>IHP Design and Construction • Automated Tracker</p>
      </footer>
    </div>
  );
}

