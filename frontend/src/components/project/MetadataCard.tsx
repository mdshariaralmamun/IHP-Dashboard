'use client';

import { useState } from 'react';
import ErrorBox from '@/components/ErrorBox';
import StageBadge from '@/components/StageBadge';
import { setDisposition, updateProject } from '@/lib/api';
import { formatDate } from '@/lib/format';
import type { CreateProjectInput, ProjectDetail } from '@/lib/types';

const inputClass =
  'mt-1 block w-full rounded-md border border-apple-border px-2.5 py-1.5 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary';

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-apple-muted">{label}</dt>
      <dd className="mt-1 text-sm text-apple-text">{value ?? '—'}</dd>
    </div>
  );
}

type EditableField = 'title' | 'location' | 'pi_name' | 'pi_email' | 'funding_source' | 'description';

const EDITABLE: { field: EditableField; label: string }[] = [
  { field: 'title', label: 'Title' },
  { field: 'pi_name', label: 'PI Name' },
  { field: 'pi_email', label: 'PI Email' },
  { field: 'location', label: 'Location' },
  { field: 'funding_source', label: 'Funding Source' },
  { field: 'description', label: 'Description' },
];

export default function MetadataCard({
  project,
  canEdit,
  onChanged,
}: {
  project: ProjectDetail;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Record<EditableField, string> & { justification: string }>({
    title: '',
    location: '',
    pi_name: '',
    pi_email: '',
    funding_source: '',
    description: '',
    justification: '',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit() {
    setForm({
      title: project.title,
      location: project.location ?? '',
      pi_name: project.pi_name ?? '',
      pi_email: project.pi_email ?? '',
      funding_source: project.funding_source ?? '',
      description: project.description ?? '',
      justification: '',
    });
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    if (busy) return;
    if (!form.title.trim()) {
      setError('Title is required.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const patch: Partial<CreateProjectInput> = {
        title: form.title.trim(),
        location: form.location.trim(),
        pi_name: form.pi_name.trim(),
        pi_email: form.pi_email.trim(),
        funding_source: form.funding_source.trim(),
        description: form.description.trim(),
      };
      await updateProject(project.id, patch);
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.');
    } finally {
      setBusy(false);
    }
  }

  async function handleConvertToIcr() {
    if (!form.justification.trim()) {
      setError('Justification is required for ICR conversion.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // Disposition changes go through the dedicated (audited) endpoint,
      // not the generic project PATCH — the PATCH schema drops the field.
      await setDisposition(project.id, 'ICR', form.justification.trim());
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ICR conversion failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-apple-muted">
          Project Details
        </h2>
        {canEdit && !editing && (
          <button
            type="button"
            onClick={startEdit}
            className="text-sm font-medium text-apple-text underline"
          >
            Edit
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {editing ? (
        <div>
          <div className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
            {EDITABLE.map(({ field, label }) => (
              <div key={field}>
                <label className="block text-xs font-medium text-apple-muted">{label}</label>
                <input
                  type="text"
                  value={form[field]}
                  onChange={(e) => setForm((prev) => ({ ...prev, [field]: e.target.value }))}
                  className={inputClass}
                />
              </div>
            ))}
            {/* ICR Conversion Section */}
            <div>
              <label className="block text-xs font-medium text-apple-muted">
                Convert to ICR
              </label>
              <p className="mt-2 text-xs text-apple-muted/60">
                Routes project straight to MTO (skips EAR & SOW). ICR-classified
                projects do not go through construction, EAR, or SOW stages.
              </p>
              <textarea
                rows={3}
                value={form.justification}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    justification: e.target.value,
                  }))
                }
                className={inputClass}
                placeholder="Enter justification for ICR classification..."
              />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={busy}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-primary/90 disabled:opacity-50"
              >
                {busy ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => void handleConvertToIcr()}
                disabled={busy}
                className="rounded-md bg-orange-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50"
              >
                Convert to ICR
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="rounded-md border border-apple-border px-3 py-1.5 text-sm font-medium text-apple-text hover:bg-apple-surface"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : (
        <>
          <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="PR Number" value={project.pr_number} />
            <Field label="Stage" value={<StageBadge stage={project.stage} />} />
            <Field label="Disposition" value={project.disposition} />
            <Field label="PI Name" value={project.pi_name} />
            <Field label="PI Email" value={project.pi_email} />
            <Field label="Location" value={project.location} />
            <Field label="Funding Source" value={project.funding_source} />
            <Field label="Created" value={formatDate(project.created_at)} />
          </dl>
          {project.description && (
            <div className="mt-4 border-t border-apple-border pt-4">
              <dt className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
                Description
              </dt>
              <dd className="mt-1 whitespace-pre-wrap text-sm text-apple-text">
                {project.description}
              </dd>
            </div>
          )}
          {canEdit && (
            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={startEdit}
                className="text-sm font-medium text-apple-text underline"
              >
                Edit
              </button>
              {/* ICR convert button when not editing and not already ICR */}
              {project.disposition !== 'ICR' && (
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="text-sm font-medium text-orange-600 underline"
                >
                  Convert to ICR
                </button>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}