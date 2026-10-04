'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { listContacts } from '@/lib/api';
import type { ContactList } from '@/lib/api';
import { KpiCard, PbiCanvas, VisualCard } from '@/components/powerbi/PowerBI';
import { useUser } from '@/lib/useUser';
import { stageName } from '@/lib/stages';

/**
 * The PI / requester directory.
 *
 * Every PR already names the person who owns it, so the directory is derived
 * from the register rather than maintained by hand: one row per person, their
 * email front and centre for the TQ / EAR mail, and the PRs they own. It can
 * never drift from the register because it *is* the register.
 */
export default function ContactsPage() {
  return (
    <AuthGuard>
      <Contacts />
    </AuthGuard>
  );
}

function Contacts() {
  const { user } = useUser();
  const [data, setData] = useState<ContactList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(() => {
    listContacts(query)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load the directory'));
  }, [query]);

  useEffect(() => {
    load();
  }, [load]);

  async function copy(email: string) {
    try {
      await navigator.clipboard.writeText(email);
      setCopied(email);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  }

  const contacts = data?.contacts ?? [];

  return (
    <div className="min-h-screen bg-apple-surface/50">
      <Header user={user} />
      <main className="mx-auto max-w-6xl space-y-4 px-4 py-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-apple-text">PI / requester directory</h1>
          <p className="mt-1 text-sm text-apple-muted">
            Who owns which PR, and the email to write to. Built from the register
            (PI name and PI email), so it stays in step with the projects.
          </p>
        </div>

        {error && <ErrorBox message={error} />}

        <PbiCanvas>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <KpiCard label="People" value={data?.total ?? 0} hint="named on a PR" accent="navy" />
            <KpiCard label="With an email" value={data?.with_email ?? 0} hint="ready to write to" accent="green" />
            <KpiCard
              label="Active owners"
              value={contacts.filter((c) => c.active_count > 0).length}
              hint="have live work"
              accent="blue"
            />
            <KpiCard label="PRs covered" value={contacts.reduce((a, c) => a + c.project_count, 0)} accent="teal" />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200/80 bg-white p-2.5 shadow-sm dark:border-white/10 dark:bg-white/[0.04]">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search a name or an email…"
              className="w-full max-w-sm rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-apple-text outline-none focus:border-primary dark:border-white/10 dark:bg-white/5"
            />
            <span className="text-[11px] text-slate-500">{contacts.length} shown</span>
          </div>

          <VisualCard className="mt-3" title="Contacts" subtitle="click a PR to open it">
            {contacts.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-200 p-8 text-center text-sm text-slate-400">
                Nobody matches that search.
              </p>
            ) : (
              <ul className="space-y-2">
                {contacts.map((contact) => (
                  <li
                    key={contact.name + contact.email}
                    className="rounded-lg border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-white/[0.03]"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-apple-text">{contact.name || '(no name)'}</span>
                      {contact.email ? (
                        <>
                          <a
                            href={'mailto:' + contact.email}
                            className="font-mono text-[11px] text-primary hover:underline"
                          >
                            {contact.email}
                          </a>
                          <button
                            type="button"
                            onClick={() => void copy(contact.email)}
                            className="rounded border border-slate-200 px-2 py-0.5 text-[10px] font-semibold text-slate-500 hover:bg-slate-50 dark:border-white/10"
                          >
                            {copied === contact.email ? 'copied' : 'copy'}
                          </button>
                        </>
                      ) : (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                          no email on file
                        </span>
                      )}
                      <span className="ml-auto text-[11px] text-slate-500">
                        {contact.active_count} active · {contact.project_count} PRs
                      </span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {contact.projects.map((project) => (
                        <Link
                          key={project.id}
                          href={'/projects/' + project.id}
                          className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600 hover:bg-slate-200 dark:bg-white/10"
                        >
                          {project.pr_number} · {stageName(project.stage)}
                        </Link>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </VisualCard>
        </PbiCanvas>
      </main>
    </div>
  );
}
