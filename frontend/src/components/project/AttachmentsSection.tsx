'use client';

import { useRef, useState } from 'react';
import type { DragEvent } from 'react';
import ErrorBox from '@/components/ErrorBox';
import { deleteAttachment, downloadAttachment, uploadAttachments } from '@/lib/api';
import { formatBytes, formatDate } from '@/lib/format';
import type { Attachment } from '@/lib/types';

export default function AttachmentsSection({
  projectId,
  attachments,
  canUpload,
  canDelete,
  onChanged,
}: {
  projectId: number;
  attachments: Attachment[];
  canUpload: boolean;
  canDelete: boolean;
  onChanged: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(fileList: FileList | null) {
    const files = fileList ? Array.from(fileList) : [];
    if (files.length === 0 || uploading) return;
    setError(null);
    setUploading(true);
    try {
      await uploadAttachments(projectId, files);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragOver(false);
    void handleFiles(event.dataTransfer.files);
  }

  async function handleDownload(attachment: Attachment) {
    if (downloadingId !== null) return;
    setError(null);
    setDownloadingId(attachment.id);
    try {
      await downloadAttachment(projectId, attachment.id, attachment.filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed.');
    } finally {
      setDownloadingId(null);
    }
  }

  async function handleDelete(attachment: Attachment) {
    if (deletingId !== null) return;
    if (!window.confirm(`Delete "${attachment.filename}"?`)) return;
    setError(null);
    setDeletingId(attachment.id);
    try {
      await deleteAttachment(projectId, attachment.id);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed.');
    } finally {
      setDeletingId(null);
    }
  }

  const dropZoneClass = dragOver
    ? 'border-primary bg-apple-surface'
    : 'border-apple-border bg-apple-surface/50 hover:border-primary';

  return (
    <section className="rounded-lg border border-apple-border bg-apple-surface p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-apple-muted">
          Attachments
        </h2>
        {attachments.length > 0 && (
          <span className="text-xs text-apple-muted">{attachments.length} file(s)</span>
        )}
      </div>

      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {canUpload && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`mb-4 flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors ${dropZoneClass}`}
        >
          <p className="text-sm text-apple-muted">
            {uploading ? 'Uploading…' : 'Drag and drop files here, or'}
          </p>
          {!uploading && (
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="mt-2 rounded-md border border-apple-border bg-apple-surface px-3 py-1.5 text-sm font-medium text-apple-text hover:bg-apple-surface"
            >
              Browse files
            </button>
          )}
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => void handleFiles(e.target.files)}
          />
        </div>
      )}

      {attachments.length === 0 ? (
        <p className="text-sm text-apple-muted">No attachments uploaded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-apple-border text-sm">
            <thead>
              <tr>
                {['Filename', 'Size', 'Version', 'Uploaded', ''].map((heading) => (
                  <th
                    key={heading}
                    className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-apple-muted"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-apple-border">
              {attachments.map((attachment) => (
                <tr key={attachment.id}>
                  <td className="max-w-xs truncate px-3 py-2 font-medium text-apple-text">
                    {attachment.filename}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-apple-muted">
                    {formatBytes(attachment.size_bytes)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-apple-muted">
                    v{attachment.version}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-apple-muted">
                    {formatDate(attachment.created_at)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        type="button"
                        onClick={() => void handleDownload(attachment)}
                        disabled={downloadingId !== null}
                        className="text-sm font-medium text-apple-text underline underline-offset-2 hover:text-apple-text disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {downloadingId === attachment.id ? 'Downloading…' : 'Download'}
                      </button>
                      {canDelete && (
                        <button
                          type="button"
                          onClick={() => void handleDelete(attachment)}
                          disabled={deletingId !== null}
                          className="text-sm font-medium text-red-600 underline underline-offset-2 hover:text-red-800 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {deletingId === attachment.id ? 'Deleting…' : 'Delete'}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

