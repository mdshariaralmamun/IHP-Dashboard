'use client';

import { useState } from 'react';

type OverrideMode = 'pi' | 'location' | 'other';

interface OverrideDialogProps {
  /** Current auto-populated value from O&M sheet or AI */
  currentValue: string;
  /** Field name for display/logging */
  fieldName: string;
  /** Whether the field is currently being edited */
  isEditing: boolean;
  /** Callback when user wants to edit */
  onStartEdit: () => void;
  /** Callback when user confirms the corrected value */
  onConfirm: (correctedValue: string, justification: string) => void;
  /** Callback when user cancels editing */
  onCancel: () => void;
  /** Callback when user wants to auto-populate again */
  onReauto: () => void;
  /** Human-readable label for the field */
  label: string;
}

export default function OverrideDialog({
  currentValue,
  fieldName,
  isEditing,
  onStartEdit,
  onConfirm,
  onCancel,
  onReauto,
  label,
}: OverrideDialogProps) {
  const [justification, setJustification] = useState('');

  function handleConfirm() {
    const trimmed = justification.trim();
    if (!trimmed) {
      // Show error - justification required
      return;
    }
    onConfirm(currentValue, trimmed);
  }

  return null; // Rendering handled by caller
}