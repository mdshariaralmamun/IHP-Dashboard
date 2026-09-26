'use client';

import { useState } from 'react';

type OverrideFieldMode = 'pi' | 'location' | 'other';

interface OverrideFieldProps {
  /** The current value displayed (auto-populated or manually entered) */
  value: string;
  /** Human-readable label for the field */
  label: string;
  /** Whether the field comes from O&M sheet auto-population */
  fromOms: boolean;
  /** Callback when user starts editing (shows justification field + confirm) */
  onStartEdit: (correctedValue: string, justification: string) => void;
  /** Callback when user cancels editing */
  onCancel: () => void;
  /** Callback when user wants to re-auto-populate from source */
  onReauto: () => void;
  /** Additional metadata for logging */
  fieldKey: string;
}

function JustificationInput({ justification, onChange }: { justification: string; onChange: (v: string) => void }) {
  return (
    <div className="mt-2">
      <label className="block text-sm font-medium text-apple-text mb-1">
        Justification — why this value differs from the auto-populated source
      </label>
      <textarea
        rows={3}
        value={justification}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-apple-border px-3 py-2 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary placeholder-apple-muted/60 dark:placeholder-apple-muted/40"
      />
    </div>
  );
}

export default function OverrideField({
  value,
  label,
  fromOms,
  onStartEdit,
  onCancel,
  onReauto,
  fieldKey,
}: OverrideFieldProps) {
  const [editing, setEditing] = useState(false);
  const [justification, setJustification] = useState('');

  function handleStartEdit() {
    setEditing(true);
    setJustification('');
  }

  function handleCancel() {
    setEditing(false);
    setJustification('');
    onCancel();
  }

  function handleConfirm(correctedValue: string) {
    const jet = correctedValue.trim();
    if (!jet) return; // Justification required
    setEditing(false);
    setJustification('');
    onStartEdit(correctedValue, jet);
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-apple-text">{label}:&nbsp;</span>
        <span className={`font-medium text-apple-text ${
          fromOms ? 'text-orange-600' : 'text-apple-text'
        }`}>
          {value || '—'}
        </span>
      </div>

      {editing ? (
        <div className="mt-2">
          <JustificationInput
            justification={justification}
            onChange={setJustification}
          />
          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={() => handleConfirm(value)}
              disabled={!justification.trim()}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-apple-surface disabled:opacity-50"
            >
              Confirm
            </button>
            <button
              onClick={handleCancel}
              className="rounded-md border border-apple-border px-3 py-1.5 text-sm font-medium text-apple-text hover:bg-apple-surface"
            >
              Cancel
            </button>
            {fromOms && (
              <button
                onClick={() => onReauto()}
                className="rounded-md border border-apple-border px-3 py-1.5 text-xs font-medium text-apple-muted hover:bg-apple-surface/50 disabled:opacity-50"
              >
                Re-auto
            </button>
            )}
          </div>
        </div>
      ) : (
        <button
          onClick={handleStartEdit}
          className="rounded-md border border-apple-border px-3 py-1.5 text-sm font-medium text-apple-text hover:bg-apple-surface/50 transition-colors"
        >
          {fromOms ? 'Edit' : 'Details'}
        </button>
      )}
    </div>
  );
}