'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { acceptInvite, getInvite, setToken } from '@/lib/api';

/** Landing page for an invite link: set a password and go straight in. */
export default function InvitePage() {
  const params = useParams<{ token: string }>();
  const router = useRouter();
  const token = typeof params?.token === 'string' ? params.token : '';

  const [info, setInfo] = useState<{ full_name: string; email: string; role: string; username: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    getInvite(token)
      .then((d) => setInfo(d))
      .catch((e) => setError(e instanceof Error ? e.message : 'This invite link is not valid'));
  }, [token]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }
    if (password.length < 8) {
      setError('Use at least 8 characters.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await acceptInvite(token, password);
      setToken(res.access_token);
      router.replace('/');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not set the password');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-apple-bg px-5 text-apple-text">
      <div className="w-full max-w-md rounded-2xl border border-apple-border bg-white p-6 shadow-sm dark:bg-white/[0.04]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/kaust_logo.png" alt="KAUST" className="h-10" />
        <h1 className="mt-4 text-xl font-bold">Set your password</h1>

        {error && (
          <p className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
            {error}
          </p>
        )}

        {info && !error && (
          <>
            <p className="mt-2 text-sm text-apple-muted">
              Welcome {info.full_name}. This link creates the account for{' '}
              <span className="font-medium text-apple-text">{info.email}</span> with the{' '}
              <span className="font-medium text-apple-text">{info.role}</span> role.
            </p>
            <form onSubmit={submit} className="mt-5 space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-apple-muted">
                  New password
                </span>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-apple-muted">
                  Repeat password
                </span>
                <input
                  type="password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="w-full rounded-md border border-apple-border bg-white px-3 py-2 text-sm text-apple-text dark:bg-[#1c1c1e]"
                />
              </label>
              <button
                type="submit"
                disabled={busy}
                className="w-full rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
              >
                {busy ? 'Saving…' : 'Activate my account'}
              </button>
            </form>
            <p className="mt-3 text-[11px] text-apple-muted">
              Your username will be <span className="font-mono">{info.username}</span>. You can
              change the password later in your profile.
            </p>
          </>
        )}

        {!info && !error && (
          <p className="mt-4 text-sm text-apple-muted">Checking the link…</p>
        )}

        <Link href="/" className="mt-5 inline-block text-xs text-apple-muted hover:text-apple-text">
          ← Back to the overview
        </Link>
      </div>
    </div>
  );
}
