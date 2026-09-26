'use client';

import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import AuthGuard from '@/components/AuthGuard';
import ErrorBox from '@/components/ErrorBox';
import Header from '@/components/Header';
import { ApiError, createUser, deleteUser, listUsers, updateUser } from '@/lib/api';
import { useUser } from '@/lib/useUser';
import { KNOWN_ROLES, PERMISSION_GROUPS, ROLE_DEFAULT_PERMISSIONS, TRADE_OPTIONS, roleLabel } from '@/lib/types';
import type { Role, User } from '@/lib/types';

export default function AdminUsersPage() {
  return (
    <AuthGuard>
      <AdminUsersView />
    </AuthGuard>
  );
}

const inputClass =
  'mt-1 block w-full rounded-md border border-apple-border px-3 py-2 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary';
const labelClass = 'block text-sm font-medium text-apple-text';

interface FormState {
  username: string;
  full_name: string;
  title: string;
  email: string;
  password: string;
  role: Role;
  trade: string;
  tradeMode: 'standard' | 'custom' | 'none';
  is_active: boolean;
  customPerms: boolean;
  perms: string[];
}

const EMPTY_FORM: FormState = {
  username: '',
  full_name: '',
  title: '',
  email: '',
  password: '',
  role: 'trade',
  trade: 'civil_arch',
  tradeMode: 'standard',
  is_active: true,
  customPerms: false,
  perms: [],
};

function tradeLabel(trade: string | null): string {
  if (!trade) return '—';
  return TRADE_OPTIONS.find((t) => t.value === trade)?.label ?? trade;
}

function isCustomPerms(user: User): boolean {
  const effective = [...(user.permissions ?? [])].sort();
  const defaults = [...(ROLE_DEFAULT_PERMISSIONS[user.role] ?? [])].sort();
  return JSON.stringify(effective) !== JSON.stringify(defaults);
}

