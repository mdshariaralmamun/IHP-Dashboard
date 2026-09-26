'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';
import AiChat from '@/components/AiChat';
import { getToken } from '@/lib/api';

/** Client-side auth guard: without a stored token, redirect to /login. */
export default function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    } else {
      setReady(true);
    }
  }, [router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-apple-surface/50">
        <p className="text-sm text-apple-muted">Loading…</p>
      </div>
    );
  }
  return (
    <>
      {children}
      <AiChat />
    </>
  );
}

