'use client';

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError, getToken, login } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace('/');
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      router.replace('/');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Invalid credentials.');
      } else {
        setError(err instanceof Error ? err.message : 'Login failed.');
      }
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 bg-apple-bg">
      <div className="w-full max-w-sm text-center">
        {/* Hero Typography for Login */}
        <h1 className="text-[48px] leading-tight font-bold tracking-tight text-apple-text mb-12">
          KAUST IHP
        </h1>

        <form onSubmit={handleSubmit} className="space-y-6 text-left">
          {error && (
            <div className="rounded-lg bg-status-rejected/10 px-4 py-3 text-sm text-status-rejected border border-status-rejected/20 text-center">
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div>
              <input
                id="username"
                type="text"
                autoComplete="username"
                placeholder="Username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="block w-full rounded-xl border border-apple-border bg-white dark:bg-[#1c1c1e] text-gray-900 dark:text-gray-100 px-4 py-3.5 text-base shadow-sm transition-colors placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="Password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="block w-full rounded-xl border border-apple-border bg-white dark:bg-[#1c1c1e] text-gray-900 dark:text-gray-100 px-4 py-3.5 text-base shadow-sm transition-colors placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-full bg-primary px-4 py-3.5 text-base font-semibold text-white shadow-sm transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 mt-4"
          >
            {submitting ? 'Authenticating…' : 'Sign In'}
          </button>
        </form>

        <p className="mt-12 text-xs text-apple-muted">
          Project Delivery Platform &middot; Authorized Access Only
        </p>
      </div>
    </div>
  );
}
