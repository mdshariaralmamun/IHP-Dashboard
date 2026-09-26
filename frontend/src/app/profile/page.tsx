'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import AuthGuard from '@/components/AuthGuard';
import Header from '@/components/Header';
import { useUser } from '@/lib/useUser';
import {
  updateProfile,
  changePassword,
  getMyRoles,
  type UserRbacRole,
  type MyRolesResponse,
} from '@/lib/api';

/* ─── tiny helpers ─── */
function SectionCard({
  id,
  title,
  icon,
  children,
}: {
  id?: string;
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      className="overflow-hidden rounded-2xl border border-apple-border bg-apple-surface shadow-sm"
    >
      <div className="flex items-center gap-3 border-b border-apple-border/60 px-6 py-4">
        <span className="text-apple-muted">{icon}</span>
        <h2 className="text-base font-semibold text-apple-text">{title}</h2>
      </div>
      <div className="px-6 py-5">{children}</div>
    </section>
  );
}

function Badge({ color, label }: { color: string; label: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold"
      style={{
        background: `${color}18`,
        color,
        border: `1px solid ${color}40`,
      }}
    >
      <span
        className="h-2 w-2 rounded-full"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}

/* ─── main page ─── */
export default function ProfilePage() {
  const { user, loading: userLoading } = useUser();

  /* --- profile form state --- */
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [title, setTitle] = useState('');
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMsg, setProfileMsg] = useState<{ ok: boolean; text: string } | null>(null);

  /* --- password form state --- */
  const [curPwd, setCurPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [pwdSaving, setPwdSaving] = useState(false);
  const [pwdMsg, setPwdMsg] = useState<{ ok: boolean; text: string } | null>(null);

  /* --- roles state --- */
  const [roles, setRoles] = useState<UserRbacRole[]>([]);
  const [permissions, setPermissions] = useState<Record<string, Record<string, boolean>>>({});
  const [rolesLoading, setRolesLoading] = useState(true);

  /* Seed form once user loads */
  useEffect(() => {
    if (user) {
      setFullName(user.full_name ?? '');
      setEmail(user.email ?? '');
      setTitle(user.title ?? '');
    }
  }, [user]);

  /* Fetch RBAC roles */
  const loadRoles = useCallback(async () => {
    setRolesLoading(true);
    try {
      const data: MyRolesResponse = await getMyRoles();
      setRoles(data.roles);
      setPermissions(data.effective_permissions);
    } catch {
      // silent – section will show empty
    } finally {
      setRolesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRoles();
  }, [loadRoles]);

  /* Scroll to hash on mount */
  const didScroll = useRef(false);
  useEffect(() => {
    if (didScroll.current) return;
    const hash = window.location.hash.replace('#', '');
    if (!hash) return;
    const el = document.getElementById(hash);
    if (el) {
      didScroll.current = true;
      setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 200);
    }
  }, [userLoading, rolesLoading]);

  /* --- handlers --- */
  async function handleProfileSave(e: React.FormEvent) {
    e.preventDefault();
    setProfileSaving(true);
    setProfileMsg(null);
    try {
      await updateProfile({ full_name: fullName, email, title });
      setProfileMsg({ ok: true, text: 'Profile updated successfully.' });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to update profile';
      setProfileMsg({ ok: false, text: msg });
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwdMsg(null);
    if (newPwd !== confirmPwd) {
      setPwdMsg({ ok: false, text: 'New passwords do not match.' });
      return;
    }
    if (newPwd.length < 6) {
      setPwdMsg({ ok: false, text: 'New password must be at least 6 characters.' });
      return;
    }
    setPwdSaving(true);
    try {
      await changePassword(curPwd, newPwd);
      setPwdMsg({ ok: true, text: 'Password changed successfully.' });
      setCurPwd('');
      setNewPwd('');
      setConfirmPwd('');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to change password';
      setPwdMsg({ ok: false, text: msg });
    } finally {
      setPwdSaving(false);
    }
  }

  /* --- derived --- */
  const permEntries = Object.entries(permissions).sort(([a], [b]) => a.localeCompare(b));
  const actionLabels: Record<string, string> = {
    can_read: 'Read',
    can_write: 'Write',
    can_delete: 'Delete',
    can_approve: 'Approve',
    can_manage: 'Manage',
  };

  return (
    <AuthGuard>
      <Header user={user ?? null} />
      <main className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-apple-text">My Profile</h1>
          <p className="mt-1 text-sm text-apple-muted">
            Manage your account information, password, and view your roles.
          </p>
        </div>

        {/* ── 1. Profile Info ── */}
        <SectionCard
          id="profile"
          title="Profile Information"
          icon={
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          }
        >
          {userLoading ? (
            <p className="animate-pulse text-sm text-apple-muted">Loading…</p>
          ) : (
            <form onSubmit={handleProfileSave} className="space-y-4">
              {/* Username (read-only) */}
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-apple-muted">
                  Username
                </label>
                <input
                  value={user?.username ?? ''}
                  disabled
                  className="w-full rounded-lg border border-apple-border bg-black/5 px-3 py-2 text-sm text-apple-muted dark:bg-white/5"
                />
              </div>

              {/* Full Name */}
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-apple-muted">
                  Full Name
                </label>
                <input
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full rounded-lg border border-apple-border bg-white/50 px-3 py-2 text-sm text-apple-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary dark:bg-white/10"
                />
              </div>

              {/* Email */}
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-apple-muted">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-lg border border-apple-border bg-white/50 px-3 py-2 text-sm text-apple-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary dark:bg-white/10"
                />
              </div>

              {/* Title */}
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-apple-muted">
                  Job Title
                </label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. Senior Project Engineer"
                  className="w-full rounded-lg border border-apple-border bg-white/50 px-3 py-2 text-sm text-apple-text placeholder:text-apple-muted/60 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary dark:bg-white/10"
                />
              </div>

              {profileMsg && (
                <p className={`text-sm ${profileMsg.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                  {profileMsg.text}
                </p>
              )}

              <button
                type="submit"
                disabled={profileSaving}
                className="rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {profileSaving ? 'Saving…' : 'Save Changes'}
              </button>
            </form>
          )}
        </SectionCard>

        {/* ── 2. Change Password ── */}
        <SectionCard
          id="password"
          title="Change Password"
          icon={
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
            </svg>
          }
        >
          <form onSubmit={handleChangePassword} className="space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-apple-muted">
                Current Password
              </label>
              <input
                type="password"
                value={curPwd}
                onChange={(e) => setCurPwd(e.target.value)}
                required
                className="w-full rounded-lg border border-apple-border bg-white/50 px-3 py-2 text-sm text-apple-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary dark:bg-white/10"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-apple-muted">
                New Password
              </label>
              <input
                type="password"
                value={newPwd}
                onChange={(e) => setNewPwd(e.target.value)}
                required
                minLength={6}
                className="w-full rounded-lg border border-apple-border bg-white/50 px-3 py-2 text-sm text-apple-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary dark:bg-white/10"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-apple-muted">
                Confirm New Password
              </label>
              <input
                type="password"
                value={confirmPwd}
                onChange={(e) => setConfirmPwd(e.target.value)}
                required
                minLength={6}
                className="w-full rounded-lg border border-apple-border bg-white/50 px-3 py-2 text-sm text-apple-text focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary dark:bg-white/10"
              />
            </div>

            {pwdMsg && (
              <p className={`text-sm ${pwdMsg.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                {pwdMsg.text}
              </p>
            )}

            <button
              type="submit"
              disabled={pwdSaving}
              className="rounded-lg bg-primary px-5 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
            >
              {pwdSaving ? 'Changing…' : 'Change Password'}
            </button>
          </form>
        </SectionCard>

        {/* ── 3. My Roles & Permissions ── */}
        <SectionCard
          id="roles"
          title="My Roles & Permissions"
          icon={
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          }
        >
          {rolesLoading ? (
            <p className="animate-pulse text-sm text-apple-muted">Loading roles…</p>
          ) : roles.length === 0 ? (
            <p className="text-sm text-apple-muted">No RBAC roles assigned yet.</p>
          ) : (
            <div className="space-y-5">
              {/* Role badges */}
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-apple-muted">
                  Assigned Roles
                </p>
                <div className="flex flex-wrap gap-2">
                  {roles.map((r) => (
                    <Badge key={r.id} color={r.color} label={r.display_name} />
                  ))}
                </div>
              </div>

              {/* Permission matrix */}
              {permEntries.length > 0 && (
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-apple-muted">
                    Effective Permissions
                  </p>
                  <div className="overflow-x-auto rounded-lg border border-apple-border">
                    <table className="w-full text-left text-sm">
                      <thead>
                        <tr className="border-b border-apple-border bg-black/[0.02] dark:bg-white/[0.03]">
                          <th className="px-3 py-2 font-medium text-apple-muted">Resource</th>
                          {Object.entries(actionLabels).map(([key, label]) => (
                            <th key={key} className="px-3 py-2 text-center font-medium text-apple-muted">
                              {label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {permEntries.map(([resource, actions]) => (
                          <tr key={resource} className="border-b border-apple-border/40 last:border-0">
                            <td className="px-3 py-2 font-medium text-apple-text capitalize">
                              {resource.replace(/_/g, ' ')}
                            </td>
                            {Object.keys(actionLabels).map((key) => (
                              <td key={key} className="px-3 py-2 text-center">
                                {actions[key] ? (
                                  <span className="inline-block h-4 w-4 text-emerald-500">
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                    </svg>
                                  </span>
                                ) : (
                                  <span className="inline-block h-4 w-4 text-apple-muted/30">
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                      <path strokeLinecap="round" strokeLinejoin="round" d="M18 12H6" />
                                    </svg>
                                  </span>
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </SectionCard>

        {/* ── 4. Account Info ── */}
        <SectionCard
          id="account"
          title="Account Information"
          icon={
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
        >
          <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-apple-muted">System Role</p>
              <p className="mt-0.5 font-medium text-apple-text capitalize">{user?.role ?? '—'}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-apple-muted">Trade</p>
              <p className="mt-0.5 font-medium text-apple-text capitalize">{user?.trade ?? '—'}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-apple-muted">Status</p>
              <p className={`mt-0.5 font-medium ${user?.is_active !== false ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                {user?.is_active !== false ? 'Active' : 'Disabled'}
              </p>
            </div>
          </div>
        </SectionCard>
      </main>
    </AuthGuard>
  );
}
