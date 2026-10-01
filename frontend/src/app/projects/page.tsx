'use client';

import { useCallback, useEffect, useMemo, useRef, useState, Suspense } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import StageBadge from '@/components/StageBadge';
import { listProjects, parsePrForm, createProject, uploadAttachments, ApiError } from '@/lib/api';
import { formatDate } from '@/lib/format';
import { canDo, useUser } from '@/lib/useUser';
import { EAR_STATUS_LABELS, PHASES } from '@/lib/types';
import type { ProjectSummary } from '@/lib/types';

export default function HomePage() {
  return (
    <AuthGuard>
      <Suspense fallback={<div className="p-8 text-center text-apple-muted animate-pulse">Loading projects...</div>}>
        <ProjectRegister />
      </Suspense>
    </AuthGuard>
  );
}

type SortKey = 'pr_number' | 'title' | 'pi_name' | 'location' | 'stage' | 'created_at' | 'completion_pct';
type SortDir = 'asc' | 'desc';

const STAGES_ORDER = [
  'INTAKE', 'MOM_SENT', 'MOM_CONFIRMED', 'DISPOSITION',
  'EAR_DRAFT', 'EAR_REVIEW', 'EAR_APPROVED',
  'SOW_DRAFT', 'SOW_REVIEW', 'SOW_APPROVED',
  'MTO_DRAFT', 'MTO_APPROVED', 'PROCUREMENT',
  'WORK_PERMIT', 'CONSTRUCTION', 'CLOSEOUT', 'ICR_DONE',
];

