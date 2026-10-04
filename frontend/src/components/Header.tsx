'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { clearToken, getAccessNotifications } from '@/lib/api';
import { useTheme } from '@/components/ThemeProvider';
import type { User } from '@/lib/types';

/**
 * Menu-bar configuration: every dashboard in the app is reachable by
 * clicking a top-level menu and then an item in its dropdown panel.
 * Panels are grouped with small headings so the different dashboards are
 * visible at a glance (no guessing URLs).
 */
interface NavItem {
  label: string;
  href: string;
  hint?: string;
  group?: string;
}
interface NavMenu {
  label: string;
  items: NavItem[];
  wide?: boolean;
}

const PLANNER_BUCKETS = [
  'EAR', 'DESIGN', 'PROCORE', 'PTW/WICF', 'CONSTRUCTION',
  'SHUTDOWN', 'QUALITY INSPECTION', 'WCC', 'WCH',
];

const NAV_MENUS: NavMenu[] = [
  {
    label: 'Dashboards',
    wide: true,
    items: [
      { label: 'Executive Dashboard', href: '/', hint: 'KPIs: totals, disposition and lifecycle counts', group: 'Overview' },
      { label: 'To-do List (all PRs)', href: '/todo', hint: 'Next step per PR, tasks by bucket, assignee and due date', group: 'Overview' },
      { label: 'Project Divisions', href: '/dashboard', hint: 'EAR · Design · Construction · Close-up', group: 'Overview' },
      { label: 'Construction & Materials', href: '/dashboard/construction', hint: 'Execution, permits and materials', group: 'Overview' },
      { label: 'Active PRs (O&M)', href: '/dashboard/active-prs', hint: 'Classified active requests, equipment split out', group: 'Overview' },
      { label: 'EAR Board', href: '/dashboard/ear', hint: 'MOM & Summary sent/pending, whose court, follow-up', group: 'Overview' },
      { label: 'Design Board', href: '/dashboard/design', hint: 'SOW/design status, ETC, assignment, follow-up', group: 'Overview' },
      { label: 'Procore Board', href: '/dashboard/procore', hint: 'Procurement status, follow-up, communication', group: 'Overview' },
      { label: 'Consistency Check', href: '/dashboard/consistency', hint: 'Where the Planner and O&M disagree', group: 'Overview' },
      { label: 'Areas & Labs', href: '/areas', hint: 'By room or area: current and previous PIs, active and finished projects', group: 'Overview' },

      { label: 'EAR', href: '/projects?phase=EAR', hint: 'Assessment & project summary', group: 'Divisions' },
      { label: 'Design', href: '/projects?phase=Design', hint: 'Detail design, Procore & MTO', group: 'Divisions' },
      { label: 'Construction', href: '/projects?phase=Construction', hint: 'PTW/WICF, execution, shutdown & QA', group: 'Divisions' },
      { label: 'Close-up', href: '/projects?phase=Close-up', hint: 'WCC, WCH & technical library', group: 'Divisions' },

      ...PLANNER_BUCKETS.map((b) => ({
        label: b,
        href: `/dashboard/bucket/${encodeURIComponent(b)}`,
        group: 'Planner buckets',
      })),
    ],
  },
  {
    label: 'Projects',
    items: [
      { label: 'Project Register', href: '/projects', hint: 'All projects, search & filters' },
      { label: 'PI Directory', href: '/contacts', hint: 'PI / requester name and email per PR' },
      { label: 'New Project', href: '/projects/new', hint: 'Create a project manually' },
      { label: 'Tracker Upload & Sync', href: '/upload', hint: 'Publish the Planner / O&M tracker, review conflicts' },
    ],
  },
  {
    label: 'Construction',
    items: [
      { label: 'Construction Dashboard', href: '/dashboard/construction', hint: 'KPIs, teams and materials' },
      { label: 'Active Construction', href: '/projects?stage=CONSTRUCTION', hint: 'Projects in execution' },
      { label: 'Work Permits', href: '/projects?stage=WORK_PERMIT', hint: 'PTW / WICF stage' },
    ],
  },
];

