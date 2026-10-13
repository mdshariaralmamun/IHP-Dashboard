'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getAssistantState,
  proposeAssistant,
  resetAssistant,
  runAssistantAction,
} from '@/lib/api';
import type { AssistantActionInfo, AssistantState, AssistantTurn } from '@/lib/api';
import { VisualCard } from '@/components/powerbi/PowerBI';
import { canDo, useUser } from '@/lib/useUser';

const STATUS_STYLE: Record<string, string> = {
  not_started: 'bg-slate-100 text-slate-600',
  in_progress: 'bg-blue-100 text-blue-800',
  awaiting_feedback: 'bg-amber-100 text-amber-800',
  pending_approval: 'bg-amber-100 text-amber-800',
  under_review: 'bg-blue-100 text-blue-800',
  revise_and_resubmit: 'bg-red-100 text-red-800',
  approved_as_noted: 'bg-emerald-100 text-emerald-800',
  approved: 'bg-emerald-100 text-emerald-800',
  confirmed: 'bg-emerald-100 text-emerald-800',
  done: 'bg-emerald-100 text-emerald-800',
};

const CAP_LABEL: Record<string, string> = {
  'mom.manage': 'MOM',
  'projects.edit': 'project editing',
  'ear.manage': 'EAR',
  'sow.manage': 'SOW',
  'boq.manage': 'BOQ / MTO',
};

/** The delivery order, so the panel lists the actions the way the work happens. */
const ORDER = [
  'mom.draft',
  'mom.confirm',
  'summary.draft',
  'summary.approve',
  'ear.draft',
  'ear.pi_signature',
  'ear.asepc',
  'sow.draft',
  'boq.draft',
  'drawings.list',
  'sow.approve',
  'package.binder',
  'mto.draft',
];

function rank(id: string): number {
  const index = ORDER.indexOf(id);
  return index < 0 ? ORDER.length : index;
}

/**
 * The project delivery assistant.
 *
 * Paste the meeting notes, the instructions or the scope inputs; the assistant
 * says which step comes next, and every step it runs writes the real document
 * through the app's own generators. It cannot skip a gate: a step that is not
 * allowed yet is shown greyed out with the pipeline's own sentence, and the API
 * refuses it with a 409 even if the button were clicked. The EAR funnel is shown
 * beside the five-stage spine because the two run in parallel.
 */
