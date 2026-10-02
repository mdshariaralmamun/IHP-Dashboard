'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import StageBadge from '@/components/StageBadge';
import AttachmentsSection from '@/components/project/AttachmentsSection';
import AuditTrail from '@/components/project/AuditTrail';
import CloseoutPanel from '@/components/project/CloseoutPanel';
import ConstructionPanel from '@/components/project/ConstructionPanel';
import DispositionPanel from '@/components/project/DispositionPanel';
import EarPanel from '@/components/project/EarPanel';
import MetadataCard from '@/components/project/MetadataCard';
import MomPanel from '@/components/project/MomPanel';
import PunchListPanel from '@/components/project/PunchListPanel';
import SowBoqPanel from '@/components/project/SowBoqPanel';
import PromoteToEarModal from '@/components/project/PromoteToEarModal';
import TrackerStepper, { stageLabel } from '@/components/TrackerStepper';
import TrackingShare from '@/components/TrackingShare';
import StageChangePanel from '@/components/project/StageChangePanel';
import AiReviewCard from '@/components/project/AiReviewCard';
import { ApiError, deleteProject, getAudit, getProject } from '@/lib/api';
import { canDo, useUser } from '@/lib/useUser';
import type { AuditEntry, ProjectDetail } from '@/lib/types';

export default function ProjectDetailPage() {
  return (
    <AuthGuard>
      <ProjectDetailView />
    </AuthGuard>
  );
}

type TabKey = 'all' | 'mom' | 'disposition' | 'ear' | 'sow_boq' | 'construction' | 'closeout' | 'punch' | 'attachments';

