'use client';

import { useEffect, useState } from 'react';
import { getMe } from './api';
import type { User } from './types';

/** Fetch the current user once on mount. A 401 inside getMe redirects to /login. */
export function useUser(): { user: User | null; loading: boolean } {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (!cancelled) {
          setUser(me);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { user, loading };
}

/** Capability check against the user's effective permissions. */
export function canDo(user: User | null, cap: string): boolean {
  return (user?.permissions ?? []).includes(cap);
}
