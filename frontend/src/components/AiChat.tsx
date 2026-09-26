'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { askAi, listAiModels, sendAiFeedback } from '@/lib/api';
import { useUser } from '@/lib/useUser';
import type { AiModel, AiSource } from '@/lib/types';

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  ts: number;
  sources?: AiSource[];
  mode?: 'llm' | 'extractive' | 'live';
  model?: string;
  error?: boolean;
}

const MODEL_KEY = 'ihp-ai-model';

const PROJECT_PROMPTS = [
  'Summarise this project for a status report',
  'What is blocking this project right now?',
  'What documents are still outstanding?',
  'Draft a short client update',
];

const PORTFOLIO_PROMPTS = [
  'Which projects are overdue?',
  'Summarise the Design pipeline',
  'What construction work is active this week?',
  'Draft a weekly portfolio summary',
];

// ---------------------------------------------------------------------------
// Small inline icons (no icon dependency)
// ---------------------------------------------------------------------------

function SparkIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path
        d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"
        fill="currentColor"
      />
      <path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" fill="currentColor" opacity="0.75" />
    </svg>
  );
}

function SendIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path d="M12 19V5M12 5l-6 6M12 5l6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CloseIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function RefreshIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path d="M4 4v6h6M20 20v-6h-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M20 10a8 8 0 00-14.3-4.6M4 14a8 8 0 0014.3 4.6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function CopyIcon({ className = 'h-3.5 w-3.5' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M15 6.5A2.5 2.5 0 0012.5 4H6a2 2 0 00-2 2v6.5A2.5 2.5 0 006.5 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function ThumbIcon({ down = false, className = 'h-3.5 w-3.5' }: { down?: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true"
      style={down ? { transform: 'rotate(180deg)' } : undefined}>
      <path
        d="M7 10v10H4.5A1.5 1.5 0 013 18.5v-7A1.5 1.5 0 014.5 10H7zm0 0l4.2-6.3A1.6 1.6 0 0114 4.6V9h4.6a2 2 0 012 2.4l-1.2 6A2 2 0 0117.4 19H7"
        stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round"
      />
    </svg>
  );
}

function DocIcon({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      <path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Lightweight markdown rendering (headings, lists, code, bold, inline code)
// ---------------------------------------------------------------------------

function inlineNodes(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\x60[^\x60]+\x60)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith('**')) {
      out.push(
        <strong key={keyPrefix + '-b' + i} className="font-semibold text-apple-text">
          {token.slice(2, -2)}
        </strong>,
      );
    } else {
      out.push(
        <code
          key={keyPrefix + '-c' + i}
          className="rounded bg-black/[0.06] px-1 py-0.5 font-mono text-[12px] dark:bg-white/10"
        >
          {token.slice(1, -1)}
        </code>,
      );
    }
    last = match.index + token.length;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { kind: 'p' | 'h'; text: string }
  | { kind: 'ul' | 'ol'; items: string[] }
  | { kind: 'pre'; text: string };

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let list: Block & { kind: 'ul' | 'ol' } | null = null;
  let code: string[] | null = null;

  for (const rawLine of text.split('\n')) {
    const line = rawLine.replace(/\s+$/, '');
    if (code) {
      if (line.trim().startsWith('\x60\x60\x60')) {
        blocks.push({ kind: 'pre', text: code.join('\n') });
        code = null;
      } else {
        code.push(rawLine);
      }
      continue;
    }
    if (line.trim().startsWith('\x60\x60\x60')) {
      code = [];
      continue;
    }
    const bullet = /^\s*[-*\u2022]\s+(.*)$/.exec(line);
    const numbered = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
    if (bullet) {
      if (!list || list.kind !== 'ul') {
        list = { kind: 'ul', items: [] };
        blocks.push(list);
      }
      list.items.push(bullet[1]);
      continue;
    }
    if (numbered) {
      if (!list || list.kind !== 'ol') {
        list = { kind: 'ol', items: [] };
        blocks.push(list);
      }
      list.items.push(numbered[2]);
      continue;
    }
    list = null;
    if (!line.trim()) continue;
    const heading = /^\s*#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ kind: 'h', text: heading[1] });
      continue;
    }
    blocks.push({ kind: 'p', text: line });
  }
  if (code) blocks.push({ kind: 'pre', text: code.join('\n') });
  return blocks;
}

function RichText({ text }: { text: string }) {
  const blocks = useMemo(() => parseBlocks(text), [text]);
  return (
    <div className="space-y-1.5 text-[13px] leading-relaxed">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case 'pre':
            return (
              <pre
                key={index}
                className="chat-scroll overflow-x-auto rounded-lg bg-black/[0.05] p-2.5 font-mono text-[12px] dark:bg-white/[0.06]"
              >
                {block.text}
              </pre>
            );
          case 'ul':
          case 'ol': {
            const Tag = block.kind === 'ul' ? 'ul' : 'ol';
            return (
              <Tag
                key={index}
                className={
                  'ml-4 space-y-1 ' +
                  (block.kind === 'ul' ? 'list-disc' : 'list-decimal')
                }
              >
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{inlineNodes(item, 'l' + index + '-' + itemIndex)}</li>
                ))}
              </Tag>
            );
          }
          case 'h':
            return (
              <p key={index} className="pt-1 font-semibold text-apple-text">
                {inlineNodes(block.text, 'h' + index)}
              </p>
            );
          default:
            return (
              <p key={index} className="whitespace-pre-wrap break-words">
                {inlineNodes(block.text, 'p' + index)}
              </p>
            );
        }
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function timeLabel(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return '';
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return gb.toFixed(1) + ' GB';
  return Math.round(bytes / 1024 ** 2) + ' MB';
}

