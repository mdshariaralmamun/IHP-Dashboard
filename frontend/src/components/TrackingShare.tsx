'use client';

import { useState } from 'react';
import { getToken } from '@/lib/api';

interface TrackingShareProps {
  /** The element to capture: the card that holds the progress bar. */
  target: React.RefObject<HTMLElement | null>;
  /** POST target that returns the .eml draft (project id or share token). */
  endpoint: string;
  prNumber: string;
  /** Pre-fills the recipient where it is known (the PI, in-app). */
  defaultTo?: string | null;
  /** Named in the drafted email, e.g. "Design". */
  stageLabel?: string | null;
  /** Only used to build the "open the live tracker" link inside the draft. */
  trackingToken?: string | null;
}

type Busy = 'copy' | 'save' | 'email' | null;

function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke late: Safari aborts the download if the URL dies too soon.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * Copy, save or email the live tracking bar as an image.
 *
 * The picture is captured from the DOM with html-to-image, so it always
 * matches what is on screen (current step highlight included) instead of
 * being redrawn from data and drifting from the real view.
 *
 * The email is a draft (.eml): the server has no mailbox and never sends, it
 * hands the message to the user's own Outlook, where the snapshot is already
 * attached and inlined. Nothing on the server can relay mail.
 */
export default function TrackingShare({
  target,
  endpoint,
  prNumber,
  defaultTo,
  stageLabel,
  trackingToken,
}: TrackingShareProps) {
  const [busy, setBusy] = useState<Busy>(null);
  const [to, setTo] = useState(defaultTo ?? '');
  const [note, setNote] = useState('');
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function capture(): Promise<Blob> {
    const node = target.current;
    if (!node) throw new Error('The tracker is not on screen yet.');
    const { toPng } = await import('html-to-image');
    const background = window.getComputedStyle(node).backgroundColor;
    const dataUrl = await toPng(node, {
      pixelRatio: 2, // retina-crisp when pasted into an email or chat
      cacheBust: true,
      backgroundColor:
        background && background !== 'rgba(0, 0, 0, 0)' ? background : '#ffffff',
      // Anything that must not appear in the picture can opt out.
      filter: (node) =>
        !(node instanceof HTMLElement && node.dataset.snapshotSkip === 'true'),
    });
    const blob = await (await fetch(dataUrl)).blob();
    if (!blob.size) throw new Error('The capture came back empty — try again.');
    return blob;
  }

  async function run(which: Exclude<Busy, null>, work: () => Promise<void>) {
    setBusy(which);
    setError(null);
    setStatus(null);
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  }

  const onCopy = () =>
    run('copy', async () => {
      const blob = await capture();
      if (!navigator.clipboard || typeof ClipboardItem === 'undefined') {
        throw new Error(
          'This browser cannot copy images — use "Save PNG" and attach the file.',
        );
      }
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      setStatus('Tracker image copied — paste it into an email, Teams or WhatsApp.');
    });

  const onSave = () =>
    run('save', async () => {
      download(await capture(), `tracker_${prNumber}.png`);
      setStatus('Tracker image saved.');
    });

  const onEmail = () =>
    run('email', async () => {
      if (!to.trim()) throw new Error('Add at least one recipient email address.');
      const blob = await capture();
      const fd = new FormData();
      fd.append('image', blob, `tracker_${prNumber}.png`);
      fd.append('to', to);
      fd.append('note', note);
      fd.append('stage_label', stageLabel ?? '');
      fd.append('base_url', window.location.origin);
      const headers: Record<string, string> = {};
      const token = getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(endpoint, { method: 'POST', body: fd, headers });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Could not build the email (${res.status}): ${text.slice(0, 180)}`);
      }
      download(await res.blob(), `Tracker_${prNumber}.eml`);
      setStatus('Email draft downloaded — open it to write the mail in Outlook. The snapshot is already attached and shown in the body.');
    });

  function openInMailApp() {
    const subject = `PR ${prNumber} - project tracker`;
    const body = [
      `PR ${prNumber} - live project tracker`,
      stageLabel ? `Current stage: ${stageLabel}` : '',
      trackingToken ? `${window.location.origin}/track/${trackingToken}` : '',
      '',
      'Tracking snapshot: use "Copy image" above, then paste it here.',
    ]
      .filter(Boolean)
      .join('\n');
    window.location.href =
      `mailto:${encodeURIComponent(to)}` +
      `?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }

  return (
    <div className="mt-4 rounded-lg border border-apple-border bg-apple-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-sm font-semibold text-apple-text">Share live tracking</span>
        <button
          type="button"
          onClick={() => void onCopy()}
          disabled={busy !== null}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
        >
          {busy === 'copy' ? 'Copying…' : 'Copy image'}
        </button>
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={busy !== null}
          className="rounded-md border border-apple-border px-3 py-1.5 text-xs font-semibold text-apple-text hover:bg-apple-surface/70 disabled:opacity-50"
        >
          {busy === 'save' ? 'Saving…' : 'Save PNG'}
        </button>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md border border-apple-border px-3 py-1.5 text-xs font-semibold text-apple-text hover:bg-apple-surface/70"
        >
          Email {open ? '▴' : '▾'}
        </button>
      </div>

      {open && (
        <div className="mt-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              type="text"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder="recipient@kaust.edu.sa"
              className="flex-1 rounded-md border border-apple-border bg-apple-surface px-3 py-1.5 text-sm text-apple-text placeholder:text-apple-muted focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Optional note to include"
              className="flex-1 rounded-md border border-apple-border bg-apple-surface px-3 py-1.5 text-sm text-apple-text placeholder:text-apple-muted focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
            <button
              type="button"
              onClick={() => void onEmail()}
              disabled={busy !== null || !to.trim()}
              className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              {busy === 'email' ? 'Preparing…' : 'Email draft'}
            </button>
          </div>
          <p className="mt-2 text-[11px] text-apple-muted">
            Downloads an Outlook draft with the snapshot attached and shown in the body — you
            send it from your own account.{' '}
            <button
              type="button"
              onClick={openInMailApp}
              className="underline hover:text-apple-text"
            >
              or open your mail app
            </button>
          </p>
        </div>
      )}

      {status && (
        <p className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs text-emerald-800">
          {status}
        </p>
      )}
      {error && (
        <p className="mt-2 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
