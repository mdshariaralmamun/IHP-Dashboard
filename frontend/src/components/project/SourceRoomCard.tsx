'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  analyzeSources,
  deleteSource,
  downloadAttachment,
  generateDeliverables,
  getSourceBrief,
  getSourceRoom,
  getSourceText,
  uploadSources,
} from '@/lib/api';
import { answerQuestion, listQuestions } from '@/lib/api';
import type {
  GenerateResult,
  ProjectQuestion,
  SourceBrief,
  SourceDocument,
  SourceRoom,
} from '@/lib/api';
import { KpiCard, VisualCard } from '@/components/powerbi/PowerBI';

const SIZE_UNITS = ['B', 'KB', 'MB', 'GB'];

function size(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < SIZE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return (unit === 0 ? value : value.toFixed(1)) + ' ' + SIZE_UNITS[unit];
}

function availableStyle(value: string | undefined): string {
  const v = (value ?? '').toLowerCase();
  if (v.startsWith('yes')) return 'bg-emerald-100 text-emerald-800';
  if (v.startsWith('no')) return 'bg-red-100 text-red-800';
  return 'bg-amber-100 text-amber-800';
}

/**
 * The PR data room.
 *
 * Everything the engineer, the PI and the suppliers sent lands here - in
 * whatever format it was produced in - filed under the archive taxonomy the
 * team already uses. Each file's text is extracted on upload, the reviewer can
 * open it, and one click turns the whole room into the structured project
 * brief (scope by trade, utility matrix, line items, open technical queries)
 * that the MOM / Project Summary / SOW / BOQ / MTO are built from.
 */