function AssistantAvatar() {
  return (
    <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[var(--kaust-primary)] to-[var(--kaust-blue)] text-white shadow-sm">
      <SparkIcon className="h-3.5 w-3.5" />
    </div>
  );
}

function MessageRow({
  message,
  onCopy,
  rating,
  onRate,
}: {
  message: Message;
  onCopy: () => void;
  rating?: 'up' | 'down';
  onRate?: (rating: 'up' | 'down') => void;
}) {
  const [showSources, setShowSources] = useState(false);
  const sources = message.sources ?? [];

  if (message.role === 'user') {
    return (
      <div className="animate-msg-in flex justify-end">
        <div className="max-w-[85%] space-y-1">
          <div className="rounded-2xl rounded-br-md bg-gradient-to-br from-[var(--kaust-primary)] to-[var(--kaust-blue)] px-3.5 py-2.5 text-[13px] leading-relaxed text-white shadow-sm">
            <p className="whitespace-pre-wrap break-words">{message.text}</p>
          </div>
          <p className="pr-1 text-right text-[10px] text-apple-muted">{timeLabel(message.ts)}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-msg-in flex gap-2.5">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 space-y-1">
        <div
          className={
            'group relative rounded-2xl rounded-tl-md border px-3.5 py-2.5 shadow-sm ' +
            (message.error
              ? 'border-status-rejected/30 bg-status-rejected/[0.07] text-status-rejected'
              : 'border-apple-border/60 bg-apple-surface text-apple-text backdrop-blur')
          }
        >
          {message.error ? (
            <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed">{message.text}</p>
          ) : (
            <RichText text={message.text} />
          )}
          {!message.error && (
            <button
              type="button"
              onClick={onCopy}
              title="Copy answer"
              className="absolute -top-2.5 right-2 hidden rounded-md border border-apple-border bg-white p-1 text-apple-muted shadow-sm transition hover:text-apple-text group-hover:block dark:bg-[#242426]"
            >
              <CopyIcon />
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5 pl-1 text-[10px] text-apple-muted">
          <span>{timeLabel(message.ts)}</span>
          {message.model && (
            <>
              <span className="opacity-40">&middot;</span>
              <span className="font-mono">{message.model}</span>
            </>
          )}
          {message.mode === 'live' && (
            <span className="rounded-full bg-status-approved/15 px-1.5 py-px font-medium text-status-approved">
              live database
            </span>
          )}
          {message.mode === 'extractive' && (
            <span className="rounded-full bg-status-warning/15 px-1.5 py-px font-medium text-status-warning">
              knowledge base only
            </span>
          )}
          {sources.length > 0 && (
            <button
              type="button"
              onClick={() => setShowSources((value) => !value)}
              className="rounded-full border border-apple-border/70 px-1.5 py-px font-medium transition hover:border-apple-primary hover:text-apple-primary"
            >
              {sources.length} source{sources.length === 1 ? '' : 's'}
            </button>
          )}
          {onRate && !message.error && (
            <span className="ml-0.5 flex items-center gap-0.5">
              <button
                type="button"
                title="Good answer (saved as training signal)"
                onClick={() => onRate('up')}
                className={
                  'rounded p-0.5 transition ' +
                  (rating === 'up'
                    ? 'bg-status-approved/15 text-status-approved'
                    : 'text-apple-muted hover:text-status-approved')
                }
              >
                <ThumbIcon />
              </button>
              <button
                type="button"
                title="Bad answer (saved as training signal)"
                onClick={() => onRate('down')}
                className={
                  'rounded p-0.5 transition ' +
                  (rating === 'down'
                    ? 'bg-status-rejected/15 text-status-rejected'
                    : 'text-apple-muted hover:text-status-rejected')
                }
              >
                <ThumbIcon down />
              </button>
              {rating && <span className="text-[10px]">saved</span>}
            </span>
          )}
        </div>

        {showSources && sources.length > 0 && (
          <div className="animate-msg-in space-y-1.5 rounded-xl border border-apple-border/60 bg-apple-surface/70 p-2.5">
            {sources.map((source, index) => (
              <div key={index} className="flex gap-2">
                <span className="mt-0.5 shrink-0 text-apple-primary">
                  <DocIcon />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[11px] font-medium text-apple-text">{source.filename}</p>
                  <p className="line-clamp-2 text-[10.5px] leading-snug text-apple-muted">{source.snippet}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AiChat() {
  const pathname = usePathname();
  const { user } = useUser();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);

  const [ratings, setRatings] = useState<Record<string, 'up' | 'down'>>({});
  const [models, setModels] = useState<AiModel[]>([]);
  const [provider, setProvider] = useState('');
  const [providerLabel, setProviderLabel] = useState('');
  const [model, setModel] = useState('');
  const [modelsLoaded, setModelsLoaded] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const projectMatch = /^\/projects\/(\d+)/.exec(pathname ?? '');
  const projectId = projectMatch ? Number(projectMatch[1]) : undefined;

  const firstName = (user?.full_name || user?.username || '').split(' ')[0];
  const prompts = projectId ? PROJECT_PROMPTS : PORTFOLIO_PROMPTS;

  const greeting = useMemo<Message>(
    () => ({
      id: 'welcome',
      role: 'assistant',
      text:
        (firstName ? firstName + ', welcome' : 'Welcome') +
        (projectId
          ? ' — I can see PR ' + projectId + '. Ask about its documents, schedule or risks.'
          : ' — ask me anything about the portfolio. I answer from the knowledge base and cite my sources.'),
      ts: Date.now(),
    }),
    [firstName, projectId],
  );

  const thread = messages.length === 0 ? [greeting] : [greeting, ...messages];

  // Load the available models the first time the panel opens.
  useEffect(() => {
    if (!open || modelsLoaded) return;
    let alive = true;
    listAiModels()
      .then((res) => {
        if (!alive) return;
        setProvider(res.provider || '');
        setProviderLabel(res.provider_label || '');
        setModels(res.models || []);
        const saved = typeof window !== 'undefined' ? window.localStorage.getItem(MODEL_KEY) : null;
        const savedModel = (res.models || []).find((item) => item.name === saved);
        setModel((current) => current || savedModel?.name || res.active || res.models?.[0]?.name || '');
        setModelsLoaded(true);
      })
      .catch(() => {
        if (alive) setModelsLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, [open, modelsLoaded]);

  // Keep the newest message in view.
  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' });
  }, [messages, busy, open]);

  // Focus + auto-grow the composer.
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => inputRef.current?.focus(), 80);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = Math.min(node.scrollHeight, 148) + 'px';
  }, [input, open]);

  // Escape closes the panel.
  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  function rate(message: Message, question: string, rating: 'up' | 'down') {
    setRatings((prev) => ({ ...prev, [message.id]: rating }));
    void sendAiFeedback({
      question,
      answer: message.text,
      rating,
      mode: message.mode,
      model: message.model,
      project_id: projectId,
      sources: message.sources,
    }).catch(() => {
      /* rating is best-effort */
    });
  }

  function selectModel(name: string) {
    setModel(name);
    try {
      window.localStorage.setItem(MODEL_KEY, name);
    } catch {
      /* storage unavailable */
    }
  }

  async function handleSend(preset?: string) {
    const question = (preset ?? input).trim();
    if (!question || busy) return;
    if (!preset) setInput('');
    // Prior turns give follow-ups ("and which of those are overdue?") their
    // context. The backend trims this to the last few exchanges.
    const history = messages.slice(-4).map((message) => ({
      role: message.role,
      content: message.text,
    }));
    const stamp = Date.now();
    setMessages((prev) => [
      ...prev,
      { id: 'u' + stamp, role: 'user', text: question, ts: stamp },
    ]);
    setBusy(true);
    const started = Date.now();
    try {
      const res = await askAi(question, projectId, model || undefined, history);
      setMessages((prev) => [
        ...prev,
        {
          id: 'a' + Date.now(),
          role: 'assistant',
          text: res.answer || '(the assistant returned an empty answer)',
          ts: Date.now(),
          sources: res.sources ?? [],
          mode: res.mode,
          model: model || undefined,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: 'e' + Date.now(),
          role: 'assistant',
          text:
            'I could not reach the assistant (' +
            (err instanceof Error ? err.message : 'request failed') +
            '). It answered in ' + Math.round((Date.now() - started) / 1000) + 's.',
          ts: Date.now(),
          error: true,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const activeModel = models.find((item) => item.name === model);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label="Open the AI assistant"
        className={
          'group fixed bottom-5 right-5 z-50 items-center gap-2 rounded-full border border-white/15 ' +
          'bg-gradient-to-br from-[var(--kaust-primary)] to-[var(--kaust-blue)] px-4 py-2.5 text-sm ' +
          'font-medium text-white shadow-lg shadow-black/25 transition-all hover:scale-[1.03] ' +
          'hover:shadow-xl active:scale-95 ' +
          (open ? 'hidden sm:flex' : 'flex')
        }
      >
        <SparkIcon className="h-4 w-4" />
        <span>Ask AI</span>
      </button>

      {open && (
        <div
          className={
            'animate-chat-in fixed inset-x-3 bottom-3 z-50 flex h-[min(78vh,720px)] flex-col overflow-hidden ' +
            'rounded-2xl border border-apple-border/70 bg-white/95 shadow-2xl shadow-black/20 backdrop-blur-xl ' +
            'dark:bg-[#161618]/95 dark:shadow-black/60 ' +
            'sm:inset-x-auto sm:bottom-24 sm:right-5 sm:h-[min(720px,calc(100vh-8rem))] sm:w-[460px]'
          }
        >
          {/* Header */}
          <header className="flex items-center gap-3 border-b border-apple-border/60 bg-gradient-to-r from-[var(--kaust-primary)]/[0.07] to-transparent px-4 py-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[var(--kaust-primary)] to-[var(--kaust-blue)] text-white shadow-md">
              <SparkIcon className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[13.5px] font-semibold leading-tight text-apple-text">IHP Assistant</p>
              <p className="flex items-center gap-1.5 text-[11px] text-apple-muted">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-status-approved" />
                <span className="truncate">
                  {providerLabel || provider || 'AI'}
                  {model ? ' \u00b7 ' + model : ''}
                  {projectId ? ' \u00b7 PR ' + projectId : ' \u00b7 portfolio'}
                </span>
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setMessages([]);
                setInput('');
                inputRef.current?.focus();
              }}
              disabled={messages.length === 0}
              title="New chat"
              className="rounded-lg p-1.5 text-apple-muted transition hover:bg-apple-border/40 hover:text-apple-text disabled:opacity-30"
            >
              <RefreshIcon />
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              title="Close"
              className="rounded-lg p-1.5 text-apple-muted transition hover:bg-apple-border/40 hover:text-apple-text"
            >
              <CloseIcon />
            </button>
          </header>

          {/* Model switcher */}
          {(models.length > 0 || modelsLoaded) && (
            <div className="flex items-center gap-2 border-b border-apple-border/60 px-4 py-2">
              <label htmlFor="ai-model" className="text-[11px] font-medium uppercase tracking-wide text-apple-muted">
                Model
              </label>
              {models.length > 0 ? (
                <select
                  id="ai-model"
                  value={model}
                  onChange={(event) => selectModel(event.target.value)}
                  className="min-w-0 flex-1 truncate rounded-lg border border-apple-border/70 bg-white px-2 py-1.5 text-[12px] font-medium text-apple-text transition hover:border-apple-primary focus:border-apple-primary focus:outline-none focus:ring-1 focus:ring-apple-primary dark:bg-[#1f1f22]"
                >
                  {models.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.name}
                      {item.params ? ' (' + item.params + ')' : ''}
                      {item.size ? ' \u2013 ' + formatSize(item.size) : ''}
                      {item.source === 'suggested' ? ' (suggested)' : ''}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="flex-1 text-[12px] text-apple-muted">
                  {modelsLoaded ? 'No local models detected' : 'Checking\u2026'}
                </span>
              )}
              {activeModel?.params && (
                <span className="hidden shrink-0 rounded-full bg-apple-border/40 px-2 py-0.5 text-[10px] font-medium text-apple-muted sm:inline">
                  {activeModel.params}
                </span>
              )}
            </div>
          )}

          {/* Messages */}
          <div ref={scrollRef} className="chat-scroll flex-1 space-y-4 overflow-y-auto px-4 py-4">
            {thread.map((message, index) => {
              const question =
                [...thread.slice(0, index)]
                  .reverse()
                  .find((item) => item.role === 'user')?.text ?? '';
              return (
                <MessageRow
                  key={message.id}
                  message={message}
                  rating={ratings[message.id]}
                  onRate={(value) => rate(message, question, value)}
                  onCopy={() => {
                    if (typeof navigator !== 'undefined' && navigator.clipboard) {
                      void navigator.clipboard.writeText(message.text);
                    }
                  }}
                />
              );
            })}

            {busy && (
              <div className="animate-msg-in flex gap-2.5">
                <AssistantAvatar />
                <div className="flex items-center gap-1 rounded-2xl rounded-tl-md border border-apple-border/60 bg-apple-surface px-3.5 py-3">
                  <span className="chat-dot h-1.5 w-1.5 rounded-full bg-apple-muted" />
                  <span className="chat-dot h-1.5 w-1.5 rounded-full bg-apple-muted" style={{ animationDelay: '0.15s' }} />
                  <span className="chat-dot h-1.5 w-1.5 rounded-full bg-apple-muted" style={{ animationDelay: '0.3s' }} />
                </div>
              </div>
            )}

            {messages.length === 0 && !busy && (
              <div className="space-y-2 pt-1">
                <p className="text-[11px] font-medium uppercase tracking-wide text-apple-muted">Try asking</p>
                <div className="flex flex-wrap gap-1.5">
                  {prompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => void handleSend(prompt)}
                      className="rounded-full border border-apple-border/70 bg-white/70 px-2.5 py-1.5 text-[11.5px] text-apple-text transition hover:border-apple-primary hover:bg-apple-primary/[0.06] hover:text-apple-primary dark:bg-white/[0.04]"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Composer */}
          <div className="border-t border-apple-border/60 bg-white/60 px-3 py-3 dark:bg-white/[0.02]">
            <div className="flex items-end gap-2 rounded-xl border border-apple-border/70 bg-white px-2.5 py-2 shadow-sm transition focus-within:border-apple-primary focus-within:ring-1 focus-within:ring-apple-primary dark:bg-[#1f1f22]">
              <textarea
                ref={inputRef}
                value={input}
                rows={1}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    void handleSend();
                  }
                }}
                placeholder={projectId ? 'Ask about this project\u2026' : 'Ask about your projects\u2026'}
                className="chat-scroll max-h-[148px] min-h-[24px] flex-1 resize-none border-0 bg-transparent py-1 text-[13px] text-apple-text placeholder:text-apple-muted focus:outline-none"
              />
              <button
                type="button"
                onClick={() => void handleSend()}
                disabled={!input.trim() || busy}
                title="Send (Enter)"
                className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-[var(--kaust-primary)] to-[var(--kaust-blue)] text-white shadow-sm transition hover:opacity-90 disabled:opacity-35"
              >
                <SendIcon />
              </button>
            </div>
            <p className="mt-1.5 px-1 text-[10px] text-apple-muted">
              Enter to send &middot; Shift + Enter for a new line
              {models.length > 1 ? ' \u00b7 switch models above' : ''}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