function ProjectRegister() {
  const router = useRouter();
  const { user } = useUser();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const prFormInputRef = useRef<HTMLInputElement>(null);

  // Filter / sort state
  const [stageFilter, setStageFilter] = useState<string>('');
  const [dispositionFilter, setDispositionFilter] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [tradeFilter, setTradeFilter] = useState<string>('');
  const [bucketFilter, setBucketFilter] = useState<string>('');
  // Lifecycle division drill-down ("?phase=EAR" from the dashboard cards).
  const [phaseFilter, setPhaseFilter] = useState<string>('');
  const searchParams = useSearchParams();
  const [search, setSearch] = useState<string>(searchParams?.get('search') ?? '');
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  // Drill-down links (dashboard, KPI cards) arrive as ?stage=A,B and ?disposition=ICR.
  // Seed the matching filter; a multi-stage list uses the search box as fallback.
  const [seededStage, setSeededStage] = useState<string>('');
  // A PR that dropped out of the newest Planner is no longer IHP work:
  // leaving it in the register made cancelled / equipment-branch PRs (e.g.
  // PR-12725, an ASEPC item that only exists in the O&M closed-equipment
  // tab) look like live projects. It stays reachable here for audit.
  const [showRemoved, setShowRemoved] = useState(false);
  useEffect(() => {
    if (!searchParams) return;
    const st = searchParams.get('stage');
    const disp = searchParams.get('disposition');
    if (st) {
      const stages = st.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
      if (stages.length === 1) {
        setStageFilter(stages[0]);
      } else if (stages.length > 1) {
        setSeededStage(stages.join(','));
      }
    }
    if (disp) setDispositionFilter(disp.toUpperCase());
    const ph = searchParams.get('phase');
    if (ph) setPhaseFilter(ph);
  }, [searchParams]);

  const load = useCallback(async () => {
    setError(null);
    try {
      setProjects(await listProjects());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load projects.');
    }
  }, []);

  useEffect(() => {
    if (searchParams) {
      const q = searchParams.get('search');
      if (q !== null) setSearch(q);
    }
  }, [searchParams]);

  useEffect(() => {
    void load();
  }, [load]);

  // Drag-dropped (or browsed) PR form: parse it, create the PR in the master
  // database automatically, attach the form file, then open the project.
  async function handlePrFormUpload(file: File) {
    setParsing(true);
    setError(null);
    try {
      const result = await parsePrForm(file);
      const input = result.project;
      if (!input.pr_number) {
        throw new Error('No Reference Number found — is this a KAUST PR form export?');
      }
      const created = await createProject({
        pr_number: input.pr_number,
        title: input.title ?? input.pr_number,
        description: input.description,
        location: input.location,
        pi_name: input.pi_name,
        pi_email: input.pi_email,
        funding_source: input.funding_source,
      });
      try {
        const carried = (result.carried_files ?? []).map(
          ({ filename, content_base64 }) =>
            new File(
              [Uint8Array.from(atob(content_base64), (c) => c.charCodeAt(0))],
              filename,
            ),
        );
        await uploadAttachments(created.id, [file, ...carried]);
      } catch {
        setError('PR created, but attaching the form file failed — re-upload it from the project page.');
      }
      router.push(`/projects/${created.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError('A project with this PR number already exists.');
      } else {
        setError(err instanceof Error ? err.message : 'Could not process the PR form.');
      }
      setParsing(false);
    }
  }

  const removedCount = useMemo(
    () => (projects ?? []).filter((p) => p.planner_removed).length,
    [projects],
  );

  // ---- filter + sort + project memo ----
  const visibleProjects = useMemo(() => {
    if (!projects) return null;
    const multiStages = seededStage ? seededStage.split(',').map((s) => s.trim()) : [];
    const out = projects.filter((p) => {
      // Live view by default; the removed ones are one click away.
      if (showRemoved ? !p.planner_removed : p.planner_removed) return false;
      if (stageFilter && p.stage !== stageFilter) return false;
      if (multiStages.length > 0 && !multiStages.includes(p.stage)) return false;
      if (dispositionFilter && p.disposition !== dispositionFilter) return false;
      if (typeFilter && (p.project_type ?? '') !== typeFilter) return false;
      if (tradeFilter && !(p.trades ?? []).includes(tradeFilter)) return false;
      if (bucketFilter && (p.planner_bucket ?? '') !== bucketFilter) return false;
      if (phaseFilter) {
        const phase = PHASES.find((x) => x.key === phaseFilter);
        const inPhase = phase
          ? phase.buckets.includes(p.planner_bucket ?? '')
          : p.phase === phaseFilter;
        if (!inPhase) return false;
      }
      if (search) {
        const s = search.toLowerCase();
        if (!(
          p.pr_number.toLowerCase().includes(s) ||
          (p.title || '').toLowerCase().includes(s) ||
          (p.pi_name || '').toLowerCase().includes(s) ||
          (p.location || '').toLowerCase().includes(s)
        )) return false;
      }
      return true;
    });
    out.sort((a, b) => {
      const va: any = (a as any)[sortKey] ?? '';
      const vb: any = (b as any)[sortKey] ?? '';
      // Special-case stage: sort by lifecycle order, not alphabetic
      if (sortKey === 'stage') {
        const ia = STAGES_ORDER.indexOf(va);
        const ib = STAGES_ORDER.indexOf(vb);
        return sortDir === 'asc' ? ia - ib : ib - ia;
      }
      if (va < vb) return sortDir === 'asc' ? -1 : 1;
      if (va > vb) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return out;
  }, [projects, stageFilter, dispositionFilter, typeFilter, tradeFilter, bucketFilter, search, sortKey, sortDir, seededStage, phaseFilter, showRemoved]);

  // Distinct values for filter dropdowns
  const distinctTypes = useMemo(() => {
    const s = new Set<string>();
    (projects || []).forEach((p) => p.project_type && s.add(p.project_type));
    return Array.from(s).sort();
  }, [projects]);
  const distinctTrades = useMemo(() => {
    const s = new Set<string>();
    (projects || []).forEach((p) => (p.trades ?? []).forEach((t) => s.add(t)));
    return Array.from(s).sort();
  }, [projects]);
  // Bucket options come from the IHP planner's own buckets on the imported
  // projects (EAR, DESIGN, PTW/WICF, CONSTRUCTION, QUALITY INSPECTION,
  // WCH, WCC, ...). The canonical list lives in BUCKET_TO_STAGE
  // (scripts/import_planner.py).
  const KNOWN_BUCKETS = [
    'EAR', 'DESIGN', 'PTW/WICF', 'PTW', 'WICF', 'CONSTRUCTION',
    'QUALITY INSPECTION', 'WCH', 'WCC', 'MOM', 'INTAKE',
  ];
  const distinctBuckets = useMemo(() => {
    const s = new Set<string>();
    (projects || []).forEach((p) => p.planner_bucket && s.add(p.planner_bucket));
    // offer the canonical buckets even before the first planner import
    KNOWN_BUCKETS.forEach((b) => s.add(b));
    return Array.from(s).sort();
  }, [projects]);

  function toggleSort(k: SortKey) {
    if (sortKey === k) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(k);
      setSortDir(k === 'pr_number' || k === 'title' ? 'asc' : 'desc');
    }
  }
  function sortIndicator(k: SortKey) {
    if (sortKey !== k) return ' ↕';
    return sortDir === 'asc' ? ' ↑' : ' ↓';
  }
  function toggleExpand(id: number) {
    const next = new Set(expanded);
    next.has(id) ? next.delete(id) : next.add(id);
    setExpanded(next);
  }

  function resetFilters() {
    setStageFilter(''); setDispositionFilter(''); setTypeFilter(''); setTradeFilter('');
    setBucketFilter(''); setSearch(''); setSeededStage(''); setPhaseFilter('');
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', '/projects');
    }
  }
  const filterCount = (stageFilter ? 1 : 0) + (dispositionFilter ? 1 : 0) + (typeFilter ? 1 : 0) +
    (tradeFilter ? 1 : 0) + (bucketFilter ? 1 : 0) + (search ? 1 : 0) + (seededStage ? 1 : 0) +
    (phaseFilter ? 1 : 0);

  return (
    <div className="min-h-screen bg-apple-bg text-apple-text transition-colors duration-200">
      <Header user={user} />
      <main className="mx-auto max-w-[1400px] px-6 py-8">

        {/* Register Title & Search Header */}
        <div className="mb-8 flex flex-col md:flex-row md:items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl sm:text-[39px] font-bold tracking-tight leading-none mb-2">
              Project Register
            </h1>
            <p className="text-sm text-apple-muted font-medium">
              All lab-modification project requests. {projects ? `${projects.length} total` : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/"
              className="rounded-full border border-apple-border bg-apple-surface/50 backdrop-blur-md px-5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/10"
            >
              ← Dashboard
            </Link>
            <Link
              href="/upload"
              className="rounded-full border border-apple-border bg-apple-surface/50 backdrop-blur-md px-5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/10"
            >
              Upload Trackers
            </Link>
            {canDo(user, 'projects.create') && (
              <>
                <button
                  type="button"
                  disabled={parsing}
                  onClick={() => prFormInputRef.current?.click()}
                  className="rounded-full border border-apple-border bg-apple-surface/50 backdrop-blur-md px-5 py-2 text-sm font-medium transition-colors hover:bg-black/5 dark:hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {parsing ? 'Reading form…' : 'Upload PR form'}
                </button>
                <input
                  ref={prFormInputRef}
                  type="file"
                  accept=".pdf,.docx,.txt,.md,.msg"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void handlePrFormUpload(file);
                    e.target.value = '';
                  }}
                />
                <Link
                  href="/projects/new"
                  className="rounded-full bg-primary px-6 py-2 text-sm font-semibold text-white shadow-sm transition-opacity hover:opacity-90"
                >
                  New PR
                </Link>
              </>
            )}
          </div>
        </div>

        {canDo(user, 'projects.create') && (
          <div
            role="button"
            tabIndex={0}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragActive(false);
              const file = e.dataTransfer.files?.[0];
              if (file) void handlePrFormUpload(file);
            }}
            onClick={() => prFormInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') prFormInputRef.current?.click();
            }}
            className={`mb-8 cursor-pointer rounded-2xl border-2 border-dashed px-6 py-8 text-center text-sm font-medium transition-colors ${
              dragActive
                ? 'border-primary bg-primary/5 text-primary'
                : 'border-apple-border bg-apple-surface/30 text-apple-muted hover:border-apple-muted hover:bg-apple-surface/60 backdrop-blur-md'
            }`}
          >
            {parsing
              ? 'Reading PR form…'
              : 'Drag & drop a KAUST PR request form here, or click to browse. The PR is created automatically.'}
          </div>
        )}

        {/* ---- Live vs removed-from-Planner ---- */}
        {projects && removedCount > 0 && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-apple-border bg-apple-surface/50 px-4 py-2.5 text-xs backdrop-blur-md">
            <div className="flex overflow-hidden rounded-lg border border-apple-border">
              <button
                type="button"
                onClick={() => setShowRemoved(false)}
                className={`px-3 py-1.5 font-semibold ${showRemoved ? 'text-apple-muted hover:bg-apple-surface' : 'bg-primary text-white'}`}
              >
                Live ({(projects.length ?? 0) - removedCount})
              </button>
              <button
                type="button"
                onClick={() => setShowRemoved(true)}
                className={`px-3 py-1.5 font-semibold ${showRemoved ? 'bg-primary text-white' : 'text-apple-muted hover:bg-apple-surface'}`}
              >
                Removed from Planner ({removedCount})
              </button>
            </div>
            <span className="text-apple-muted">
              {showRemoved
                ? 'Gone from the newest Planner export — cancelled, or moved to the equipment branch. Not IHP work, and excluded from the dashboard.'
                : 'Only PRs present in the newest Planner export.'}
            </span>
          </div>
        )}

        {/* ---- Filter bar ---- */}
        {projects && projects.length > 0 && (
          <div className="mb-6 grid grid-cols-2 gap-4 rounded-2xl border border-apple-border bg-apple-surface/50 backdrop-blur-md p-4 shadow-sm md:grid-cols-6">
            <div className="col-span-2 md:col-span-2">
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-apple-muted mb-1">
                Search
              </label>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="PR number, title, PI, location…"
                className="w-full rounded-lg border border-apple-border bg-white/50 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary placeholder:text-apple-muted dark:bg-white/10"
              />
            </div>
            <FilterSelect
              label="Stage" value={stageFilter} onChange={setStageFilter}
              options={STAGES_ORDER}
            />
            <FilterSelect
              label="Disposition" value={dispositionFilter} onChange={setDispositionFilter}
              options={['PROJECT', 'ICR']}
            />
            <FilterSelect
              label="Type" value={typeFilter} onChange={setTypeFilter}
              options={distinctTypes}
            />
            <FilterSelect
              label="Trade" value={tradeFilter} onChange={setTradeFilter}
              options={distinctTrades}
            />
            <FilterSelect
              label="Bucket" value={bucketFilter} onChange={setBucketFilter}
              options={distinctBuckets}
            />
            <FilterSelect
              label="Division" value={phaseFilter} onChange={setPhaseFilter}
              options={PHASES.map((x) => x.key)}
            />
            {filterCount > 0 && (
              <div className="col-span-2 flex items-center gap-3 md:col-span-6 mt-2">
                <button
                  type="button"
                  onClick={resetFilters}
                  className="text-xs font-medium text-apple-muted hover:text-apple-text transition-colors"
                >
                  ✕ Clear {filterCount} filter{filterCount > 1 ? 's' : ''}
                </button>
                {seededStage && (
                  <span className="rounded-full bg-primary/10 border border-primary/20 px-3 py-1 text-[11px] font-semibold text-primary">
                    Stages: {seededStage.split(',').join(' / ')}
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {error && <ErrorBox message={error} onRetry={load} />}

        {!error && visibleProjects === null && (
          <p className="py-20 text-center text-sm font-medium text-apple-muted">Loading projects…</p>
        )}

        {visibleProjects !== null && visibleProjects.length === 0 && !error && projects && projects.length > 0 && (
          <div className="rounded-2xl border border-dashed border-apple-border bg-apple-surface/30 px-6 py-20 text-center text-sm text-apple-muted backdrop-blur-md">
            No projects match the current filters.{' '}
            <button onClick={resetFilters} className="font-semibold text-apple-text hover:opacity-70 transition-opacity">
              Clear filters
            </button>
          </div>
        )}

        {projects !== null && projects.length === 0 && !error && (
          <div className="rounded-2xl border border-dashed border-apple-border bg-apple-surface/30 px-6 py-20 text-center text-sm text-apple-muted backdrop-blur-md">
            No projects yet.
            {canDo(user, 'projects.create') && (
              <>
                {' '}
                <Link href="/projects/new" className="font-semibold text-primary hover:opacity-80 transition-opacity">
                  Create the first PR
                </Link>{' '}
                to get started.
              </>
            )}
          </div>
        )}

        {visibleProjects !== null && visibleProjects.length > 0 && (
          <div className="overflow-x-auto border-t border-apple-border">
            <table className="min-w-full text-sm">
              <thead className="bg-apple-bg border-b border-apple-border">
                <tr>
                  <th className="w-8 px-2 py-4" aria-label="Expand"></th>
                  <Th label="PR #" onClick={() => toggleSort('pr_number')} sortIndicator={sortIndicator('pr_number')} active={sortKey === 'pr_number'} dir={sortDir} />
                  <Th label="Title" onClick={() => toggleSort('title')} sortIndicator={sortIndicator('title')} active={sortKey === 'title'} dir={sortDir} />
                  <Th label="PI" onClick={() => toggleSort('pi_name')} sortIndicator={sortIndicator('pi_name')} active={sortKey === 'pi_name'} dir={sortDir} />
                  <Th label="Location" onClick={() => toggleSort('location')} sortIndicator={sortIndicator('location')} active={sortKey === 'location'} dir={sortDir} />
                  <Th label="Stage" onClick={() => toggleSort('stage')} sortIndicator={sortIndicator('stage')} active={sortKey === 'stage'} dir={sortDir} />
                  <Th label="Trades" onClick={() => toggleSort('completion_pct')} sortIndicator="" />
                  <Th label="Done" onClick={() => toggleSort('completion_pct')} sortIndicator={sortIndicator('completion_pct')} active={sortKey === 'completion_pct'} dir={sortDir} />
                  <Th label="Created" onClick={() => toggleSort('created_at')} sortIndicator={sortIndicator('created_at')} active={sortKey === 'created_at'} dir={sortDir} />
                </tr>
              </thead>
              <tbody className="divide-y divide-apple-border">
                {visibleProjects.map((p) => {
                  const isOpen = expanded.has(p.id);
                  return (
                    <ProjectRow
                      key={p.id}
                      project={p}
                      isOpen={isOpen}
                      onToggle={() => toggleExpand(p.id)}
                      onOpen={() => router.push(`/projects/${p.id}`)}
                    />
                  );
                })}
              </tbody>
            </table>
            <div className="border-t border-apple-border py-4 text-xs font-medium text-apple-muted text-right">
              Showing {visibleProjects.length} of {projects?.length ?? 0} projects
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function FilterSelect({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: string[];
}) {
  return (
    <div>
      <label className="block text-[10px] font-semibold uppercase tracking-wider text-apple-muted mb-1">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-apple-border bg-white/50 px-2 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary dark:bg-white/10"
      >
        <option value="">All</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}

function Th({ label, onClick, sortIndicator, active, dir }: {
  label: string;
  onClick: () => void;
  sortIndicator: string;
  active?: boolean;
  dir?: 'asc' | 'desc';
}) {
  return (
    <th
      onClick={onClick}
      className={`cursor-pointer select-none px-3 py-4 text-left text-xs font-semibold uppercase tracking-wider transition-colors ${
        active ? 'text-apple-text' : 'text-apple-muted hover:text-apple-text'
      }`}
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      {label}{sortIndicator}
    </th>
  );
}

function ProjectRow({ project, isOpen, onToggle, onOpen }: {
  project: ProjectSummary; isOpen: boolean; onToggle: () => void; onOpen: () => void;
}) {
  const completion = project.completion_pct ?? 0;
  return (
    <>
      <tr className="cursor-pointer transition-colors hover:bg-apple-surface/50 group" onClick={onOpen}>
        <td className="px-2 py-4" onClick={(e) => { e.stopPropagation(); onToggle(); }}>
          <span className={`inline-block w-4 text-apple-muted transition-transform ${isOpen ? 'rotate-90' : 'group-hover:text-apple-text'}`}>
            ▶
          </span>
        </td>
        <td className="whitespace-nowrap px-3 py-4 font-mono font-medium text-apple-text">
          {project.pr_number}
        </td>
        <td className="max-w-md truncate px-3 py-4 font-medium text-apple-text" title={project.title}>
          {project.title}
        </td>
        <td className="whitespace-nowrap px-3 py-4 text-apple-muted">
          {project.pi_name ?? '—'}
        </td>
        <td className="whitespace-nowrap px-3 py-4 text-apple-muted">
          {project.location ?? '—'}
        </td>
        <td className="whitespace-nowrap px-3 py-4">
          <StageBadge stage={project.stage} />
        </td>
        <td className="px-3 py-4">
          {(project.trades ?? []).length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {(project.trades ?? []).slice(0, 4).map((t) => (
                <span key={t} className="rounded-sm bg-apple-surface px-1.5 py-0.5 text-[10px] font-semibold text-apple-text border border-apple-border">
                  {t}
                </span>
              ))}
              {(project.trades ?? []).length > 4 && (
                <span className="text-[10px] text-apple-muted">+{project.trades!.length - 4}</span>
              )}
            </div>
          ) : (
            <span className="text-apple-muted">—</span>
          )}
        </td>
        <td className="whitespace-nowrap px-3 py-4">
          <CompletionBar pct={completion} />
        </td>
        <td className="whitespace-nowrap px-3 py-4 text-xs tabular-nums text-apple-muted">
          {formatDate(project.created_at)}
        </td>
      </tr>
      {isOpen && (
        <tr className="bg-apple-surface/20 border-b border-apple-border">
          <td colSpan={9} className="px-8 py-6 text-xs text-apple-text shadow-inner">
            <div className="grid grid-cols-2 gap-x-8 gap-y-4 md:grid-cols-4">
              <DetailField label="PR Number" value={project.pr_number} />
              <DetailField label="Type" value={project.project_type ?? '—'} />
              <DetailField label="Division" value={project.division ?? '—'} />
              <DetailField label="Priority" value={project.priority ?? '—'} />
              <DetailField label="Discipline" value={(project.trades ?? []).join(', ') || '—'} />
              <DetailField label="Funding" value={project.funding_source ?? '—'} />
              <DetailField label="Bucket" value={project.planner_bucket ?? '—'} />
              <DetailField label="Created" value={formatDate(project.created_at)} />
              <DetailField label="Phase" value={project.phase ?? '—'} />
              <DetailField
                label="Latest status"
                value={
                  project.latest_status
                    ? project.latest_status +
                      (project.latest_status_date ? ` (${project.latest_status_date})` : '')
                    : '—'
                }
              />
              <DetailField label="Checklist" value={project.checklist ?? '—'} />
              <DetailField
                label="EAR approved"
                value={project.ear_approved_date ?? '—'}
              />
              <DetailField
                label="EAR status"
                value={
                  project.ear_substatus
                    ? EAR_STATUS_LABELS[project.ear_substatus] ?? project.ear_substatus
                    : '—'
                }
              />
              <DetailField label="Flags" value={(project.flags ?? []).join(', ') || '—'} />
            </div>
            {project.ear_substatus === 'asepc_pending' && (
              <div className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                <strong>Waiting for ASEPC approval.</strong> EAR is approved; construction
                cannot start until ASEPC approves — otherwise the project is cancelled.
              </div>
            )}
            {project.ear_substatus === 'cancelled' && (
              <div className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-900">
                <strong>Cancelled</strong> — ASEPC did not approve this project.
              </div>
            )}
            {(project.status_timeline ?? []).length > 0 && (
              <div className="mt-4 rounded-md border border-apple-border bg-white p-3 dark:bg-white/[0.04]">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-apple-muted">
                  Status timeline (from the Planner notes)
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {(project.status_timeline ?? []).map((s, i) => (
                    <span key={s} className="flex items-center gap-1.5">
                      {i > 0 && <span className="text-apple-muted">→</span>}
                      <span className="rounded-full bg-apple-surface px-2 py-0.5 text-[11px] text-apple-text">
                        {s}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-5 flex items-center gap-3 text-xs">
              <button onClick={onOpen} className="font-semibold text-primary hover:underline">
                Open project details →
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-apple-muted mb-0.5">
        {label}
      </div>
      <div className="font-medium text-apple-text">{value}</div>
    </div>
  );
}

function CompletionBar({ pct }: { pct: number }) {
  const colour = pct >= 100 ? 'bg-status-approved' : pct >= 50 ? 'bg-status-warning' : 'bg-apple-muted';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 rounded-full bg-apple-surface overflow-hidden border border-apple-border">
        <div
          className={`h-full ${colour}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      <span className="text-[10px] font-medium tabular-nums text-apple-muted">{pct}%</span>
    </div>
  );
}

