'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  cancelProject,
  createTodo,
  deleteTodo,
  getNextStep,
  setNextStep,
  updateTodo,
} from '@/lib/api';
import type { CancelResult, NextStepResponse, ProjectDetail, Todo } from '@/lib/types';
import { FOLLOWUP_BUCKETS } from '@/lib/types';
import { STAGES, stageName } from '@/lib/stages';

/**
 * The one panel that answers "what happens next?" for a PR.
 *
 * The plan is a single next step - the lifecycle stage (MTO, EAR, Design,
 * Procore, PTW/WICF, Construction, Shutdown, Quality Inspection, WCC, WCH,
 * ICR), the bucket it is followed up in, who owns it and when it is due -
 * plus the to-do rows that get it there. "Move now" executes the planned
 * stage through the workflow instead of only scheduling it.
 *
 * Cancellation is here too, because stopping a PR is the other possible next
 * step: it keeps a reason, a written justification and the email the PI was
 * sent (or the draft, when SMTP is off).
 */
export default function NextStepCard({
  project,
  canEdit,
  onChanged,
}: {
  project: ProjectDetail;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const [state, setState] = useState<NextStepResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [stage, setStage] = useState('');
  const [bucket, setBucket] = useState('');
  const [date, setDate] = useState('');
  const [owner, setOwner] = useState('');
  const [note, setNote] = useState('');

  const [todoTitle, setTodoTitle] = useState('');
  const [todoBucket, setTodoBucket] = useState('');
  const [todoOwner, setTodoOwner] = useState('');
  const [todoDue, setTodoDue] = useState('');

  const [cancelReason, setCancelReason] = useState('');
  const [cancelText, setCancelText] = useState('');
  const [cancelEmail, setCancelEmail] = useState(true);
  const [cancelResult, setCancelResult] = useState<CancelResult | null>(null);

  const load = useCallback(() => {
    getNextStep(project.id)
      .then((data) => {
        setState(data);
        setStage(data.next_stage ?? '');
        setBucket(data.next_stage_bucket ?? '');
        setDate(data.next_stage_date ?? '');
        setOwner(data.next_stage_owner ?? '');
        setNote(data.next_step_note ?? '');
        setTodoBucket((b) => b || data.next_stage_bucket || '');
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'));
  }, [project.id]);

  useEffect(load, [load]);

  async function savePlan(moveNow = false) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await setNextStep(project.id, {
        next_stage: stage,
        next_stage_bucket: bucket,
        next_stage_date: date,
        next_stage_owner: owner,
        next_step_note: note,
        move_now: moveNow,
        justification: note || 'next step',
      });
      setState(saved);
      setNotice(
        moveNow
          ? 'Moved to ' + stageName(saved.stage) + '.'
          : 'Next step saved' + (saved.next_stage ? ' — ' + stageName(saved.next_stage) : '') + '.',
      );
      if (moveNow) {
        setStage(saved.next_stage ?? '');
        setDate(saved.next_stage_date ?? '');
      }
      onChanged();
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : 'Could not save the next step.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function addTodo() {
    if (!todoTitle.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createTodo(project.id, {
        title: todoTitle,
        bucket: todoBucket || bucket || null,
        assignee_username: todoOwner || null,
        due_date: todoDue || null,
      });
      setTodoTitle('');
      setTodoOwner('');
      setTodoDue('');
      load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not add the task.');
    } finally {
      setBusy(false);
    }
  }

  async function toggle(todo: Todo) {
    setBusy(true);
    try {
      await updateTodo(todo.id, { status: todo.status === 'done' ? 'open' : 'done' });
      load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update the task.');
    } finally {
      setBusy(false);
    }
  }

  async function remove(todo: Todo) {
    setBusy(true);
    try {
      await deleteTodo(todo.id);
      load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete the task.');
    } finally {
      setBusy(false);
    }
  }

  async function doCancel() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await cancelProject(project.id, {
        reason: cancelReason,
        justification: cancelText,
        send_email: cancelEmail,
      });
      setCancelResult(result);
      setNotice(
        result.emailed
          ? 'Cancelled and the PI was emailed at ' + (result.email_to ?? '') + '.'
          : 'Cancelled. The email is ready below — SMTP is not configured, so send it by hand.',
      );
      load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not cancel the project.');
    } finally {
      setBusy(false);
    }
  }

  const todos = state?.todos ?? [];
  const open = todos.filter((t) => t.status !== 'done');
  const done = todos.filter((t) => t.status === 'done');
  const cancelled = project.stage === 'CANCELLED';
  const mailto =
    cancelResult && cancelResult.email_to
      ? 'mailto:' +
        cancelResult.email_to +
        '?subject=' +
        encodeURIComponent(cancelResult.email_subject ?? '') +
        '&body=' +
        encodeURIComponent(cancelResult.email_body ?? '')
      : null;

  return (
    <section className="rounded-xl border border-apple-border bg-white p-5 shadow-sm dark:bg-white/[0.04]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-bold text-apple-text">Next step &amp; to-do</h2>
          <p className="mt-0.5 text-xs text-apple-muted">
            Current stage <span className="font-semibold text-apple-text">{stageName(project.stage)}</span>.
            One next step per PR, with the bucket it is followed up in and the tasks that get it there.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[10px] font-semibold">
          {cancelled && (
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-800 ring-1 ring-inset ring-red-300">
              CANCELLED
            </span>
          )}
          <span className="rounded-full bg-apple-surface px-2 py-0.5 text-apple-muted">
            {open.length} open · {done.length} done
          </span>
        </div>
      </div>

      {cancelled && state?.cancel_reason && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-900">
          <div className="font-semibold">Cancelled — {state.cancel_reason}</div>
          <p className="mt-1 whitespace-pre-wrap">{state.cancel_justification}</p>
          <p className="mt-1 text-[11px] italic">
            {state.cancel_notified_at
              ? 'The PI was emailed on ' + state.cancel_notified_at.slice(0, 10) + '.'
              : 'No email was sent.'}
          </p>
        </div>
      )}

      {canEdit && !cancelled && (
        <>
          <div className="mt-3 grid gap-2 lg:grid-cols-[220px_180px_150px_180px_1fr]">
            <label className="block">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-apple-muted">
                Next stage
              </span>
              <select
                value={stage}
                onChange={(e) => setStage(e.target.value)}
                className="mt-0.5 w-full rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
              >
                <option value="">— not scheduled —</option>
                {STAGES.filter((s) => s.id !== project.stage).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                    {s.terminal ? ' (final)' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-apple-muted">
                Follow-up bucket
              </span>
              <select
                value={bucket}
                onChange={(e) => setBucket(e.target.value)}
                className="mt-0.5 w-full rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
              >
                <option value="">— none —</option>
                {FOLLOWUP_BUCKETS.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-apple-muted">
                Due date
              </span>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="mt-0.5 w-full rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
              />
            </label>
            <label className="block">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-apple-muted">
                Assign to
              </span>
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="engineer / planner"
                className="mt-0.5 w-full rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
              />
            </label>
            <label className="block">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-apple-muted">
                What is the next step
              </span>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. Issue the SOW, then book the shutdown window"
                className="mt-0.5 w-full rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
              />
            </label>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void savePlan(false)}
              disabled={busy}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              Save next step
            </button>
            <button
              type="button"
              onClick={() => void savePlan(true)}
              disabled={busy || !stage}
              title="Walk the project into the planned stage now (the usual workflow path is enforced)"
              className="rounded-md border border-primary px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/10 disabled:opacity-50"
            >
              Move now
            </button>
            {(state?.next_stage || state?.next_stage_date) && (
              <span className="self-center text-[11px] text-apple-muted">
                Scheduled: {stageName(state?.next_stage)} {state?.next_stage_date ?? ''}
              </span>
            )}
          </div>
        </>
      )}

      {/* The to-do rows that get the PR there */}
      <div className="mt-4 border-t border-apple-border pt-3">
        <h3 className="text-xs font-bold uppercase tracking-wide text-apple-muted">
          To-do list
        </h3>
        {canEdit && (
          <div className="mt-2 grid gap-2 lg:grid-cols-[1fr_170px_150px_140px_auto]">
            <input
              value={todoTitle}
              onChange={(e) => setTodoTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void addTodo();
              }}
              placeholder="Add a task — e.g. Confirm the shutdown window with O&M"
              className="rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
            />
            <select
              value={todoBucket}
              onChange={(e) => setTodoBucket(e.target.value)}
              className="rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
            >
              <option value="">Bucket…</option>
              {FOLLOWUP_BUCKETS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
            <input
              value={todoOwner}
              onChange={(e) => setTodoOwner(e.target.value)}
              placeholder="Assign to"
              className="rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
            />
            <input
              type="date"
              value={todoDue}
              onChange={(e) => setTodoDue(e.target.value)}
              className="rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
            />
            <button
              type="button"
              onClick={() => void addTodo()}
              disabled={busy || !todoTitle.trim()}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              + Add
            </button>
          </div>
        )}

        {todos.length === 0 ? (
          <p className="mt-2 rounded-lg border border-dashed border-apple-border p-3 text-center text-xs italic text-apple-muted">
            No tasks yet.
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {todos.map((todo) => (
              <li
                key={todo.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-apple-border px-2.5 py-1.5 text-xs"
              >
                <input
                  type="checkbox"
                  checked={todo.status === 'done'}
                  disabled={!canEdit || busy}
                  onChange={() => void toggle(todo)}
                />
                <span
                  className={
                    todo.status === 'done'
                      ? 'text-apple-muted line-through'
                      : 'font-medium text-apple-text'
                  }
                >
                  {todo.title}
                </span>
                {todo.bucket && (
                  <span className="rounded-full bg-apple-surface px-2 py-0.5 text-[10px] font-semibold text-apple-muted">
                    {todo.bucket}
                  </span>
                )}
                {todo.assignee_username && (
                  <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700">
                    {todo.assignee_username}
                  </span>
                )}
                {todo.due_date && (
                  <span className="text-[10px] text-apple-muted">due {todo.due_date}</span>
                )}
                {todo.note && (
                  <span className="text-[10px] italic text-apple-muted">{todo.note}</span>
                )}
                {canEdit && (
                  <button
                    type="button"
                    onClick={() => void remove(todo)}
                    disabled={busy}
                    className="ml-auto text-[10px] font-semibold text-red-600 hover:underline disabled:opacity-50"
                  >
                    delete
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Cancellation: the other possible next step */}
      {canEdit && !cancelled && (
        <details className="mt-4 border-t border-apple-border pt-3">
          <summary className="cursor-pointer text-xs font-bold uppercase tracking-wide text-red-700">
            Cancel this project (reason + justification + email)
          </summary>
          <div className="mt-2 grid gap-2 lg:grid-cols-[240px_1fr]">
            <input
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              placeholder="Reason — e.g. Budget pulled"
              className="rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
            />
            <textarea
              value={cancelText}
              onChange={(e) => setCancelText(e.target.value)}
              rows={3}
              placeholder="Justification — what was decided, by whom, and what the PI should do next (a new PR re-initiates it)."
              className="rounded-md border border-apple-border bg-apple-surface px-2 py-1.5 text-xs text-apple-text"
            />
          </div>
          <label className="mt-2 flex items-center gap-2 text-[11px] text-apple-text">
            <input
              type="checkbox"
              checked={cancelEmail}
              onChange={(e) => setCancelEmail(e.target.checked)}
            />
            Email the PI ({project.pi_email ?? 'no PI email on file'}) with the reason and
            justification.
          </label>
          <button
            type="button"
            onClick={() => void doCancel()}
            disabled={busy || cancelReason.trim().length < 3 || cancelText.trim().length < 10}
            className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          >
            Cancel project
          </button>
          {cancelResult && (
            <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[11px] text-amber-900">
              <div className="font-semibold">
                {cancelResult.emailed ? 'Email sent to ' : 'Email draft for '}
                {cancelResult.email_to}
              </div>
              <div className="mt-1 font-mono text-[10px]">{cancelResult.email_subject}</div>
              <pre className="mt-1 whitespace-pre-wrap font-sans text-[11px]">
                {cancelResult.email_body}
              </pre>
              {mailto && (
                <a
                  href={mailto}
                  className="mt-1 inline-block font-semibold text-amber-900 underline"
                >
                  Open in your mail client
                </a>
              )}
            </div>
          )}
        </details>
      )}

      {error && (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}
      {notice && (
        <p className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          {notice}
        </p>
      )}
    </section>
  );
}
