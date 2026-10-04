'use client';

/**
 * A small Power BI-style visual kit.
 *
 * Everything here is deliberately dependency-free (no chart library): the
 * visuals are CSS + inline SVG so they stay crisp, print well and never
 * bloat the bundle. The interaction model mirrors Power BI: every visual is
 * cross-filtering - clicking a bar, slice, chip or KPI narrows the page
 * around that selection, and clicking it again clears it.
 */

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';

/** The Power BI default palette. */
export const PBI_COLORS = [
  '#118DFF',
  '#12239E',
  '#E66C37',
  '#6B007B',
  '#E044A7',
  '#744EC2',
  '#D9B300',
  '#D64550',
  '#197278',
  '#1AAB40',
];

export function colorAt(i: number): string {
  return PBI_COLORS[i % PBI_COLORS.length];
}

/** The page canvas: a light grey board the visuals sit on. */
export function PbiCanvas({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[60vh] rounded-2xl bg-[#f3f5f8] p-3 dark:bg-black/20 sm:p-4">
      {children}
    </div>
  );
}

/** The title band above the canvas. */
export function PbiHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-apple-text">{title}</h1>
        {subtitle ? <div className="mt-1 text-sm text-apple-muted">{subtitle}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/** A titled visual container, with room for a header action or menu. */
export function VisualCard({
  title,
  subtitle,
  actions,
  children,
  className = '',
  onClick,
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <section
      onClick={onClick}
      className={
        'flex flex-col rounded-xl border border-slate-200/80 bg-white p-3 shadow-sm dark:border-white/10 dark:bg-white/[0.04] ' +
        className
      }
    >
      {(title || actions) && (
        <header className="mb-2 flex items-start justify-between gap-2">
          <div className="min-w-0">
            {title && (
              <h2 className="truncate text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 truncate text-[11px] text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
        </header>
      )}
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}

const ACCENTS: Record<string, string> = {
  blue: '#118DFF',
  navy: '#12239E',
  orange: '#E66C37',
  purple: '#6B007B',
  pink: '#E044A7',
  violet: '#744EC2',
  gold: '#D9B300',
  red: '#D64550',
  teal: '#197278',
  green: '#1AAB40',
  slate: '#64748B',
};

/**
 * A KPI card. It is clickable: `href` drills through to another page, while
 * `onClick` cross-filters the current page. `active` draws the selection.
 */
export function KpiCard({
  label,
  value,
  hint,
  accent = 'blue',
  href,
  onClick,
  active = false,
  icon,
}: {
  label: string;
  value: number | string;
  hint?: string;
  accent?: keyof typeof ACCENTS | string;
  href?: string;
  onClick?: () => void;
  active?: boolean;
  icon?: string;
}) {
  const color = ACCENTS[accent] ?? accent;
  const body = (
    <div
      className={
        'relative h-full overflow-hidden rounded-xl border border-slate-200/80 bg-white p-3 pl-4 text-left shadow-sm transition hover:shadow-md dark:border-white/10 dark:bg-white/[0.04]'
      }
      style={active ? { boxShadow: '0 0 0 2px ' + color } : undefined}
    >
      <span className="absolute inset-y-0 left-0 w-1.5" style={{ backgroundColor: color }} />
      <div className="flex items-start justify-between gap-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          {label}
        </div>
        {icon ? <span className="text-sm leading-none">{icon}</span> : null}
      </div>
      <div className="mt-1 text-3xl font-bold leading-none tabular-nums text-apple-text">{value}</div>
      {hint ? <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{hint}</div> : null}
    </div>
  );

  if (href) {
    return (
      <Link href={href} className="block h-full">
        {body}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className="block h-full w-full">
        {body}
      </button>
    );
  }
  return body;
}

export interface BarItem {
  key: string;
  label: string;
  value: number;
  color?: string;
  href?: string;
}

/** A horizontal bar list - click a bar to filter, click again to clear. */
export function BarList({
  items,
  onSelect,
  selected = [],
  max,
  total,
}: {
  items: BarItem[];
  onSelect?: (key: string) => void;
  selected?: string[];
  max?: number;
  total?: number;
}) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value));
  const sum = total ?? items.reduce((a, i) => a + i.value, 0);
  if (items.length === 0) {
    return <p className="py-6 text-center text-xs italic text-slate-400">No data</p>;
  }
  return (
    <ul className="space-y-1.5">
      {items.map((it, i) => {
        const pct = top > 0 ? Math.round((it.value / top) * 100) : 0;
        const share = sum > 0 ? Math.round((it.value / sum) * 100) : 0;
        const isSel = selected.includes(it.key);
        const inner = (
          <>
            <span className="flex items-baseline justify-between gap-2 text-[11px]">
              <span className="truncate font-medium text-apple-text">{it.label}</span>
              <span className="shrink-0 tabular-nums text-slate-500">
                {it.value}
                {sum > 0 ? <span className="ml-1 text-slate-400">({share}%)</span> : null}
              </span>
            </span>
            <span className="mt-1 block h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
              <span
                className="block h-full rounded-full transition-all"
                style={{ width: Math.max(pct, 2) + '%', backgroundColor: it.color ?? colorAt(i) }}
              />
            </span>
          </>
        );
        const cls =
          'block w-full rounded-md px-1.5 py-1 text-left transition ' +
          (isSel
            ? 'bg-slate-100 ring-1 ring-inset ring-slate-300 dark:bg-white/10'
            : 'hover:bg-slate-50 dark:hover:bg-white/5');
        return (
          <li key={it.key}>
            {it.href ? (
              <Link href={it.href} className={cls}>
                {inner}
              </Link>
            ) : onSelect ? (
              <button type="button" onClick={() => onSelect(it.key)} className={cls}>
                {inner}
              </button>
            ) : (
              <div className={cls}>{inner}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export interface Slice {
  key: string;
  label: string;
  value: number;
  color?: string;
}

/** A donut with a centre total. Slices are clickable. */
export function Donut({
  items,
  onSelect,
  selected = [],
  size = 148,
  centerLabel = 'Total',
}: {
  items: Slice[];
  onSelect?: (key: string) => void;
  selected?: string[];
  size?: number;
  centerLabel?: string;
}) {
  const total = items.reduce((a, i) => a + i.value, 0);
  const stroke = size / 6;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="flex flex-wrap items-center justify-center gap-4">
      <svg width={size} height={size} viewBox={'0 0 ' + size + ' ' + size} className="shrink-0">
        <g transform={'rotate(-90 ' + size / 2 + ' ' + size / 2 + ')'}>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="#e2e8f0"
            strokeWidth={stroke}
          />
          {total > 0 &&
            items.map((it, i) => {
              const frac = it.value / total;
              const len = frac * circumference;
              const dash = len + ' ' + Math.max(circumference - len, 0.001);
              const isSel = selected.length === 0 || selected.includes(it.key);
              const el = (
                <circle
                  key={it.key}
                  cx={size / 2}
                  cy={size / 2}
                  r={radius}
                  fill="none"
                  stroke={it.color ?? colorAt(i)}
                  strokeWidth={isSel ? stroke : stroke * 0.7}
                  strokeDasharray={dash}
                  strokeDashoffset={-offset}
                  opacity={isSel ? 1 : 0.25}
                  style={{ cursor: onSelect ? 'pointer' : 'default', transition: 'opacity .15s' }}
                  onClick={onSelect ? () => onSelect(it.key) : undefined}
                >
                  <title>{it.label + ': ' + it.value}</title>
                </circle>
              );
              offset += len;
              return el;
            })}
        </g>
        <text
          x="50%"
          y="47%"
          textAnchor="middle"
          className="fill-slate-900 text-2xl font-bold dark:fill-slate-100"
          style={{ fontSize: size / 5 }}
        >
          {total}
        </text>
        <text
          x="50%"
          y="64%"
          textAnchor="middle"
          className="fill-slate-400"
          style={{ fontSize: size / 14 }}
        >
          {centerLabel}
        </text>
      </svg>
      <ul className="min-w-[140px] space-y-1">
        {items.map((it, i) => {
          const isSel = selected.includes(it.key);
          return (
            <li key={it.key}>
              <button
                type="button"
                onClick={onSelect ? () => onSelect(it.key) : undefined}
                className={
                  'flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-left text-[11px] transition ' +
                  (onSelect ? 'hover:bg-slate-50 dark:hover:bg-white/5' : '') +
                  (isSel ? ' font-semibold text-apple-text' : ' text-slate-500')
                }
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: it.color ?? colorAt(i) }}
                />
                <span className="min-w-0 flex-1 truncate">{it.label}</span>
                <span className="tabular-nums">{it.value}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** A Power BI slicer: the chips that drive the whole page. */
export function SlicerBar({
  label = 'Filter',
  items,
  selected,
  onToggle,
  onClear,
}: {
  label?: string;
  items: { key: string; label: string; value?: number; color?: string }[];
  selected: string[];
  onToggle: (key: string) => void;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </span>
      <button
        type="button"
        onClick={onClear}
        className={
          'rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset transition ' +
          (selected.length === 0
            ? 'bg-primary text-white ring-primary'
            : 'bg-white text-slate-500 ring-slate-200 hover:bg-slate-50 dark:bg-white/5 dark:ring-white/10')
        }
      >
        All
      </button>
      {items.map((it) => {
        const on = selected.includes(it.key);
        return (
          <button
            key={it.key}
            type="button"
            onClick={() => onToggle(it.key)}
            className={
              'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset transition ' +
              (on
                ? 'bg-slate-900 text-white ring-slate-900 dark:bg-white dark:text-slate-900'
                : 'bg-white text-slate-600 ring-slate-200 hover:bg-slate-50 dark:bg-white/5 dark:text-slate-300 dark:ring-white/10')
            }
          >
            {it.color ? (
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: it.color }} />
            ) : null}
            {it.label}
            {typeof it.value === 'number' ? (
              <span className="tabular-nums opacity-70">{it.value}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/** A compact, striped table whose rows drill through. */
export function DataTable<T extends { id: number | string }>({
  columns,
  rows,
  hrefFor,
  empty = 'Nothing to show',
}: {
  columns: { key: string; label: string; align?: 'left' | 'right'; render: (row: T) => ReactNode }[];
  rows: T[];
  hrefFor?: (row: T) => string;
  empty?: string;
}) {
  const router = useRouter();
  if (rows.length === 0) {
    return <p className="py-8 text-center text-xs italic text-slate-400">{empty}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="border-b border-slate-200 text-[10px] uppercase tracking-wider text-slate-400 dark:border-white/10">
            {columns.map((c) => (
              <th
                key={c.key}
                className={'px-2 py-1.5 font-semibold ' + (c.align === 'right' ? 'text-right' : '')}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const href = hrefFor ? hrefFor(row) : undefined;
            return (
              <tr
                key={row.id}
                onClick={href ? () => router.push(href) : undefined}
                className={
                  'border-b border-slate-100 transition last:border-0 hover:bg-slate-50 dark:border-white/5 dark:hover:bg-white/5 ' +
                  (href ? 'cursor-pointer' : '')
                }
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={
                      'px-2 py-1.5 align-top text-apple-text ' +
                      (c.align === 'right' ? 'text-right tabular-nums' : '')
                    }
                  >
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
