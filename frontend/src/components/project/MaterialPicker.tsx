'use client';

import { useCallback, useEffect, useState } from 'react';
import { downloadPickedMto, searchPricing } from '@/lib/api';
import type { PickedMaterial, PricedMaterial } from '@/lib/api';
import { VisualCard } from '@/components/powerbi/PowerBI';

/** The trades the take-off is grouped by, in the order the team reads them. */
const TRADES: { key: string; label: string }[] = [
  { key: '', label: 'All trades' },
  { key: 'civil_arch', label: 'Civil / Architectural' },
  { key: 'electrical', label: 'Electrical' },
  { key: 'low_current', label: 'Low Current / Telecom' },
  { key: 'plumbing', label: 'Plumbing' },
  { key: 'hvac', label: 'HVAC' },
  { key: 'fire_protection', label: 'Fire Protection' },
];

/**
 * Pick the MTO from the materials price master.
 *
 * The master already holds the project cost list and the store's quotation
 * list (2 200+ rows). Type a few words, pick the real row, set the quantity -
 * the take-off is written into the team's own MTO grid with the master rate on
 * every line. Nothing is typed twice and nothing is invented.
 */
export default function MaterialPicker({ projectId }: { projectId: number }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PricedMaterial[]>([]);
  const [picked, setPicked] = useState<PickedMaterial[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [masterSize, setMasterSize] = useState<number | null>(null);
  const [trade, setTrade] = useState('');
  const [manual, setManual] = useState({
    description: '',
    unit: 'EA',
    qty: '1',
    trade: 'plumbing',
  });

  const search = useCallback(async (text: string, tradeKey: string) => {
    try {
      const rows = await searchPricing(text, 40, tradeKey);
      setResults(rows);
      setMasterSize((size) => (size === null && !text && !tradeKey ? rows.length : size));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not search the price master');
    }
  }, []);

  useEffect(() => {
    void search('', trade);
  }, [search, trade]);

  function add(material: PricedMaterial) {
    setPicked((rows) => [
      ...rows,
      {
        description: material.description,
        unit: material.unit,
        qty: '1',
        trade: material.trade || trade || 'plumbing',
        item_code: material.item_code,
      },
    ]);
    setNotice('Added: ' + material.description.slice(0, 60));
  }

  function setQty(index: number, qty: string) {
    setPicked((rows) => rows.map((row, i) => (i === index ? { ...row, qty } : row)));
  }

  function remove(index: number) {
    setPicked((rows) => rows.filter((_, i) => i !== index));
  }

  async function build() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await downloadPickedMto(projectId, picked);
      setNotice('MTO built with ' + picked.length + ' line(s).');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not build the MTO');
    } finally {
      setBusy(false);
    }
  }

  return (
    <VisualCard
      title="Materials list - pick the MTO"
      subtitle="search the price master, pick the rows, set the quantities"
      actions={
        <button
          type="button"
          onClick={() => void build()}
          disabled={busy || picked.length === 0}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {busy ? 'Building…' : 'Generate MTO (' + picked.length + ')'}
        </button>
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={trade}
          onChange={(e) => setTrade(e.target.value)}
          className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-apple-text dark:border-white/10 dark:bg-white/5"
        >
          {TRADES.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            void search(e.target.value, trade);
          }}
          placeholder="Search the materials list - e.g. ball valve 1/2, EMT conduit, socket…"
          className="w-full max-w-md rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-apple-text outline-none focus:border-primary dark:border-white/10 dark:bg-white/5"
        />
        <span className="text-[11px] text-slate-500">
          {results.length} shown{masterSize !== null ? ' of the master' : ''}
        </span>
      </div>

      <div className="mt-2 grid max-h-64 gap-1 overflow-auto lg:grid-cols-2">
        {results.map((material) => (
          <button
            key={material.id}
            type="button"
            onClick={() => add(material)}
            className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-left text-[11px] hover:border-primary dark:border-white/10 dark:bg-white/[0.03]"
          >
            <span className="min-w-0 flex-1 truncate text-apple-text">{material.description}</span>
            <span className="shrink-0 text-slate-500">{material.unit}</span>
            <span className="shrink-0 font-semibold tabular-nums text-apple-text">
              {material.base_unit_rate}
            </span>
            <span className="shrink-0 rounded bg-slate-100 px-1.5 text-[10px] text-slate-500">
              {material.item_code}
            </span>
          </button>
        ))}
        {results.length === 0 && (
          <p className="py-4 text-center text-xs italic text-slate-400 lg:col-span-2">
            Nothing matched that search.
          </p>
        )}
      </div>

      {/* Anything the master does not carry is typed in here: the MTO is a
          project document, not a price-list export. */}
      <div className="mt-3 grid gap-2 rounded-lg border border-dashed border-slate-300 p-2 lg:grid-cols-[1fr_110px_80px_170px_auto] dark:border-white/10">
        <input
          value={manual.description}
          onChange={(event) => setManual({ ...manual, description: event.target.value })}
          placeholder="Add a material manually - description"
          className="rounded border border-slate-200 px-2 py-1 text-xs dark:border-white/10 dark:bg-white/5"
        />
        <input
          value={manual.unit}
          onChange={(event) => setManual({ ...manual, unit: event.target.value })}
          placeholder="Unit"
          className="rounded border border-slate-200 px-2 py-1 text-xs dark:border-white/10 dark:bg-white/5"
        />
        <input
          value={manual.qty}
          onChange={(event) => setManual({ ...manual, qty: event.target.value })}
          placeholder="Qty"
          className="rounded border border-slate-200 px-2 py-1 text-right text-xs tabular-nums dark:border-white/10 dark:bg-white/5"
        />
        <select
          value={manual.trade}
          onChange={(event) => setManual({ ...manual, trade: event.target.value })}
          className="rounded border border-slate-200 px-2 py-1 text-xs dark:border-white/10 dark:bg-white/5"
        >
          {TRADES.filter((option) => option.key).map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => {
            if (!manual.description.trim()) return;
            setPicked((rows) => [
              ...rows,
              {
                description: manual.description.trim(),
                unit: manual.unit.trim() || 'EA',
                qty: manual.qty.trim() || '1',
                trade: manual.trade,
                item_code: null,
              },
            ]);
            setManual({ ...manual, description: '', qty: '1' });
          }}
          disabled={!manual.description.trim()}
          className="rounded-md border border-primary px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/10 disabled:opacity-50"
        >
          + Add manually
        </button>
      </div>

      {picked.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-slate-200 pt-2 dark:border-white/10">
          {picked.map((row, index) => (
            <li
              key={row.description + index}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-1.5 text-[11px] dark:border-white/10"
            >
              <span className="min-w-0 flex-1 truncate text-apple-text">{row.description}</span>
              <span className="shrink-0 rounded bg-slate-100 px-1.5 text-[10px] uppercase text-slate-500">
                {(TRADES.find((option) => option.key === row.trade)?.label ?? row.trade ?? '')
                  .replace(' / Architectural', '')}
              </span>
              <span className="text-slate-500">{row.unit}</span>
              <input
                value={row.qty}
                onChange={(event) => setQty(index, event.target.value)}
                className="w-16 rounded border border-slate-200 px-1.5 py-0.5 text-right tabular-nums dark:border-white/10 dark:bg-white/5"
              />
              <button
                type="button"
                onClick={() => remove(index)}
                className="text-[10px] font-semibold text-red-600 hover:underline"
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}
      {notice && !error && (
        <p className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          {notice}
        </p>
      )}
    </VisualCard>
  );
}
