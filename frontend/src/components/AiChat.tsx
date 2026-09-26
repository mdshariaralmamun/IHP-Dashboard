'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { askAi } from '@/lib/api';
import { useUser } from '@/lib/useUser';

interface Message {
  role: 'user' | 'assistant';
  text: string;
}

const WELCOME: Message = {
  role: 'assistant',
  text: 'Ask me anything about your projects. I answer from the knowledge base and cite my sources.',
};

export default function AiChat() {
  const pathname = usePathname();
  const { user } = useUser();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const projectMatch = /^\/projects\/(\d+)/.exec(pathname ?? '');
  const projectId = projectMatch ? Number(projectMatch[1]) : undefined;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, open]);

  async function handleSend() {
    const question = input.trim();
    if (!question || busy) return;
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', text: question }]);
    setBusy(true);
    try {
      const res = await askAi(question, projectId);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: res.answer },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: `Error: ${err instanceof Error ? err.message : 'request failed'}`,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight });
    }
  }, [messages]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-4 right-4 z-50 rounded-lg bg-apple-surface px-3 py-2 text-sm font-medium transition-colors hover:bg-apple-border/50"
        title="AI assistant"
      >
        AI
      </button>

      {open && (
        <div className="fixed bottom-24 right-4 z-50 w-80 rounded-lg border border-apple-border bg-white dark:bg-[#1c1c1e] shadow-xl shadow-black/10 dark:shadow-black/30 flex flex-col">
          <div className="flex items-center justify-between border-b border-apple-border/50 px-4 py-3">
            <span className="text-sm font-semibold text-apple-text">IHP Assistant</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-apple-muted hover:text-white"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {messages.map((msg, i) => (
              <div key={i} className={msg.role === 'user' ? 'text-right' : 'text-left'}>
                <div
                  className={`inline-block max-w-[85%] rounded-lg px-3 py-2 text-left text-sm ${
                    msg.role === 'user'
                      ? 'bg-apple-primary text-white'
                      : 'bg-apple-surface text-apple-text'
                  }`}
                >
                  <p className="whitespace-pre-wrap">{msg.text}</p>
                </div>
              </div>
            ))}

            {busy && (
              <p className="text-sm text-apple-muted">Thinking…</p>
            )}
          </div>

          <div className="px-4 py-3 border-t border-apple-border/50">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void handleSend();
                }}
                placeholder="Ask a question…"
                className="flex-1 rounded-md border border-apple-border bg-white dark:bg-[#1c1c1e] text-gray-900 dark:text-gray-100 px-3 py-2 text-sm placeholder:text-gray-400 dark:placeholder:text-gray-500 focus:border-apple-primary focus:outline-none focus:ring-1 focus:ring-apple-primary"
              />
              <button
                type="button"
                onClick={() => void handleSend()}
                disabled={!input.trim()}
                className="rounded-md bg-apple-primary px-3 py-2 text-sm font-medium text-white hover:bg-apple-surface/90 disabled:opacity-50"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}