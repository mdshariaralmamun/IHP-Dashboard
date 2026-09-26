'use client';

import { useCallback, useEffect, useState } from 'react';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import {
  approveAccessRequest,
  listAccessRequests,
  rejectAccessRequest,
  reissueAccessInvite,
  type AccessRequestInbox,
  type AccessRequestRow,
} from '@/lib/api';
import { useUser } from '@/lib/useUser';

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800',
  approved: 'bg-emerald-100 text-emerald-800',
  rejected: 'bg-gray-100 text-gray-600',
};

export default function AccessRequestsPage() {
  return (
    <AuthGuard>
      <InboxView />
    </AuthGuard>
  );
}

function InboxView() {
  const { user } = useUser();
  const [data, setData] = useState<AccessRequestInbox | null>(null);
  const [filter, setFilter] = useState<'pending' | 'approved' | 'rejected' | ''>('pending');
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [roleChoice, setRoleChoice] = useState<Record<number, string>>({});
  const [copied, setCopied] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await listAccessRequests(filter || undefined);
      setData(res);
      setRoleChoice((prev) => {
        const next = { ...prev };
        for (const item of res.items) {
          if (!next[item.id]) next[item.id] = item.requested_role;
        }
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the inbox');
    }
  }, [filter]);

  useEffect(() => { void load(); }, [load]);

  async function approve(item: AccessRequestRow) {
    setBusy(item.id);
    setError(null);
    try {
      const res = await approveAccessRequest(item.id, roleChoice[item.id] || item.requested_role);
      const link = inviteLink(res.request) ?? inviteLinkFromToken(res.request.invite_token);
      if (link) await copy(link, item.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not approve');
    } finally {
      setBusy(null);
    }
  }

  async function reject(item: AccessRequestRow) {
    setBusy(item.id);
    setError(null);
    try {
      await rejectAccessRequest(item.id, note || undefined);
      setNote('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reject');
    } finally {
      setBusy(null);
    }
  }

  async function reissue(item: AccessRequestRow) {
    setBusy(item.id);
    try {
      const res = await reissueAccessInvite(item.id);
      const link = inviteLink(res.request) ?? inviteLinkFromToken(res.request.invite_token);
      if (link) await copy(link, item.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create a new link');
    } finally {
      setBusy(null);
    }
  }

  function inviteLinkFromToken(token: string | null): string | null {
    if (!token || typeof window === 'undefined') return null;
    return window.location.origin + '/invite/' + token;
  }

  function inviteLink(row: AccessRequestRow): string | null {
    if (!row.invite_token) return null;
    return inviteLinkFromToken(row.invite_token);
  }

  async function copy(link: string, id: number) {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(id);
      window.setTimeout(() => setCopied(null), 2500);
    } catch {
      /* clipboard unavailable */
    }
  }

  const pending = data?.pending ?? 0;

  return (
    <div className="min-h-screen">
      <Header user={user} />
      <main className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-apple-text">
              Access requests
            </h1>
            <p className="mt-1 text-sm text-apple-muted">
              Approve to create the account and copy its invite link; send that link to the
              person so they can set a password.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
              {pending} pending
            </span>
            <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800">
              {data?.approved ?? 0} approved
            </span>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          {(['pending', 'approved', 'rejected', ''] as const).map((key) => (
            <button
              key={key || 'all'}
              type="button"
              onClick={() => setFilter(key)}
              className={
                'rounded-full border px-3 py-1.5 text-xs font-semibold transition ' +
                (filter === key
                  ? 'border-apple-primary bg-apple-primary/10 text-apple-primary'
                  : 'border-apple-border text-apple-text hover:bg-black/5 dark:hover:bg-white/10')
              }
            >
              {key === '' ? 'All' : key.charAt(0).toUpperCase() + key.slice(1)}
            </button>
          ))}
        </div>

        {error && <ErrorBox message={error} onRetry={load} />}

        {!data && !error && (
          <p className="py-12 text-center text-sm text-apple-muted">Loading…</p>
        )}

        {data && data.items.length === 0 && (
          <p className="rounded-xl border border-apple-border bg-white p-6 text-center text-sm text-apple-muted dark:bg-white/[0.04]">
            Nothing here yet.
          </p>
        )}

        <div className="space-y-3">
          {data?.items.map((item) => (
            <article
              key={item.id}
              className="rounded-xl border border-apple-border bg-white p-4 dark:bg-white/[0.04]"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-semibold text-apple-text">
                    {item.full_name}
                    <span className={'rounded-full px-2 py-0.5 text-[10px] font-semibold ' + (STATUS_STYLE[item.status] ?? '')}>
                      {item.status}
                    </span>
                    <span className="text-[10px] font-mono text-apple-muted">{item.reference}</span>
                  </p>
                  <p className="mt-0.5 text-xs text-apple-muted">
                    {item.email}
                    {item.phone ? ' · ' + item.phone : ''}
                    {item.company ? ' · ' + item.company : ''}
                  </p>
                  <p className="mt-1 text-xs text-apple-muted">
                    Wants: <span className="font-medium text-apple-text">{item.requested_role_label}</span>
                    {item.created_at ? ' · ' + new Date(item.created_at).toLocaleString() : ''}
                  </p>
                  {item.message && (
                    <p className="mt-1 max-w-2xl text-xs italic text-apple-muted">“{item.message}”</p>
                  )}
                  {item.decision_note && (
                    <p className="mt-1 text-xs text-apple-muted">Note: {item.decision_note}</p>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {item.status === 'pending' && (
                    <>
                      <select
                        value={roleChoice[item.id] ?? item.requested_role}
                        onChange={(e) => setRoleChoice({ ...roleChoice, [item.id]: e.target.value })}
                        className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs text-apple-text dark:bg-[#1c1c1e]"
                      >
                        {(data.roles ?? []).map((role) => (
                          <option key={role.value} value={role.value}>
                            {role.label.split(' - ')[0]}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={busy === item.id}
                        onClick={() => void approve(item)}
                        className="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                      >
                        {busy === item.id ? 'Working…' : 'Approve'}
                      </button>
                      <button
                        type="button"
                        disabled={busy === item.id}
                        onClick={() => void reject(item)}
                        className="rounded-full border border-apple-border px-4 py-1.5 text-xs font-semibold text-apple-text transition hover:bg-black/5 disabled:opacity-50 dark:hover:bg-white/10"
                      >
                        Reject
                      </button>
                    </>
                  )}

                  {item.status === 'approved' && (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          const link = inviteLink(item);
                          if (link) void copy(link, item.id);
                        }}
                        className="rounded-full border border-apple-border px-4 py-1.5 text-xs font-semibold text-apple-text transition hover:bg-black/5 dark:hover:bg-white/10"
                      >
                        {copied === item.id ? 'Link copied ✓' : 'Copy invite link'}
                      </button>
                      <button
                        type="button"
                        disabled={busy === item.id}
                        onClick={() => void reissue(item)}
                        className="rounded-full px-3 py-1.5 text-xs font-medium text-apple-muted underline disabled:opacity-50"
                      >
                        New link
                      </button>
                      {item.invite_used_at && (
                        <span className="text-[11px] text-emerald-600 dark:text-emerald-400">
                          password set
                        </span>
                      )}
                    </>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>

        <div className="mt-6 rounded-xl border border-apple-border bg-white p-4 dark:bg-white/[0.04]">
          <label className="block text-xs font-medium text-apple-muted">
            Note attached to the next rejection (optional)
          </label>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="mt-1 w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
            placeholder="e.g. external contractor - use the guest process"
          />
        </div>
      </main>
    </div>
  );
}
