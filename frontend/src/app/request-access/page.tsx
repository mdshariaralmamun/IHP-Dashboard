'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getPublicDashboard, requestAccess } from '@/lib/api';

/** Public form: ask for an account. An admin decides inside the platform. */
export default function RequestAccessPage() {
  const [roles, setRoles] = useState<{ value: string; label: string }[]>([]);
  const [form, setForm] = useState({
    full_name: '',
    email: '',
    phone: '',
    company: '',
    requested_role: 'viewer',
    message: '',
  });
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ reference: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPublicDashboard()
      .then((d) => {
        setRoles(d.requestable_roles);
        if (d.requestable_roles.length) {
          setForm((f) => ({ ...f, requested_role: f.requested_role || d.requestable_roles[0].value }));
        }
      })
      .catch(() => setRoles([]));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await requestAccess({
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim() || undefined,
        company: form.company.trim() || undefined,
        requested_role: form.requested_role,
        message: form.message.trim() || undefined,
      });
      setDone({ reference: res.reference, message: res.message });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send the request');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-apple-bg text-apple-text">
      <header className="border-b border-apple-border/60 bg-white/70 backdrop-blur-xl dark:bg-[#161618]/80">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-5 py-4">
          <Link href="/" className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/kaust_logo.png" alt="KAUST" className="h-9" />
            <span className="text-sm font-semibold">IHP Project Delivery Platform</span>
          </Link>
          <Link href="/" className="text-sm font-medium text-apple-muted hover:text-apple-text">
            ← Back to overview
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-5 py-10">
        {done ? (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6 dark:border-emerald-900 dark:bg-emerald-950/40">
            <h1 className="text-xl font-bold text-emerald-900 dark:text-emerald-200">
              Request received
            </h1>
            <p className="mt-2 text-sm text-emerald-900/90 dark:text-emerald-100/90">
              {done.message}
            </p>
            <p className="mt-3 text-sm font-semibold text-emerald-900 dark:text-emerald-200">
              Your reference: {done.reference}
            </p>
            <p className="mt-2 text-xs text-emerald-900/80 dark:text-emerald-100/80">
              An administrator reviews it inside the platform and sends you a personal
              link. Open that link to set your password.
            </p>
            <Link
              href="/"
              className="mt-4 inline-block rounded-full bg-primary px-5 py-2 text-sm font-semibold text-white"
            >
              Back to the overview
            </Link>
          </div>
        ) : (
          <>
            <h1 className="text-3xl font-bold tracking-tight">Request access</h1>
            <p className="mt-2 text-sm text-apple-muted">
              The platform is invitation-based. Tell us who you are and which role you need;
              an administrator approves it and sends you a private link to set your password.
            </p>

            <form onSubmit={submit} className="mt-6 space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Full name" required>
                  <input
                    required
                    value={form.full_name}
                    onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                    className="w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
                  />
                </Field>
                <Field label="Work email" required>
                  <input
                    required
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    className="w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
                  />
                </Field>
                <Field label="Phone (optional)">
                  <input
                    value={form.phone}
                    onChange={(e) => setForm({ ...form, phone: e.target.value })}
                    placeholder="+966…"
                    className="w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
                  />
                </Field>
                <Field label="Company / department (optional)">
                  <input
                    value={form.company}
                    onChange={(e) => setForm({ ...form, company: e.target.value })}
                    className="w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
                  />
                </Field>
              </div>

              <Field label="Requested role" required>
                <select
                  value={form.requested_role}
                  onChange={(e) => setForm({ ...form, requested_role: e.target.value })}
                  className="w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
                >
                  {(roles.length
                    ? roles
                    : [
                        { value: 'viewer', label: 'Viewer - read-only dashboards' },
                        { value: 'team_member', label: 'Team member' },
                      ]
                  ).map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Why do you need access? (optional)">
                <textarea
                  rows={4}
                  value={form.message}
                  onChange={(e) => setForm({ ...form, message: e.target.value })}
                  placeholder="Project, trade or team you work with…"
                  className="w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
                />
              </Field>

              {error && (
                <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={busy}
                className="rounded-full bg-primary px-6 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
              >
                {busy ? 'Sending…' : 'Send request'}
              </button>
            </form>
          </>
        )}
      </main>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-apple-muted">
        {label}
        {required ? ' *' : ''}
      </span>
      {children}
    </label>
  );
}