const ADMIN_MENU: NavMenu = {
  label: 'Admin',
  items: [
    {
      label: 'Tracker Upload & Sync',
      href: '/upload',
      hint: 'Upload the Planner / O&M tracker — it becomes the live version',
    },
    {
      label: 'Access Requests',
      href: '/admin/access-requests',
      hint: 'Approve or reject visitors asking for an account',
    },
    { label: 'Users', href: '/admin/users', hint: 'Accounts and access' },
    { label: 'Roles', href: '/admin/roles', hint: 'Capabilities per role' },
    { label: 'User Role Assignments', href: '/admin/users-roles', hint: 'Who holds which role' },
    { label: 'System Settings', href: '/settings', hint: 'AI, paths, currency, theme' },
  ],
};

export default function Header({ user }: { user: User | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [mobileGroup, setMobileGroup] = useState<string | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const navRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const isAdmin = user?.role?.toLowerCase() === 'admin';
  const menus = isAdmin ? [...NAV_MENUS, ADMIN_MENU] : NAV_MENUS;
  const [pendingRequests, setPendingRequests] = useState(0);

  // Badge on the Admin menu: how many visitors are waiting for a decision.
  useEffect(() => {
    if (!isAdmin) return;
    let alive = true;
    const load = () => {
      getAccessNotifications()
        .then((res) => { if (alive) setPendingRequests(res.pending_access_requests); })
        .catch(() => { if (alive) setPendingRequests(0); });
    };
    load();
    const timer = window.setInterval(load, 120_000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [isAdmin]);

  // Click outside closes whichever panel is open.
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (navRef.current && !navRef.current.contains(e.target as Node)) setOpenMenu(null);
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setUserMenuOpen(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Escape closes everything.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpenMenu(null);
        setUserMenuOpen(false);
        setNavOpen(false);
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  // Navigating away closes the menus.
  useEffect(() => {
    setOpenMenu(null);
    setUserMenuOpen(false);
    setNavOpen(false);
  }, [pathname]);

  const handleSearch = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const input = event.currentTarget.querySelector('input') as HTMLInputElement | null;
      const q = input?.value.trim();
      if (q) router.push(`/projects?search=${encodeURIComponent(q)}`);
    },
    [router],
  );

  function handleLogout() {
    clearToken();
    router.replace('/login');
  }

  /** Is a top-level menu the current section? */
  function menuActive(m: NavMenu) {
    if (m.label === 'Dashboards') return pathname === '/' || pathname.startsWith('/dashboard');
    if (m.label === 'Projects') return pathname === '/projects' || pathname.startsWith('/projects/') || pathname === '/upload';
    if (m.label === 'Construction') return false;
    if (m.label === 'Admin') return pathname.startsWith('/admin') || pathname === '/settings';
    return false;
  }

  const initials = (user?.full_name ?? user?.username ?? '?')
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  /** One dropdown panel, with items grouped under small headings. */
  function renderPanel(m: NavMenu) {
    const groups: { name: string | null; items: NavItem[] }[] = [];
    m.items.forEach((it) => {
      const name = it.group ?? null;
      const last = groups[groups.length - 1];
      if (last && last.name === name) last.items.push(it);
      else groups.push({ name, items: [it] });
    });

    return (
      <div
        className={`absolute left-0 top-full z-50 mt-2 overflow-hidden rounded-xl border border-apple-border bg-white shadow-xl shadow-black/10 dark:bg-[#1c1c1e] ${
          m.wide ? 'w-[min(92vw,640px)]' : 'w-72'
        }`}
        role="menu"
      >
        <div className={m.wide ? 'grid gap-1 p-3 sm:grid-cols-2' : 'p-2'}>
          {groups.map((g, gi) => (
            <div key={`${m.label}-${g.name ?? gi}`} className={m.wide ? 'p-1' : ''}>
              {g.name && (
                <div className="px-3 pb-1 pt-2 text-[10px] font-bold uppercase tracking-wider text-apple-muted">
                  {g.name}
                </div>
              )}
              {g.items.map((it) => {
                const active = pathname === it.href.split('?')[0];
                return (
                  <Link
                    key={it.href + it.label}
                    href={it.href}
                    onClick={() => setOpenMenu(null)}
                    role="menuitem"
                    className={`block rounded-lg px-3 py-2 transition-colors ${
                      active
                        ? 'bg-primary/10 text-primary'
                        : 'text-apple-text hover:bg-black/5 dark:hover:bg-white/10'
                    }`}
                  >
                    <span className="block text-sm font-medium leading-tight">{it.label}</span>
                    {it.hint && (
                      <span className="mt-0.5 block text-[11px] leading-tight text-apple-muted">
                        {it.hint}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <header className="sticky top-0 z-40 border-b border-apple-border/60 bg-apple-surface/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-3 px-4 py-3 sm:gap-4 sm:px-6">
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-[11px] font-bold text-white shadow-sm">
              IHP
            </span>
            <span className="hidden text-lg font-semibold tracking-tight text-apple-text sm:block">
              IHP Project Delivery
            </span>
          </Link>

          {/* Menu bar: click a menu, then click an item */}
          <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary" ref={navRef}>
            {menus.map((m) => {
              const open = openMenu === m.label;
              const active = menuActive(m);
              return (
                <div key={m.label} className="relative">
                  <button
                    type="button"
                    onClick={() => setOpenMenu(open ? null : m.label)}
                    aria-haspopup="true"
                    aria-expanded={open}
                    className={`flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
                      open || active
                        ? 'bg-primary/10 text-primary'
                        : 'text-apple-muted hover:bg-black/5 hover:text-apple-text dark:hover:bg-white/10'
                    }`}
                  >
                    {m.label}
                    {m.label === 'Admin' && pendingRequests > 0 && (
                      <span className="ml-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
                        {pendingRequests}
                      </span>
                    )}
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  {open && renderPanel(m)}
                </div>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <form onSubmit={handleSearch} className="hidden md:block" role="search">
            <div className="relative">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-apple-muted"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                placeholder="Search PR, title, PI…"
                className="w-52 rounded-full border border-apple-border bg-white/50 py-1.5 pl-9 pr-3 text-sm text-apple-text placeholder:text-apple-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary dark:bg-white/10 lg:w-60"
              />
            </div>
          </form>

          <button
            type="button"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            aria-label="Toggle theme"
            className="grid h-9 w-9 place-items-center rounded-full border border-apple-border text-apple-muted transition-colors hover:text-apple-text hover:bg-black/5 dark:hover:bg-white/10"
          >
            {theme === 'dark' ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4.5 w-4.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4.5 w-4.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>

          {user && (
            <div className="relative" ref={menuRef}>
              <button
                type="button"
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                className="flex items-center gap-2.5 rounded-full border border-transparent px-1 py-1 transition-colors hover:border-apple-border hover:bg-black/5 dark:hover:bg-white/10"
                aria-haspopup="true"
                aria-expanded={userMenuOpen}
              >
                <div className="hidden text-right md:block">
                  <p className="text-sm font-medium leading-tight text-apple-text">{user.full_name}</p>
                  <p className="text-[11px] font-medium uppercase tracking-wide text-apple-muted">{user.role}</p>
                </div>
                <span className="grid h-9 w-9 place-items-center rounded-full bg-primary/15 text-xs font-bold text-primary">
                  {initials}
                </span>
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className={`hidden h-4 w-4 text-apple-muted transition-transform md:block ${userMenuOpen ? 'rotate-180' : ''}`}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {userMenuOpen && (
                <div className="absolute right-0 top-full mt-2 w-64 overflow-hidden rounded-xl border border-apple-border bg-white dark:bg-[#1c1c1e] shadow-xl shadow-black/10 dark:shadow-black/30">
                  <div className="border-b border-apple-border/60 px-4 py-3">
                    <p className="text-sm font-semibold text-apple-text">{user.full_name}</p>
                    <p className="text-xs text-apple-muted">@{user.username}</p>
                    {user.email && <p className="mt-0.5 text-xs text-apple-muted">{user.email}</p>}
                  </div>
                  <div className="py-1.5">
                    <Link href="/profile" onClick={() => setUserMenuOpen(false)}
                      className="flex items-center gap-3 px-4 py-2.5 text-sm text-apple-text transition-colors hover:bg-black/5 dark:hover:bg-white/10">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4 text-apple-muted">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </svg>
                      My Profile
                    </Link>
                    <Link href="/profile#roles" onClick={() => setUserMenuOpen(false)}
                      className="flex items-center gap-3 px-4 py-2.5 text-sm text-apple-text transition-colors hover:bg-black/5 dark:hover:bg-white/10">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4 text-apple-muted">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                      </svg>
                      My Roles &amp; Permissions
                    </Link>
                    <Link href="/profile#password" onClick={() => setUserMenuOpen(false)}
                      className="flex items-center gap-3 px-4 py-2.5 text-sm text-apple-text transition-colors hover:bg-black/5 dark:hover:bg-white/10">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4 text-apple-muted">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                      </svg>
                      Change Password
                    </Link>
                  </div>
                  <div className="border-t border-apple-border/60">
                    <button type="button" onClick={handleLogout}
                      className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-red-600 transition-colors hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                      </svg>
                      Log Out
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          <button
            type="button"
            onClick={() => setNavOpen(!navOpen)}
            aria-label="Toggle navigation"
            className="grid h-9 w-9 place-items-center rounded-full border border-apple-border text-apple-muted lg:hidden"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4.5 w-4.5">
              <path strokeLinecap="round" strokeLinejoin="round" d={navOpen ? 'M6 18L18 6M6 6l12 12' : 'M4 6h16M4 12h16M4 18h16'} />
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile: same menu tree as tap-to-expand sections */}
      {navOpen && (
        <nav className="max-h-[70vh] overflow-y-auto border-t border-apple-border/60 bg-apple-surface/95 px-6 py-3 backdrop-blur-xl lg:hidden" aria-label="Mobile">
          <div className="flex flex-col gap-1">
            {menus.map((m) => {
              const open = mobileGroup === m.label;
              const groups: { name: string | null; items: NavItem[] }[] = [];
              m.items.forEach((it) => {
                const name = it.group ?? null;
                const last = groups[groups.length - 1];
                if (last && last.name === name) last.items.push(it);
                else groups.push({ name, items: [it] });
              });
              return (
                <div key={m.label} className="rounded-lg border border-apple-border/60">
                  <button
                    type="button"
                    onClick={() => setMobileGroup(open ? null : m.label)}
                    aria-expanded={open}
                    className="flex w-full items-center justify-between px-3 py-2.5 text-sm font-semibold text-apple-text"
                  >
                    {m.label}
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                      className={`h-4 w-4 text-apple-muted transition-transform ${open ? 'rotate-180' : ''}`}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  {open && (
                    <div className="border-t border-apple-border/60 px-2 py-1.5">
                      {groups.map((g, gi) => (
                        <div key={`${m.label}-m-${g.name ?? gi}`}>
                          {g.name && (
                            <div className="px-3 pb-1 pt-2 text-[10px] font-bold uppercase tracking-wider text-apple-muted">
                              {g.name}
                            </div>
                          )}
                          {g.items.map((it) => (
                            <Link
                              key={it.href + it.label}
                              href={it.href}
                              onClick={() => setNavOpen(false)}
                              className="block rounded-lg px-3 py-2 text-sm text-apple-text hover:bg-black/5 dark:hover:bg-white/10"
                            >
                              {it.label}
                              {it.hint && (
                                <span className="mt-0.5 block text-[11px] text-apple-muted">{it.hint}</span>
                              )}
                            </Link>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            <Link href="/profile" onClick={() => setNavOpen(false)}
              className="rounded-lg px-3 py-2 text-sm font-medium text-apple-text hover:bg-black/5 dark:hover:bg-white/10">
              My Profile
            </Link>
          </div>
        </nav>
      )}
    </header>
  );
}
