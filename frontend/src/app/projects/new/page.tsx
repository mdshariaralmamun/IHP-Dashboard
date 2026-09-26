'use client';

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import Header from '@/components/Header';
import { ApiError, createProject } from '@/lib/api';
import { canDo, useUser } from '@/lib/useUser';
import { useOvmAutoPopulate } from '@/hooks/useOvmAutoPopulate';
import type { CreateProjectInput } from '@/lib/types';

export default function NewProjectPage() {
  return (
    <AuthGuard>
      <NewProjectForm />
    </AuthGuard>
  );
}

const EMPTY_FORM = {
  pr_number: '',
  title: '',
  description: '',
  location: '',
  pi_name: '',
  pi_email: '',
  funding_source: '',
  // Auto-population tracking
  _om_pi: '',     // PI from O&M Tracking Sheet (auto-populated)
  _om_location: '', // Location from O&M Tracking Sheet (auto-populated)
  _om_detail_location: '', // Detail Location from O&M sheet (auto-populated)
  _om_source: 'none', // 'om' | 'pr' | 'none' — which source populated the field
  _om_populated_at: '', // timestamp when O&M data was fetched
};

function NewProjectForm() {
  const router = useRouter();
  const { user, loading } = useUser();
  const [form, setForm] = useState<typeof EMPTY_FORM>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // The O&M sheet lookup doesn't depend on the PR number — fetch once on mount.
  const om = useOvmAutoPopulate('', '');

  // Sync O&M-sourced values into the form. Visible inputs are pre-filled so the
  // user can see and edit what came from the sheet; `update()` flips _om_source
  // to 'pr' on first manual edit so the hint disappears.
  useEffect(() => {
    setForm((prev) => ({
      ...prev,
      _om_pi: om.omPi,
      _om_location: om.omLocation,
      _om_detail_location: om.omDetailLocation,
      _om_source: om.omSource,
      _om_populated_at: om.omPopulatedAt,
      pi_name: prev.pi_name || (om.omSource === 'om' ? om.omPi : ''),
      location: prev.location || (om.omSource === 'om' ? om.omLocation : ''),
    }));
  }, [om.omPi, om.omLocation, om.omDetailLocation, om.omSource, om.omPopulatedAt]);

  function update(field: keyof typeof EMPTY_FORM) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({
        ...prev,
        [field]: e.target.value,
        // When user manually edits a field, mark it as not auto-populated
        ...(field === 'pi_name' ? { _om_source: 'pr' } : {}),
        ...(field === 'location' ? { _om_source: 'pr' } : {}),
      }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    const prNumber = form.pr_number.trim();
    const title = form.title.trim();
    if (!prNumber || !title) {
      setError('PR number and title are required.');
      return;
    }

    // Build payload — prioritize manually-entered values, fall back to O&M-sourced
    const payload: CreateProjectInput = { pr_number: prNumber, title };
    if (form.description.trim()) payload.description = form.description.trim();

    // Location: use manually-edited value if provided, otherwise O&M-sourced
    if (form.location.trim()) {
      payload.location = form.location.trim();
      // User overrode the O&M auto-population
    } else if (form._om_source === 'om' && form._om_location) {
      payload.location = form._om_location;
    }

    // PI name: use manually-edited value if provided, otherwise O&M-sourced
    if (form.pi_name.trim()) {
      payload.pi_name = form.pi_name.trim();
      // User overrode the O&M auto-population
    } else if (form._om_source === 'om' && form._om_pi) {
      payload.pi_name = form._om_pi;
    }

    if (form.pi_email.trim()) payload.pi_email = form.pi_email.trim();
    if (form.funding_source.trim()) payload.funding_source = form.funding_source.trim();

    setError(null);
    setSubmitting(true);
    try {
      const created = await createProject(payload);
      // Uploads happen on the detail page after creation.
      router.push(`/projects/${created.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(`A project with PR number "${prNumber}" already exists.`);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to create the project.');
      }
      setSubmitting(false);
    }
  }

  if (!loading && user && !canDo(user, 'projects.create')) {
    return (
      <div className="min-h-screen">
        <Header user={user} />
        <main className="mx-auto max-w-6xl px-4 py-8">
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            You don&apos;t have permission to create project requests.
          </div>
          <Link
            href="/"
            className="mt-4 inline-block text-sm font-medium text-apple-text underline"
          >
            ← Back to register
          </Link>
        </main>
      </div>
    );
  }

  const inputClass =
    'mt-1 block w-full rounded-md border border-apple-border px-3 py-2 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary';
  const labelClass = 'block text-sm font-medium text-apple-text';

  return (
    <div className="min-h-screen">
      <Header user={user} />
      <main className="mx-auto max-w-3xl px-4 py-8">
        <Link href="/" className="text-sm font-medium text-apple-muted hover:text-apple-text">
          ← Back to register
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-apple-text">
          New Project Request
        </h1>
        <p className="mt-1 text-sm text-apple-muted">
          Register a new lab-modification PR. Attachments can be uploaded on the next screen.
        </p>

        <form
          onSubmit={handleSubmit}
          className="mt-6 rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm"
        >
          {error && (
            <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
          <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            <div>
              <label htmlFor="pr_number" className={labelClass}>
                PR Number <span className="text-red-600">*</span>
              </label>
              <input
                id="pr_number"
                type="text"
                required
                value={form.pr_number}
                onChange={update('pr_number')}
                placeholder="e.g. PR-2026-001"
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="title" className={labelClass}>
                Title <span className="text-red-600">*</span>
              </label>
              <input
                id="title"
                type="text"
                required
                value={form.title}
                onChange={update('title')}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="pi_name" className={labelClass}>
                PI Name
                {form._om_source === 'om' && (
                  <span className="text-xs text-apple-muted/60">
                    (from O&M Tracking Sheet)
                  </span>
                )}
              </label>
              <input
                id="pi_name"
                type="text"
                value={form.pi_name}
                onChange={update('pi_name')}
                className={inputClass}
              />
              {/* Hidden field for O&M-sourced PI */}
              <input
                type="hidden"
                name="_om_pi"
                value={form._om_pi}
                defaultValue={form._om_pi}
              />
              <input
                type="hidden"
                name="_om_pi_source"
                value={form._om_source}
                defaultValue={form._om_source}
              />
            </div>
            <div>
              <label htmlFor="pi_email" className={labelClass}>
                PI Email
              </label>
              <input
                id="pi_email"
                type="email"
                value={form.pi_email}
                onChange={update('pi_email')}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="location" className={labelClass}>
                Location
                {form._om_source === 'om' && (
                  <span className="text-xs text-apple-muted/60">
                    (from O&M Tracking Sheet)
                  </span>
                )}
                {form._om_source === 'om' && form._om_detail_location && (
                  <span className="text-xs text-apple-muted/60">
                    • Detail: {form._om_detail_location}
                  </span>
                )}
              </label>
              <input
                id="location"
                type="text"
                value={form.location}
                onChange={update('location')}
                placeholder="Building / room"
                className={inputClass}
              />
              {/* Hidden field for O&M-sourced location */}
              <input
                type="hidden"
                name="_om_location"
                value={form._om_location}
                defaultValue={form._om_location}
              />
              <input
                type="hidden"
                name="_om_detail_location"
                value={form._om_detail_location}
                defaultValue={form._om_detail_location}
              />
            </div>
            <div>
              <label htmlFor="funding_source" className={labelClass}>
                Funding Source
              </label>
              <input
                id="funding_source"
                type="text"
                value={form.funding_source}
                onChange={update('funding_source')}
                className={inputClass}
              />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="description" className={labelClass}>
                Description
              </label>
              <textarea
                id="description"
                rows={4}
                value={form.description}
                onChange={update('description')}
                className={inputClass}
              />
            </div>
          </div>

          <div className="mt-6 flex items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-apple-surface disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? 'Creating…' : 'Create PR'}
            </button>
            <Link
              href="/"
              className="rounded-md border border-apple-border px-4 py-2 text-sm font-medium text-apple-text hover:bg-apple-surface"
            >
              Cancel
            </Link>
          </div>
        </form>
      </main>
    </div>
  );
}