export default function AssistantChat({
  projectId,
  prNumber,
  onChanged,
}: {
  projectId: number;
  prNumber: string;
  onChanged?: () => void;
}) {
  const { user } = useUser();
  const [state, setState] = useState<AssistantState | null>(null);
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [input, setInput] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<AssistantTurn | null>(null);
  const [showAll, setShowAll] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(() => {
    getAssistantState(projectId)
      .then((next) => {
        setState(next);
        setTurns(next.transcript ?? []);
        setError(null);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Could not load the assistant'),
      );
  }, [projectId]);

  useEffect(load, [load]);

  function scrollDown() {
    setTimeout(() => boxRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 60);
  }

  const suggested = useMemo(() => {
    const withSuggestion = [...turns].reverse().find((t) => t.suggested_action);
    return withSuggestion?.suggested_action ?? null;
  }, [turns]);

  const gate = state?.gate;
  const actions = state?.actions ?? [];

  /** Allowed and permitted first (in delivery order), then blocked, then locked. */
  const ordered = useMemo(() => {
    const allowed = new Set(gate?.allowed ?? []);
    const score = (action: AssistantActionInfo): number => {
      if (action.id === suggested) return 0;
      if (allowed.has(action.id) && canDo(user, action.capability)) return 1;
      if (allowed.has(action.id)) return 3;
      return 2;
    };
    return [...actions].sort(
      (a, b) => score(a) - score(b) || rank(a.id) - rank(b.id),
    );
  }, [actions, gate, suggested, user]);

  async function propose() {
    const message = input.trim();
    if (!message || busy) return;
    setBusy('propose');
    setError(null);
    setNotice(null);
    try {
      const turn = await proposeAssistant(projectId, message);
      setInput('');
      setNotice(
        'Next step: ' +
          (actions.find((a) => a.id === turn.suggested_action)?.label ??
            turn.suggested_action ??
            'see below'),
      );
      load();
      scrollDown();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The assistant could not answer');
    } finally {
      setBusy(null);
    }
  }

  async function run(actionId: string) {
    if (busy) return;
    setBusy(actionId);
    setError(null);
    setNotice(null);
    try {
      const turn = await runAssistantAction(projectId, actionId, note.trim() || undefined);
      setLastResult(turn);
      setNote('');
      load();
      onChanged?.();
      scrollDown();
    } catch (e) {
      // A 409 arrives as ApiError with the pipeline's own sentence.
      setError(e instanceof Error ? e.message : 'That step was refused');
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    if (busy) return;
    setBusy('reset');
    setError(null);
    try {
      await resetAssistant(projectId);
      setLastResult(null);
      setNotice('Transcript cleared (the documents stay).');
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not clear the transcript');
    } finally {
      setBusy(null);
    }
  }

  const visible = showAll ? ordered : ordered.filter((a) => a.id === suggested || (gate?.allowed ?? []).includes(a.id));

  return (
    <VisualCard
      title={'Delivery assistant — ' + prNumber}
      subtitle={
        gate
          ? 'Stage ' + gate.stage + ' · ' + gate.label + ' · ' + gate.status
          : 'paste the notes; the documents come out in gate order'
      }
      actions={
        <div className="flex items-center gap-2">
          <span
            className={
              'rounded-full px-2 py-1 text-[11px] font-medium ' +
              (state?.ai.available ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800')
            }
            title={state?.ai.reason ?? ''}
          >
            {state ? state.ai.provider + ' · ' + state.ai.model : 'AI…'}
            {state && !state.ai.available ? ' · offline' : ''}
          </span>
          <button
            type="button"
            className="rounded-md border border-apple-border px-2 py-1 text-[11px] text-apple-muted hover:bg-apple-hover"
            disabled={busy === 'reset'}
            onClick={reset}
          >
            Clear chat
          </button>
        </div>
      }
    >
      {error && (
        <p className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}
      {notice && !error && (
        <p className="mb-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
          {notice}
        </p>
      )}

      {/* the gate: the five stages, then the EAR funnel beside them */}
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {(
          (state?.pipeline as { stages?: Array<{ stage: number; label: string; status: string }> })
            ?.stages ?? []
        ).map((stage) => (
          <span
            key={stage.stage}
            title={stage.label}
            className={
              'rounded-full px-2 py-1 text-[11px] font-medium ' +
              (STATUS_STYLE[stage.status] ?? 'bg-slate-100 text-slate-600')
            }
          >
            {stage.stage}. {stage.label.split('(')[0].trim()}
          </span>
        ))}
        {state?.ear && (
          <span
            className="rounded-full border border-apple-border px-2 py-1 text-[11px] text-apple-muted"
            title="The EAR funnel runs in parallel to the five stages"
          >
            EAR · {state.ear.status.replace(/_/g, ' ')} · beside the spine
          </span>
        )}
      </div>

      {/* the chat */}
      <div
        ref={boxRef}
        className="mb-3 max-h-80 overflow-y-auto rounded-lg border border-apple-border p-3"
      >
        {turns.length === 0 && (
          <p className="text-xs text-apple-muted">
            Paste the meeting notes, the instructions or the scope inputs below. The
            assistant reads the project, says which step comes next and writes the
            document when you run it.
          </p>
        )}
        <div className="flex flex-col gap-2">
          {turns.map((turn) => (
            <div
              key={turn.id}
              className={
                'rounded-md px-3 py-2 text-xs leading-relaxed ' +
                (turn.role === 'user'
                  ? 'self-end bg-apple-hover text-apple-text'
                  : turn.role === 'tool'
                    ? 'border-l-2 border-emerald-400 bg-apple-hover/40 text-apple-text'
                    : 'text-apple-text')
              }
            >
              <div className="mb-1 text-[10px] uppercase tracking-wide text-apple-muted">
                {turn.role === 'user' ? 'you' : turn.role === 'tool' ? 'done' : 'assistant'}
                {turn.action ? ' · ' + turn.action : ''}
                {typeof turn.elapsed_ms === 'number' ? ' · ' + (turn.elapsed_ms / 1000).toFixed(1) + 's' : ''}
              </div>
              <div className="whitespace-pre-wrap">{turn.content}</div>
              {(turn.artifacts ?? []).length > 0 && (
                <ul className="mt-2 flex flex-col gap-1">
                  {(turn.artifacts ?? []).map((artifact, index) => (
                    <li key={index} className="text-[11px] text-apple-muted">
                      <span className="font-medium text-apple-text">{artifact.label}</span>
                      {artifact.filename ? ' — ' + artifact.filename : ''}
                      {artifact.panel ? ' · ' + artifact.panel : ''}
                      {artifact.url ? (
                        <>
                          {' · '}
                          <a className="underline" href={artifact.url} target="_blank" rel="noreferrer">
                            download
                          </a>
                        </>
                      ) : null}
                      {artifact.meta && Object.keys(artifact.meta).length > 0
                        ? ' · ' + JSON.stringify(artifact.meta).slice(0, 180)
                        : ''}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* the composer */}
      <textarea
        className="w-full rounded-md border border-apple-border bg-transparent px-3 py-2 text-xs text-apple-text outline-none focus:border-blue-400"
        rows={5}
        placeholder="Paste the meeting notes, the instructions or the scope inputs…"
        value={input}
        onChange={(e) => setInput(e.target.value)}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          disabled={!input.trim() || busy !== null}
          onClick={propose}
        >
          {busy === 'propose' ? 'Thinking…' : 'Propose the next step'}
        </button>
        <input
          className="min-w-[220px] flex-1 rounded-md border border-apple-border bg-transparent px-3 py-1.5 text-xs text-apple-text outline-none focus:border-blue-400"
          placeholder="Note for the next run (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button
          type="button"
          className="rounded-md border border-apple-border px-3 py-1.5 text-xs text-apple-muted hover:bg-apple-hover"
          onClick={() => setShowAll((value) => !value)}
        >
          {showAll ? 'Show only what can run' : 'Show all 13 steps'}
        </button>
      </div>

      {/* the actions */}
      <div className="mt-4 flex flex-col gap-2">
        {visible.map((action) => {
          const blockedReason = gate?.blocked[action.id];
          const permitted = canDo(user, action.capability);
          const enabled = !blockedReason && permitted && busy === null;
          return (
            <div
              key={action.id}
              className={
                'flex flex-wrap items-start justify-between gap-2 rounded-md border border-apple-border px-3 py-2 ' +
                (action.id === suggested ? 'bg-blue-50/40' : '')
              }
            >
              <div className="min-w-[240px] flex-1">
                <p className="text-xs font-medium text-apple-text">
                  {action.id === suggested ? 'Next step · ' : ''}
                  {action.label}
                </p>
                <p className="text-[11px] text-apple-muted">
                  stage {action.stage} · {action.track === 'ear' ? 'EAR funnel' : 'five-stage spine'} ·
                  updates {action.panel}
                  {!permitted ? ' · needs ' + (CAP_LABEL[action.capability] ?? action.capability) : ''}
                </p>
                {blockedReason && (
                  <p className="mt-1 text-[11px] text-apple-muted">{blockedReason}</p>
                )}
              </div>
              <button
                type="button"
                className="rounded-md border border-apple-border px-3 py-1.5 text-xs font-medium text-apple-text hover:bg-apple-hover disabled:opacity-40"
                disabled={!enabled}
                title={blockedReason ?? (permitted ? '' : 'You do not have the permission for this step')}
                onClick={() => run(action.id)}
              >
                {busy === action.id ? 'Running…' : 'Run'}
              </button>
            </div>
          );
        })}
        {state === null && <p className="text-xs text-apple-muted">Loading the assistant…</p>}
      </div>

      {/* the last result, inline */}
      {lastResult && (
        <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2">
          <p className="text-xs font-medium text-emerald-900">
            {lastResult.action} done
            {typeof lastResult.elapsed_ms === 'number'
              ? ' in ' + (lastResult.elapsed_ms / 1000).toFixed(1) + 's'
              : ''}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-xs text-emerald-900">{lastResult.content}</p>
          {(lastResult.artifacts ?? []).length > 0 && (
            <ul className="mt-1 text-[11px] text-emerald-800">
              {(lastResult.artifacts ?? []).map((artifact, index) => (
                <li key={index}>
                  {artifact.label}
                  {artifact.filename ? ' · ' + artifact.filename : ''}
                  {artifact.panel ? ' · ' + artifact.panel : ''}
                  {artifact.meta && Object.keys(artifact.meta).length > 0
                    ? ' · ' + JSON.stringify(artifact.meta).slice(0, 160)
                    : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </VisualCard>
  );
}