export default function SourceRoomCard({
  projectId,
  canEdit,
}: {
  projectId: number;
  canEdit: boolean;
}) {
  const [room, setRoom] = useState<SourceRoom | null>(null);
  const [brief, setBrief] = useState<SourceBrief | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [category, setCategory] = useState('99_Unsorted');
  const [docType, setDocType] = useState('raw_data');
  const [openText, setOpenText] = useState<number | null>(null);
  const [textBody, setTextBody] = useState<string>('');
  const [polling, setPolling] = useState(false);
  const [generated, setGenerated] = useState<GenerateResult | null>(null);
  const [questions, setQuestions] = useState<ProjectQuestion[]>([]);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [generating, setGenerating] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const polls = useRef(0);

  const load = useCallback(async () => {
    try {
      const data = await getSourceRoom(projectId);
      setRoom(data);
      setBrief(data.brief ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load the data room');
    }
  }, [projectId]);

  useEffect(() => {
    void load();
    listQuestions(projectId)
      .then((data) => setQuestions(data.questions))
      .catch(() => undefined);
  }, [load, projectId]);

  async function saveAnswer(question: ProjectQuestion, status?: 'answered' | 'closed') {
    const answer = drafts[question.id];
    setBusy(true);
    setError(null);
    try {
      const saved = await answerQuestion(projectId, question.id, {
        answer: answer !== undefined ? answer : question.answer,
        status: status ?? 'answered',
      });
      setQuestions((rows) => rows.map((row) => (row.id === saved.id ? saved : row)));
      setNotice(
        (status === 'closed' ? 'Closed: ' : 'Answer saved: ') + question.question.slice(0, 60),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the answer');
    } finally {
      setBusy(false);
    }
  }

  // Poll the brief while the background analysis runs.
  useEffect(() => {
    if (!polling) return;
    if (polls.current > 90) {
      setPolling(false);
      setError('The analysis is taking longer than expected - refresh in a minute.');
      return;
    }
    const timer = setTimeout(async () => {
      polls.current += 1;
      try {
        const next = await getSourceBrief(projectId);
        if (next) {
          setBrief(next);
          if (next.status !== 'running') {
            setPolling(false);
            setNotice(
              next.status === 'ready'
                ? 'Brief v' + next.version + ' is ready.'
                : 'The analysis failed.',
            );
          }
        }
      } catch {
        /* keep polling */
      }
    }, 5000);
    return () => clearTimeout(timer);
  }, [polling, brief, projectId]);

  async function onUpload(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const data = await uploadSources(projectId, Array.from(fileList), category, docType);
      setRoom(data);
      setNotice(
        fileList.length + (fileList.length === 1 ? ' file' : ' files') + ' added to the data room.',
      );
      if (inputRef.current) inputRef.current.value = '';
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setBusy(false);
    }
  }

  async function analyze() {
    setBusy(true);
    setError(null);
    setNotice('Reading the data room — this can take a minute…');
    try {
      const started = await analyzeSources(projectId);
      setBrief(started);
      polls.current = 0;
      setPolling(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the analysis');
      setNotice(null);
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    setGenerating(true);
    setError(null);
    setNotice(null);
    try {
      const result = await generateDeliverables(projectId);
      setGenerated(result);
      setNotice(
        result.documents.length +
          ' document(s) built from brief v' +
          result.brief_version +
          ' and attached to the PR.',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not generate the documents');
    } finally {
      setGenerating(false);
    }
  }

  async function toggleText(doc: SourceDocument) {
    if (openText === doc.id) {
      setOpenText(null);
      return;
    }
    setOpenText(doc.id);
    setTextBody('Loading…');
    try {
      const body = await getSourceText(doc.id);
      setTextBody(body.text || body.note || 'No text could be extracted from this file.');
    } catch (e) {
      setTextBody(e instanceof Error ? e.message : 'Could not read the text');
    }
  }

  async function remove(doc: SourceDocument) {
    setBusy(true);
    try {
      await deleteSource(doc.id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete the file');
    } finally {
      setBusy(false);
    }
  }

  const documents = room?.documents ?? [];
  const byCategory = new Map<string, SourceDocument[]>();
  documents.forEach((doc) => {
    const list = byCategory.get(doc.category) ?? [];
    list.push(doc);
    byCategory.set(doc.category, list);
  });
  const payload = brief?.payload ?? null;

  return (
    <section className="rounded-xl border border-apple-border bg-white p-5 shadow-sm dark:bg-white/[0.04]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-bold text-apple-text">Data room — raw data &amp; AI brief</h2>
          <p className="mt-0.5 text-xs text-apple-muted">
            Engineer row data, PI emails, the utility matrix, the technical specification,
            drawings, quotations — any format. The AI reads the whole room and drafts the
            scope by trade, the utility matrix, the line items and the open technical queries.
          </p>
        </div>
        <span className="rounded-full bg-apple-surface px-2 py-0.5 text-[10px] font-semibold text-apple-muted">
          v{brief?.version ?? 0} · {room?.readable_documents ?? 0}/{documents.length} readable
        </span>
      </div>

      {canEdit && (
        <div className="mt-3 grid gap-2 rounded-lg border border-dashed border-apple-border bg-apple-surface/60 p-3 lg:grid-cols-[170px_180px_1fr_auto]">
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs text-apple-text"
          >
            {(room?.taxonomy ?? [{ key: '99_Unsorted', label: '99 Unsorted' }]).map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.label}
              </option>
            ))}
          </select>
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value)}
            className="rounded-md border border-apple-border bg-white px-2 py-1.5 text-xs text-apple-text"
          >
            {(room?.doc_types ?? ['raw_data']).map((entry) => (
              <option key={entry} value={entry}>
                {entry.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <input
            ref={inputRef}
            type="file"
            multiple
            onChange={(e) => void onUpload(e.target.files)}
            className="w-full rounded-md border border-apple-border bg-white px-2 py-1 text-xs text-apple-text file:mr-2 file:rounded file:border-0 file:bg-primary file:px-2 file:py-0.5 file:text-white"
          />
          <button
            type="button"
            onClick={() => void analyze()}
            disabled={busy || polling || documents.length === 0}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {polling ? 'Reading…' : 'Analyze with AI'}
          </button>
        </div>
      )}

      {documents.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <KpiCard label="Files" value={documents.length} accent="navy" />
          <KpiCard label="Readable" value={room?.readable_documents ?? 0} accent="green" />
          <KpiCard label="Stored" value={size(room?.total_bytes ?? 0)} accent="teal" />
          <KpiCard
            label="Open questions"
            value={(payload?.open_questions ?? []).length}
            accent="red"
            hint={(payload?.open_questions ?? []).filter((q) => q.blocking).length + ' blocking'}
          />
        </div>
      )}

      {documents.length === 0 ? (
        <p className="mt-3 rounded-lg border border-dashed border-apple-border p-6 text-center text-xs italic text-apple-muted">
          Nothing uploaded yet. Start with the PR form and the engineer&apos;s row data, then add
          the emails, the utility matrix and the specification.
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          {Array.from(byCategory.entries()).map(([key, docs]) => (
            <div key={key}>
              <h3 className="mb-1 text-[11px] font-bold uppercase tracking-wider text-apple-muted">
                {key}
              </h3>
              <ul className="space-y-1">
                {docs.map((doc) => (
                  <li
                    key={doc.id}
                    className="rounded-lg border border-apple-border px-2.5 py-1.5 text-xs"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-apple-text">{doc.filename}</span>
                      <span className="rounded-full bg-apple-surface px-2 py-0.5 text-[10px] font-semibold text-apple-muted">
                        {doc.doc_type.replace(/_/g, ' ')}
                      </span>
                      <span className="text-[10px] text-apple-muted">{size(doc.size_bytes)}</span>
                      {doc.text_chars > 0 ? (
                        <span className="text-[10px] text-emerald-700">
                          text extracted ({doc.text_chars.toLocaleString()} chars)
                        </span>
                      ) : (
                        <span className="text-[10px] text-amber-700">
                          {doc.extraction_note ?? 'no text'}
                        </span>
                      )}
                      <span className="ml-auto flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => void toggleText(doc)}
                          className="text-[10px] font-semibold text-primary hover:underline"
                        >
                          {openText === doc.id ? 'hide text' : 'view text'}
                        </button>
                        {canEdit && (
                          <button
                            type="button"
                            onClick={() => void remove(doc)}
                            disabled={busy}
                            className="text-[10px] font-semibold text-red-600 hover:underline disabled:opacity-50"
                          >
                            delete
                          </button>
                        )}
                      </span>
                    </div>
                    {(openText === doc.id || doc.text_excerpt) && openText !== doc.id && (
                      <p className="mt-1 text-[11px] italic text-apple-muted">{doc.text_excerpt}</p>
                    )}
                    {openText === doc.id && (
                      <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-apple-surface p-2 text-[11px] text-apple-text">
                        {textBody}
                      </pre>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {canEdit && brief?.status === 'ready' && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold text-emerald-800">
              Build the project documents
            </div>
            <p className="mt-0.5 text-[11px] text-emerald-700">
              Project Summary, Scope of Work, BOQ and MTO filled from your own templates
              using brief v{brief.version}. Prices stay blank for the QS.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void generate()}
            disabled={generating}
            className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
          >
            {generating ? 'Building…' : 'Generate documents'}
          </button>
        </div>
      )}

      {generated && (
        <ul className="mt-2 space-y-1">
          {generated.documents.map((doc) => (
            <li
              key={doc.attachment_id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-apple-border px-2.5 py-1.5 text-xs"
            >
              <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                {doc.kind}
              </span>
              <span className="font-medium text-apple-text">{doc.filename}</span>
              <span className="text-[10px] text-apple-muted">{size(doc.size_bytes)}</span>
              <button
                type="button"
                onClick={() => void downloadAttachment(projectId, doc.attachment_id, doc.filename)}
                className="ml-auto text-[10px] font-semibold text-primary hover:underline"
              >
                download
              </button>
            </li>
          ))}
        </ul>
      )}

      {brief?.status === 'running' && (
        <p className="mt-3 animate-pulse rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
          Reading every file in the data room…
        </p>
      )}
      {brief?.status === 'failed' && (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          Analysis failed: {brief.error}
        </p>
      )}

      {payload && (
        <div className="mt-4 space-y-3 border-t border-apple-border pt-3">
          {payload.summary && (
            <div className="rounded-lg bg-apple-surface p-3 text-xs text-apple-text">
              <span className="font-semibold">AI reading: </span>
              {payload.summary}
              {payload.confidence && (
                <span className="ml-2 rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-apple-muted">
                  confidence: {payload.confidence}
                </span>
              )}
            </div>
          )}

          <div className="grid gap-3 lg:grid-cols-2">
            {(payload.scope_by_trade ?? []).map((row, i) => (
              <VisualCard key={row.trade + i} title={row.trade}>
                {row.requirement && (
                  <p className="text-[11px] text-apple-text">
                    <span className="font-semibold">Asked: </span>
                    {row.requirement}
                  </p>
                )}
                {row.site_check && (
                  <p className="mt-1 text-[11px] text-apple-text">
                    <span className="font-semibold">Site allows / blocks: </span>
                    {row.site_check}
                  </p>
                )}
                {(row.excluded ?? []).length > 0 && (
                  <p className="mt-1 text-[11px] text-apple-muted">
                    <span className="font-semibold">Out of scope (exists): </span>
                    {(row.excluded ?? []).join('; ')}
                  </p>
                )}
                {(row.assumptions ?? []).length > 0 && (
                  <p className="mt-1 text-[11px] italic text-apple-muted">
                    Assumptions: {(row.assumptions ?? []).join('; ')}
                  </p>
                )}
              </VisualCard>
            ))}
          </div>

          {(payload.utilities ?? []).length > 0 && (
            <VisualCard title="Utility matrix" subtitle="what the project needs vs what the site has">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px]">
                  <thead>
                    <tr className="border-b border-apple-border text-[10px] uppercase text-apple-muted">
                      <th className="px-2 py-1">Utility</th>
                      <th className="px-2 py-1">Required</th>
                      <th className="px-2 py-1">At site</th>
                      <th className="px-2 py-1">Evidence</th>
                      <th className="px-2 py-1">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(payload.utilities ?? []).map((u, i) => (
                      <tr key={u.name + i} className="border-b border-apple-border/60 last:border-0">
                        <td className="px-2 py-1 font-semibold text-apple-text">{u.name}</td>
                        <td className="px-2 py-1 text-apple-muted">{u.required ?? '—'}</td>
                        <td className="px-2 py-1">
                          <span
                            className={
                              'rounded-full px-2 py-0.5 text-[10px] font-semibold ' +
                              availableStyle(u.available_at_site)
                            }
                          >
                            {u.available_at_site ?? 'unknown'}
                          </span>
                        </td>
                        <td className="px-2 py-1 text-apple-muted">{u.evidence ?? '—'}</td>
                        <td className="px-2 py-1 text-apple-muted">{u.action ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </VisualCard>
          )}

          {(payload.line_items ?? []).length > 0 && (
            <VisualCard
              title={'Line items — ' + (payload.line_items ?? []).length}
              subtitle="the take-off the BOQ and MTO are built from"
            >
              <div className="max-h-72 overflow-auto">
                <table className="w-full text-left text-[11px]">
                  <thead>
                    <tr className="border-b border-apple-border text-[10px] uppercase text-apple-muted">
                      <th className="px-2 py-1">Ref</th>
                      <th className="px-2 py-1">Trade</th>
                      <th className="px-2 py-1">Description</th>
                      <th className="px-2 py-1">Spec</th>
                      <th className="px-2 py-1">Unit</th>
                      <th className="px-2 py-1 text-right">Qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(payload.line_items ?? []).map((item, i) => (
                      <tr key={(item.ref ?? '') + i} className="border-b border-apple-border/60 last:border-0">
                        <td className="px-2 py-1 font-mono text-apple-muted">{item.ref ?? '—'}</td>
                        <td className="px-2 py-1 text-apple-muted">{item.trade ?? '—'}</td>
                        <td className="px-2 py-1 text-apple-text">{item.description}</td>
                        <td className="px-2 py-1 text-apple-muted">{item.spec ?? '—'}</td>
                        <td className="px-2 py-1 text-apple-muted">{item.unit ?? '—'}</td>
                        <td className="px-2 py-1 text-right tabular-nums text-apple-text">
                          {item.qty ?? '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </VisualCard>
          )}

          {(payload.open_questions ?? []).length > 0 && (
            <VisualCard
              title={'Open questions / TQ — ' + (payload.open_questions ?? []).length}
              subtitle="answer these before the documents are issued"
            >
              <ul className="space-y-1">
                {(payload.open_questions ?? []).map((q, i) => (
                  <li
                    key={i}
                    className={
                      'rounded-lg border px-2.5 py-1.5 text-[11px] ' +
                      (q.blocking ? 'border-red-200 bg-red-50/60' : 'border-apple-border')
                    }
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      {q.blocking && (
                        <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold text-white">
                          BLOCKING
                        </span>
                      )}
                      <span className="font-semibold text-apple-text">{q.question}</span>
                      {q.who_can_answer && (
                        <span className="rounded-full bg-apple-surface px-2 py-0.5 text-[10px] text-apple-muted">
                          ask: {q.who_can_answer}
                        </span>
                      )}
                    </div>
                    {q.why && <p className="mt-0.5 text-apple-muted">{q.why}</p>}
                  </li>
                ))}
              </ul>
            </VisualCard>
          )}

          {questions.length > 0 && (
            <VisualCard
              title={'Questions & clarifications — ' + questions.length}
              subtitle="write the answer here; it is kept with the project, not with the brief"
            >
              <ul className="space-y-2">
                {questions.map((question) => (
                  <li
                    key={question.id}
                    className={
                      'rounded-lg border p-2.5 ' +
                      (question.status === 'closed'
                        ? 'border-slate-200 bg-slate-50/60 dark:border-white/10'
                        : question.blocking
                          ? 'border-red-200 bg-red-50/50'
                          : 'border-slate-200 dark:border-white/10')
                    }
                  >
                    <div className="flex flex-wrap items-center gap-2 text-[11px]">
                      {question.blocking && question.status === 'open' && (
                        <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold text-white">
                          BLOCKING
                        </span>
                      )}
                      <span className="font-semibold text-apple-text">{question.question}</span>
                      {question.who_can_answer && (
                        <span className="rounded-full bg-apple-surface px-2 py-0.5 text-[10px] text-apple-muted">
                          ask: {question.who_can_answer}
                        </span>
                      )}
                      <span
                        className={
                          'ml-auto rounded-full px-2 py-0.5 text-[10px] font-semibold ' +
                          (question.status === 'closed'
                            ? 'bg-slate-200 text-slate-700'
                            : question.status === 'answered'
                              ? 'bg-emerald-100 text-emerald-800'
                              : 'bg-amber-100 text-amber-800')
                        }
                      >
                        {question.status}
                      </span>
                    </div>
                    {question.detail && (
                      <p className="mt-0.5 text-[11px] text-apple-muted">{question.detail}</p>
                    )}
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <input
                        defaultValue={question.answer ?? ''}
                        onChange={(event) =>
                          setDrafts((rows) => ({ ...rows, [question.id]: event.target.value }))
                        }
                        placeholder="Type the answer / clarification here…"
                        className="min-w-[16rem] flex-1 rounded-md border border-apple-border bg-apple-surface px-2 py-1 text-xs text-apple-text"
                      />
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void saveAnswer(question, 'answered')}
                        className="rounded-md bg-primary px-3 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
                      >
                        Save answer
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void saveAnswer(question, 'closed')}
                        className="rounded-md border border-apple-border px-3 py-1 text-xs font-semibold text-apple-muted hover:bg-apple-surface disabled:opacity-50"
                      >
                        Close
                      </button>
                      {question.answered_at && (
                        <span className="text-[10px] text-apple-muted">
                          answered {question.answered_at.slice(0, 10)}
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </VisualCard>
          )}

          {((payload.missing_documents ?? []).length > 0 || (payload.risks ?? []).length > 0) && (
            <div className="grid gap-3 lg:grid-cols-2">
              {(payload.missing_documents ?? []).length > 0 && (
                <VisualCard title="Missing documents">
                  <ul className="list-inside list-disc text-[11px] text-apple-muted">
                    {(payload.missing_documents ?? []).map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                </VisualCard>
              )}
              {(payload.risks ?? []).length > 0 && (
                <VisualCard title="Risks">
                  <ul className="list-inside list-disc text-[11px] text-apple-muted">
                    {(payload.risks ?? []).map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                </VisualCard>
              )}
            </div>
          )}
        </div>
      )}

      {error && (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}
      {notice && !error && (
        <p className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          {notice}
        </p>
      )}
    </section>
  );
}