function ProjectDetailView() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const projectId = Number(params.id);
  const { user } = useUser();

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('all');
  const [showPromoteModal, setShowPromoteModal] = useState(false);
  // Captured for the "copy / save / email the tracker" buttons.
  const trackingRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [detail, entries] = await Promise.all([
        getProject(projectId),
        getAudit(projectId),
      ]);
      setProject(detail);
      setAudit(entries);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load the project.');
      }
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (Number.isInteger(projectId) && projectId > 0) {
      void load();
    } else {
      setNotFound(true);
      setLoading(false);
    }
  }, [load, projectId]);

  const canUpload = canDo(user, 'attachments.upload');
  const canDeleteAttachments = canDo(user, 'attachments.delete');
  const canEditProject = canDo(user, 'projects.edit');
  const canDeleteProject = canDo(user, 'projects.delete');

  async function handleDeleteProject() {
    if (!project || deleting) return;
    if (
      !window.confirm(
        `Delete project ${project.pr_number} with all its attachments, MOM, and history? This cannot be undone.`,
      )
    )
      return;
    setDeleting(true);
    setError(null);
    try {
      await deleteProject(project.id);
      router.replace('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed.');
      setDeleting(false);
    }
  }

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="flex items-center justify-between">
          <Link href="/projects" className="text-xs font-semibold text-apple-muted hover:text-apple-text">
            ← Back to Project Register
          </Link>
          <Link
            href="/dashboard/construction"
            className="text-xs font-medium text-primary hover:opacity-80"
          >
            Construction Dashboard →
          </Link>
        </div>

        {loading && <p className="py-12 text-center text-sm text-apple-muted">Loading project…</p>}

        {!loading && notFound && (
          <div className="mt-6 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Project not found.
          </div>
        )}

        {!loading && !notFound && error && (
          <div className="mt-6">
            <ErrorBox message={error} onRetry={load} />
          </div>
        )}

        {!loading && !notFound && project && (
          <div className="mt-4 space-y-6">
            {/* Title Block & Stage */}
            <div className="flex flex-wrap items-center justify-between gap-3 bg-apple-surface p-5 rounded-lg border border-apple-border shadow-2xs">
              <div>
                <span className="text-xs font-bold text-apple-muted uppercase tracking-widest">{project.pr_number}</span>
                {project.ear_number && (
                  <span className="ml-3 text-xs font-bold text-blue-500 uppercase tracking-widest border border-blue-200 bg-blue-50 px-2 py-0.5 rounded">
                    EAR: {project.ear_number}
                  </span>
                )}
                <h1 className="text-2xl font-bold tracking-tight text-apple-text">
                  {project.title}
                </h1>
                <p className="text-xs text-apple-muted mt-0.5">
                  Location: {project.location || 'N/A'} · PI: {project.pi_name || 'N/A'} · Funding: {project.funding_source || 'N/A'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StageBadge stage={project.stage} />
                {project.disposition && (
                  <span className="rounded-full bg-primary px-3 py-1 text-xs font-bold text-white">
                    {project.disposition}
                  </span>
                )}
                <Link
                  href={`/projects/${project.id}/summary`}
                  className="rounded border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
                >
                  Project Summary (Word/PDF)
                </Link>
                {canDo(user, 'projects.edit') && !project.ear_number && (
                  <button
                    type="button"
                    onClick={() => setShowPromoteModal(true)}
                    className="rounded border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
                  >
                    Promote to EAR (Assign New PR)
                  </button>
                )}
              </div>
            </div>

            {/* Stage Stepper Tabs */}
            {(activeTab === 'all') && (
              <div className="bg-apple-surface p-6 rounded-lg shadow-sm border border-apple-border mb-6">
                <div ref={trackingRef}>
                  <h3 className="text-base font-bold text-apple-text mb-4">Live Tracking</h3>
                  <TrackerStepper project={project} audit={audit} />
                </div>

                {/* Outside the captured node, so the buttons stay out of the image. */}
                <TrackingShare
                  target={trackingRef}
                  endpoint={`/api/projects/${project.id}/tracking-email`}
                  prNumber={project.pr_number}
                  defaultTo={project.pi_email ?? null}
                  stageLabel={stageLabel(project.stage)}
                  trackingToken={project.tracking_token ?? null}
                />

                <div className="mt-6 p-4 bg-apple-surface/50 border border-apple-border rounded-md">
                  <h4 className="text-sm font-semibold text-apple-text mb-1">Public Tracking Link</h4>
                  <p className="text-xs text-apple-muted mb-2">Share this link with the PI or external stakeholders so they can track the project without logging in.</p>
                  {project.tracking_token ? (
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        readOnly
                        value={`${typeof window !== 'undefined' ? window.location.origin : ''}/track/${project.tracking_token}`}
                        className="flex-1 text-sm bg-apple-surface border border-apple-border rounded px-3 py-2 text-apple-muted focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => navigator.clipboard.writeText(`${window.location.origin}/track/${project.tracking_token}`)}
                        className="px-4 py-2 border border-apple-border hover:bg-black/5 dark:hover:bg-white/10 text-apple-text text-sm font-medium rounded transition-colors"
                      >
                        Copy
                      </button>
                    </div>
                  ) : (
                    <p className="text-xs text-apple-muted italic">No tracking token on this project yet.</p>
                  )}
                </div>
                
                <div className="mt-4 bg-blue-50/50 p-3 rounded text-xs text-blue-800 border border-blue-100 flex gap-2 items-start">
                  <span className="text-lg">💡</span>
                  <div>
                    <strong>Data Sources Connected:</strong> This tracking table consolidates information from the O&amp;M Project Progress Tracking Sheet, IHP Construction Projects, PR Requests, and the Planner, providing a single unified view.
                  </div>
                </div>
              </div>
            )}
            
            {/* The document review sits above the tabs: it is about the PR as a
                whole (its uploaded documents), not about one workflow stage. */}
            <div className="mb-6">
              <AiReviewCard
                projectId={project.id}
                attachmentCount={project.attachments.length}
                canRun={canEditProject}
              />
            </div>

            {/* Phase changes live here, not inside a tab, so they are always
                one click away whatever the project is doing. */}
            {canEditProject && (
              <div className="mb-6">
                <StageChangePanel
                  project={project}
                  canForce={canDo(user, 'users.manage')}
                  onChanged={load}
                />
              </div>
            )}

            <div className="flex overflow-x-auto rounded-lg border border-apple-border bg-apple-surface p-1 shadow-2xs gap-1">
              {[
                { key: 'all', label: 'Overview & All Stages' },
                { key: 'mom', label: '1. MOM' },
                { key: 'disposition', label: '2. Disposition' },
                { key: 'ear', label: '3. EAR' },
                { key: 'sow_boq', label: '4. SOW / BOQ' },
                { key: 'construction', label: '5-6. Construction' },
                { key: 'closeout', label: '7. Closeout' },
                { key: 'punch', label: '8. Punch List' },
                { key: 'attachments', label: `Attachments (${project.attachments.length})` },
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveTab(tab.key as TabKey)}
                  className={`rounded-md px-3 py-2 text-xs font-semibold whitespace-nowrap transition-colors ${
                    activeTab === tab.key
                      ? 'bg-primary text-white shadow-2xs'
                      : 'text-apple-muted hover:bg-apple-surface hover:text-apple-text'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Stage Panels rendered according to active tab */}
            {(activeTab === 'all' || activeTab === 'mom') && (
              <MomPanel
                projectId={project.id}
                mom={project.mom}
                stage={project.stage}
                currentUser={user}
                onChanged={load}
              />
            )}

            {(activeTab === 'all' || activeTab === 'disposition') && (
              <DispositionPanel
                project={project}
                currentUser={user}
                onChanged={load}
              />
            )}

            {(activeTab === 'all' || activeTab === 'ear') && (
              <EarPanel
                project={project}
                currentUser={user}
                onChanged={load}
              />
            )}

            {(activeTab === 'all' || activeTab === 'sow_boq') && (
              <SowBoqPanel
                project={project}
                currentUser={user}
                onChanged={load}
              />
            )}

            {(activeTab === 'all' || activeTab === 'construction') && (
              <ConstructionPanel
                project={project}
                currentUser={user}
                onChanged={load}
              />
            )}

            {(activeTab === 'all' || activeTab === 'closeout') && (
              <CloseoutPanel
                projectId={project.id}
                project={project}
                currentUser={user}
                onChanged={load}
              />
            )}

            {activeTab === 'punch' && (
              <PunchListPanel
                projectId={project.id}
                currentUser={user}
                onChanged={load}
              />
            )}

            {(activeTab === 'all' || activeTab === 'attachments') && (
              <>
                <MetadataCard project={project} canEdit={canEditProject} onChanged={load} />
                <AttachmentsSection
                  projectId={project.id}
                  attachments={project.attachments}
                  canUpload={canUpload}
                  canDelete={canDeleteAttachments}
                  onChanged={load}
                />
              </>
            )}

            <AuditTrail entries={audit} />

            {canDeleteProject && (
              <section className="rounded-lg border border-red-200 bg-red-50 p-6">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-red-700">
                  Danger zone
                </h2>
                <p className="mt-1 text-sm text-red-600">
                  Permanently delete this project with all attachments, MOM records, and history.
                </p>
                <button
                  type="button"
                  onClick={() => void handleDeleteProject()}
                  disabled={deleting}
                  className="mt-3 rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {deleting ? 'Deleting…' : 'Delete project'}
                </button>
              </section>
            )}
          </div>
        )}

        {showPromoteModal && (
          <PromoteToEarModal 
            projectId={project!.id} 
            onClose={() => setShowPromoteModal(false)}
            onSuccess={() => {
              setShowPromoteModal(false);
              void load();
            }}
          />
        )}
      </main>
    </div>
  );
}

