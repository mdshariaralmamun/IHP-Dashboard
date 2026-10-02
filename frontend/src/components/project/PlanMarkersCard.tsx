'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiError,
  createPlanMarker,
  deletePlanMarker,
  listPlanMarkers,
  planImageUrl,
  updatePlanMarker,
} from '@/lib/api';
import type { PlanMarker } from '@/lib/api';
import type { Attachment } from '@/lib/types';

type Mode = { kind: 'idle' } | { kind: 'add' } | { kind: 'move'; id: number } ;

/**
 * Labelled pins on a floor plan.
 *
 * The plan is an ordinary PDF attachment (an AutoCAD export). Click the plan
 * to place a pin; each pin carries a label, the PI and a PR reference. Pins
 * are EDITED, not silently replaced - a PI whose name changes is a label edit,
 * and a location divided between two PIs becomes two pins, so who held what
 * stays visible in the trail.
 */
export default function PlanMarkersCard({
  projectId,
  attachments,
  canEdit,
}: {
  projectId: number;
  attachments: Attachment[];
  canEdit: boolean;
}) {
  const plans = attachments.filter((a) =>
    (a.filename ?? '').toLowerCase().endsWith('.pdf'),
  );
  const [attachmentId, setAttachmentId] = useState<number | null>(
    plans[0]?.id ?? null,
  );
  const [page, setPage] = useState(1);
  const [markers, setMarkers] = useState<PlanMarker[]>([]);
  const [mode, setMode] = useState<Mode>({ kind: 'idle' });
  const [draft, setDraft] = useState<PlanMarker | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(() => {
    listPlanMarkers(projectId)
      .then(setMarkers)
      .catch(() => undefined);
  }, [projectId]);

  useEffect(load, [load]);
  useEffect(() => {
    if (plans.length && attachmentId === null) setAttachmentId(plans[0].id);
  }, [plans, attachmentId]);

  const visible = markers.filter((m) => m.attachment_id === attachmentId);

  async function place(event: React.MouseEvent<HTMLDivElement>) {
    if (!canEdit || !attachmentId) return;
    const box = wrapRef.current?.getBoundingClientRect();
    if (!box) return;
    const x = ((event.clientX - box.left) / box.width) * 100;
    const y = ((event.clientY - box.top) / box.height) * 100;
    if (mode.kind === 'move') {
      setBusy(true);
      try {
        await updatePlanMarker(projectId, mode.id, { x, y });
        setMode({ kind: 'idle' });
        load();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not move the pin.');
      } finally {
        setBusy(false);
      }
      return;
    }
    if (mode.kind !== 'add') return;
    setBusy(true);
    setError(null);
    try {
      const created = await createPlanMarker(projectId, {
        label: 'New area',
        x,
        y,
        attachment_id: attachmentId,
        page,
      });
      setDraft(created);
      setMode({ kind: 'idle' });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not place the pin.');
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    if (!draft) return;
    setBusy(true);
    try {
      await updatePlanMarker(projectId, draft.id, {
        label: draft.label,
        pi_name: draft.pi_name,
        pr_ref: draft.pr_ref,
        notes: draft.notes,
      });
      setDraft(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the pin.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-apple-border bg-apple-surface p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-apple-text">Plan markers</h3>
          <p className="mt-1 text-xs text-apple-muted">
            Pins on the floor plan, labelled with the PI and PR. Edit a pin when the PI
            changes; place a second one when a location is divided.
          </p>
        </div>
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={attachmentId ?? ''}
              onChange={(e) => setAttachmentId(Number(e.target.value))}
              className="rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
            >
              {plans.length === 0 && <option value="">No PDF plan attached</option>}
              {plans.map((p) => (
                <option key={p.id} value={p.id}>{p.filename}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() =>
                setMode((m) => (m.kind === 'add' ? { kind: 'idle' } : { kind: 'add' }))
              }
              disabled={!attachmentId || busy}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                mode.kind === 'add'
                  ? 'bg-primary text-white'
                  : 'border border-apple-border text-apple-text hover:bg-apple-surface/70'
              } disabled:opacity-50`}
            >
              {mode.kind === 'add' ? 'Click the plan…' : 'Place a pin'}
            </button>
          </div>
        )}
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {attachmentId ? (
        <div
          ref={wrapRef}
          onClick={place}
          className={`relative mt-4 max-h-[70vh] overflow-auto rounded-md border border-apple-border bg-white ${
            mode.kind === 'add' || mode.kind === 'move' ? 'cursor-crosshair' : ''
          }`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={planImageUrl(projectId, attachmentId, page)}
            alt="Floor plan"
            className="block w-full select-none"
            draggable={false}
          />
          {visible.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                if (canEdit) setDraft(m);
              }}
              style={{ left: `${m.x}%`, top: `${m.y}%` }}
              className="absolute -translate-x-1/2 -translate-y-full"
              title={`${m.label}${m.pi_name ? ' — ' + m.pi_name : ''}`}
            >
              <span className="block rounded-full bg-primary px-2 py-0.5 text-[10px] font-bold text-white shadow ring-2 ring-white">
                {m.label}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-xs text-apple-muted">
          Attach the floor plan as a PDF (export it from AutoCAD) and it appears here.
        </p>
      )}

      {visible.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-apple-text">
          {visible.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{m.label}</span>
              {m.pi_name && <span>· PI: {m.pi_name}</span>}
              {m.pr_ref && <span>· {m.pr_ref}</span>}
              {canEdit && (
                <>
                  <button
                    type="button"
                    onClick={() => setMode({ kind: 'move', id: m.id })}
                    className="underline hover:text-apple-text"
                  >
                    move
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void deletePlanMarker(projectId, m.id).then(load);
                    }}
                    className="text-red-600 underline hover:text-red-800"
                  >
                    delete
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {draft && (
        <div className="mt-4 rounded-md border border-apple-border bg-apple-surface/70 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-apple-muted">
            Edit pin
          </h4>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <input
              value={draft.label}
              onChange={(e) => setDraft({ ...draft, label: e.target.value })}
              placeholder="Label (e.g. 5-3610 / LFO 12)"
              className="rounded border border-apple-border bg-apple-surface px-2 py-1.5 text-xs"
            />
            <input
              value={draft.pi_name ?? ''}
              onChange={(e) => setDraft({ ...draft, pi_name: e.target.value })}
              placeholder="PI name"
              className="rounded border border-apple-border bg-apple-surface px-2 py-1.5 text-xs"
            />
            <input
              value={draft.pr_ref ?? ''}
              onChange={(e) => setDraft({ ...draft, pr_ref: e.target.value })}
              placeholder="PR reference"
              className="rounded border border-apple-border bg-apple-surface px-2 py-1.5 text-xs"
            />
            <input
              value={draft.notes ?? ''}
              onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
              placeholder="Note (e.g. divided from LFO 3 in Oct 2026)"
              className="rounded border border-apple-border bg-apple-surface px-2 py-1.5 text-xs"
            />
          </div>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => void saveDraft()}
              disabled={busy || !draft.label.trim()}
              className="rounded bg-primary px-3 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="rounded border border-apple-border px-3 py-1 text-xs text-apple-text"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