function AdminUsersView() {
  const { user: me, loading } = useUser();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editing, setEditing] = useState<User | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setUsers(await listUsers());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load users.');
    }
  }, []);

  useEffect(() => {
    if (me?.role === 'admin') void load();
  }, [me, load]);

  if (!loading && me && me.role !== 'admin') {
    return (
      <div className="min-h-screen">
        <Header user={me} />
        <main className="mx-auto max-w-6xl px-4 py-8">
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Only administrators can manage users.
          </div>
        </main>
      </div>
    );
  }

  function set<K extends keyof FormState>(field: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function togglePerm(cap: string) {
    setForm((prev) => ({
      ...prev,
      perms: prev.perms.includes(cap)
        ? prev.perms.filter((p) => p !== cap)
        : [...prev.perms, cap],
    }));
  }

  function startEdit(u: User) {
    setEditing(u);
    setNotice(null);
    setError(null);
    setForm({
      username: u.username,
      full_name: u.full_name,
      title: u.title ?? '',
      email: u.email,
      password: '',
      role: u.role,
      trade: u.trade ?? 'civil_arch',
      tradeMode: !u.trade ? 'none' : TRADE_OPTIONS.some((t) => t.value === u.trade) ? 'standard' : 'custom',
      is_active: u.is_active ?? true,
      customPerms: isCustomPerms(u),
      perms: u.permissions ?? [],
    });
  }

  function cancelEdit() {
    setEditing(null);
    setForm(EMPTY_FORM);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    setNotice(null);

    if (!form.full_name.trim() || (!editing && !form.username.trim())) {
      setError('Username and full name are required.');
      return;
    }
    if (!editing && !form.password) {
      setError('Password is required.');
      return;
    }
    if (form.role === 'trade' && !form.trade) {
      setError('Pick a trade for the trade user.');
      return;
    }

    setBusy(true);
    try {
      const permsPayload = form.customPerms ? form.perms : null;
      if (editing) {
        const updated = await updateUser(editing.id, {
          full_name: form.full_name.trim(),
          title: form.title.trim(),
          email: form.email.trim(),
          role: form.role,
          trade: form.tradeMode === 'none' ? null : form.trade.trim() || null,
          is_active: form.is_active,
          permissions: permsPayload,
          ...(form.password ? { password: form.password } : {}),
        });
        setNotice(`User "${updated.username}" updated.`);
        cancelEdit();
      } else {
        const created = await createUser({
          username: form.username.trim(),
          full_name: form.full_name.trim(),
          title: form.title.trim(),
          email: form.email.trim(),
          password: form.password,
          role: form.role,
          trade: form.tradeMode === 'none' ? null : form.trade.trim() || null,
          permissions: permsPayload,
        });
        setNotice(`User "${created.username}" created.`);
        setForm(EMPTY_FORM);
      }
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError(`Username "${form.username.trim()}" is already taken.`);
      } else {
        setError(err instanceof Error ? err.message : 'Save failed.');
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(u: User) {
    if (!window.confirm(`Delete user "${u.username}"? This cannot be undone.`)) return;
    setError(null);
    setNotice(null);
    try {
      await deleteUser(u.id);
      setNotice(`User "${u.username}" deleted.`);
      if (editing?.id === u.id) cancelEdit();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed.');
    }
  }

  async function handleToggleActive(u: User) {
    setError(null);
    try {
      await updateUser(u.id, { is_active: !(u.is_active ?? true) });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Update failed.');
    }
  }

  return (
    <div className="min-h-screen">
      <Header user={me} />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-2xl font-semibold tracking-tight text-apple-text">User Management</h1>
        <p className="mt-1 text-sm text-apple-muted">
          Create users, assign role and trade access, and tune exactly what each user can do
          with the capability checklist.
        </p>

        <form
          onSubmit={handleSubmit}
          className="mt-6 rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-apple-muted">
              {editing ? `Edit user: ${editing.username}` : 'Create user'}
            </h2>
            {editing && (
              <button
                type="button"
                onClick={cancelEdit}
                className="text-sm font-medium text-apple-muted underline"
              >
                Cancel edit
              </button>
            )}
          </div>

          {error && (
            <div className="mb-4">
              <ErrorBox message={error} />
            </div>
          )}
          {notice && (
            <div className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
              {notice}
            </div>
          )}

          <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-3">
            <div>
              <label htmlFor="username" className={labelClass}>
                Username <span className="text-red-600">*</span>
              </label>
              <input
                id="username"
                type="text"
                required
                value={form.username}
                onChange={(e) => set('username', e.target.value)}
                disabled={editing !== null}
                className={`${inputClass} disabled:bg-apple-surface/50 disabled:text-apple-muted`}
              />
            </div>
            <div>
              <label htmlFor="full_name" className={labelClass}>
                Full name <span className="text-red-600">*</span>
              </label>
              <input
                id="full_name"
                type="text"
                required
                value={form.full_name}
                onChange={(e) => set('full_name', e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="title" className={labelClass}>
                Job title
              </label>
              <input
                id="title"
                type="text"
                value={form.title}
                onChange={(e) => set('title', e.target.value)}
                placeholder="e.g. Lab Equipment Technician"
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="email" className={labelClass}>
                Email
              </label>
              <input
                id="email"
                type="email"
                value={form.email}
                onChange={(e) => set('email', e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="password" className={labelClass}>
                {editing ? 'Reset password (leave blank to keep)' : 'Password'}{' '}
                {!editing && <span className="text-red-600">*</span>}
              </label>
              <input
                id="password"
                type="password"
                value={form.password}
                onChange={(e) => set('password', e.target.value)}
                className={inputClass}
                autoComplete="new-password"
              />
            </div>
            <div>
              <label htmlFor="role" className={labelClass}>
                Role <span className="text-red-600">*</span>
              </label>
              <select
                id="role"
                value={KNOWN_ROLES.includes(form.role) ? form.role : '__custom'}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v !== '__custom') set('role', v);
                  else if (KNOWN_ROLES.includes(form.role)) set('role', '');
                }}
                className={inputClass}
              >
                {KNOWN_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {roleLabel(role)}
                  </option>
                ))}
                <option value="__custom">Custom role…</option>
              </select>
              {!KNOWN_ROLES.includes(form.role) && (
                <input
                  type="text"
                  required
                  value={form.role}
                  onChange={(e) => set('role', e.target.value)}
                  placeholder="Type the custom role (e.g. Document Controller)"
                  className={`${inputClass} mt-2`}
                />
              )}
            </div>
            <div>
              <label htmlFor="trade" className={labelClass}>
                Trade {form.role === 'trade' && <span className="text-red-600">*</span>}
              </label>
              <select
                id="trade"
                value={
                  form.tradeMode === 'none'
                    ? '__none'
                    : form.tradeMode === 'custom'
                      ? '__custom'
                      : form.trade
                }
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === '__none') {
                    setForm((prev) => ({ ...prev, tradeMode: 'none', trade: '' }));
                  } else if (v === '__custom') {
                    setForm((prev) => ({
                      ...prev,
                      tradeMode: 'custom',
                      trade: TRADE_OPTIONS.some((t) => t.value === prev.trade) ? '' : prev.trade,
                    }));
                  } else {
                    setForm((prev) => ({ ...prev, tradeMode: 'standard', trade: v }));
                  }
                }}
                className={inputClass}
              >
                <option value="__none">— None —</option>
                {TRADE_OPTIONS.map((trade) => (
                  <option key={trade.value} value={trade.value}>
                    {trade.label}
                  </option>
                ))}
                <option value="__custom">Custom trade…</option>
              </select>
              {form.tradeMode === 'custom' && (
                <input
                  type="text"
                  value={form.trade}
                  onChange={(e) => set('trade', e.target.value)}
                  placeholder="Type the custom trade (e.g. Fire Alarm)"
                  className={`${inputClass} mt-2`}
                />
              )}
            </div>
            {editing && (
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-sm text-apple-text">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={(e) => set('is_active', e.target.checked)}
                    className="h-4 w-4 rounded border-apple-border"
                  />
                  Account active (can log in)
                </label>
              </div>
            )}
          </div>

          <div className="mt-6 rounded-md border border-apple-border bg-apple-surface/50 p-4">
            <label className="flex items-center gap-2 text-sm font-medium text-apple-text">
              <input
                type="checkbox"
                checked={form.customPerms}
                onChange={(e) => {
                  const custom = e.target.checked;
                  setForm((prev) => ({
                    ...prev,
                    customPerms: custom,
                    perms: custom
                      ? prev.perms.length > 0
                        ? prev.perms
                        : [...(ROLE_DEFAULT_PERMISSIONS[prev.role] ?? [])]
                      : prev.perms,
                  }));
                }}
                className="h-4 w-4 rounded border-apple-border"
              />
              Custom capabilities (override role defaults)
            </label>
            {!form.customPerms && (
              <p className="mt-2 text-xs text-apple-muted">
                Using role defaults:{' '}
                {(ROLE_DEFAULT_PERMISSIONS[form.role] ?? []).length > 0
                  ? (ROLE_DEFAULT_PERMISSIONS[form.role] ?? []).join(', ')
                  : 'read-only'}
              </p>
            )}
            {form.customPerms && (
              <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {PERMISSION_GROUPS.map((group) => (
                  <fieldset key={group.label}>
                    <legend className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
                      {group.label}
                    </legend>
                    <div className="mt-1 space-y-1.5">
                      {group.caps.map((cap) => (
                        <label
                          key={cap.value}
                          className="flex items-start gap-2 text-sm text-apple-text"
                        >
                          <input
                            type="checkbox"
                            checked={form.perms.includes(cap.value)}
                            onChange={() => togglePerm(cap.value)}
                            className="mt-0.5 h-4 w-4 rounded border-apple-border"
                          />
                          <span>{cap.label}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                ))}
              </div>
            )}
          </div>

          <div className="mt-6">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-apple-surface disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy ? 'Saving…' : editing ? 'Save changes' : 'Create user'}
            </button>
          </div>
        </form>

        <div className="mt-8 overflow-x-auto rounded-lg border border-apple-border bg-apple-surface shadow-sm">
          <table className="min-w-full divide-y divide-apple-border text-sm">
            <thead className="bg-apple-surface/50">
              <tr>
                {['Username', 'Full name', 'Job title', 'Role', 'Trade access', 'Capabilities', 'Active', 'Actions'].map(
                  (column) => (
                    <th
                      key={column}
                      className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-apple-muted"
                    >
                      {column}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-apple-border">
              {(users ?? []).map((u) => (
                <tr key={u.id}>
                  <td className="whitespace-nowrap px-4 py-3 font-medium text-apple-text">
                    {u.username}
                  </td>
                  <td className="px-4 py-3 text-apple-text">{u.full_name}</td>
                  <td className="px-4 py-3 text-apple-muted">{u.title || '—'}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-apple-muted">
                    {roleLabel(u.role)}
                  </td>
                  <td className="px-4 py-3 text-apple-muted">{tradeLabel(u.trade)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-apple-muted">
                    {(u.permissions ?? []).length}
                    {isCustomPerms(u) && (
                      <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">
                        custom
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {(u.is_active ?? true) ? (
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
                        Active
                      </span>
                    ) : (
                      <span className="rounded-full bg-apple-surface px-2 py-0.5 text-xs font-medium text-apple-muted">
                        Disabled
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => startEdit(u)}
                        className="text-sm font-medium text-apple-text underline"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleToggleActive(u)}
                        className="text-sm font-medium text-apple-muted underline"
                      >
                        {(u.is_active ?? true) ? 'Disable' : 'Activate'}
                      </button>
                      {u.id !== me?.id && (
                        <button
                          type="button"
                          onClick={() => void handleDelete(u)}
                          className="text-sm font-medium text-red-600 hover:text-red-800"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {users !== null && users.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-apple-muted">
                    No users yet.
                  </td>
                </tr>
              )}
              {users === null && !error && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-apple-muted">
                    Loading users…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}

