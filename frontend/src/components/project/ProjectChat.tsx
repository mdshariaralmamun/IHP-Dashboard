'use client';

import { useRef, useState } from 'react';
import { aiChat } from '@/lib/api';
import type { AiChatReply, AiChatScope } from '@/lib/api';
import { VisualCard } from '@/components/powerbi/PowerBI';

interface Turn {
  role: 'you' | 'ai';
  text: string;
  citations?: AiChatReply['citations'];
  failed?: boolean;
}

const SCOPES: { key: AiChatScope; label: string }[] = [
  { key: 'project', label: 'This project' },
  { key: 'standards', label: 'Standards & specifications' },
  { key: 'all', label: 'Everything' },
];

/**
 * The project's AI chat.
 *
 * A chat window that works on the PR's own material: the indexed attachments,
 * the data room and the reference libraries (KAUST specifications, MEP BOQ,
 * the MEP narrative). It answers scope and document questions, and its replies
 * cite the documents they came from - it never answers from outside the
 * project unless you switch the scope.
 */
export default function ProjectChat({ projectId, prNumber }: { projectId: number; prNumber: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [scope, setScope] = useState<AiChatScope>('project');
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  async function send() {
    const message = input.trim();
    if (!message || busy) return;
    setTurns((rows) => [...rows, { role: 'you', text: message }]);
    setInput('');
    setBusy(true);
    try {
      const answer = await aiChat({ projectId, message, scope });
      setTurns((rows) => [
        ...rows,
        { role: 'ai', text: answer.reply, citations: answer.citations },
      ]);
    } catch (error) {
      setTurns((rows) => [
        ...rows,
        {
          role: 'ai',
          text: error instanceof Error ? error.message : 'The AI could not answer.',
          failed: true,
        },
      ]);
    } finally {
      setBusy(false);
      setTimeout(() => boxRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 50);
    }
  }

  return (
    <VisualCard
      title={'AI chat — ' + prNumber}
      subtitle="ask about the scope, the documents, the standards; answers cite the files"
      actions={
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value as AiChatScope)}
          className="rounded border border-slate-200 px-2 py-0.5 text-[10px] dark:border-white/10 dark:bg-white/5"
        >
          {SCOPES.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      }
    >
      <div ref={boxRef} className="max-h-80 space-y-2 overflow-auto pr-1">
        {turns.length === 0 && (
          <p className="rounded-lg border border-dashed border-slate-200 p-3 text-[11px] italic text-slate-400">
            Ask anything about this PR — “what does the specification say about the N2 line?”,
            “is the partition fire rated?”, “list the materials in the BOQ”. Index this PR&apos;s
            attachments first (Settings → AI) so the answer can read them.
          </p>
        )}
        {turns.map((turn, index) => (
          <div
            key={index}
            className={
              'rounded-lg px-3 py-2 text-[12px] ' +
              (turn.role === 'you'
                ? 'ml-8 bg-primary/10 text-apple-text'
                : turn.failed
                  ? 'mr-8 bg-red-50 text-red-800'
                  : 'mr-8 bg-apple-surface text-apple-text')
            }
          >
            <div className="whitespace-pre-wrap">{turn.text}</div>
            {(turn.citations ?? []).length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {(turn.citations ?? []).slice(0, 6).map((cite, i) => (
                  <span
                    key={i}
                    className="rounded-full bg-white px-2 py-0.5 text-[10px] text-slate-500 ring-1 ring-inset ring-slate-200 dark:bg-white/10"
                  >
                    {cite.label ?? cite.filename ?? cite.detail ?? 'source'}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <p className="text-[11px] italic text-slate-400">Thinking…</p>}
      </div>

      <div className="mt-2 flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          rows={2}
          placeholder="Write your question or your input about the project… (Enter to send, Shift+Enter for a new line)"
          className="flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-apple-text outline-none focus:border-primary dark:border-white/10 dark:bg-white/5"
        />
        <button
          type="button"
          onClick={() => void send()}
          disabled={busy || !input.trim()}
          className="rounded-md bg-primary px-4 py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </VisualCard>
  );
}
