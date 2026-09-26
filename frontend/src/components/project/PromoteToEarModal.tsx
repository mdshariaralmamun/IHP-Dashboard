'use client';

import { useState } from 'react';
import { promoteToEar } from '@/lib/api';

interface PromoteToEarModalProps {
  projectId: number;
  onClose: () => void;
  onSuccess: () => void;
}

export default function PromoteToEarModal({ projectId, onClose, onSuccess }: PromoteToEarModalProps) {
  const [newPrNumber, setNewPrNumber] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPrNumber.trim()) {
      setError('New PR number is required.');
      return;
    }
    
    setLoading(true);
    setError('');
    
    try {
      await promoteToEar(projectId, newPrNumber.trim());
      onSuccess();
    } catch (err: any) {
      setError(err.message || 'Failed to promote project to EAR.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-primary/50 p-4">
      <div className="bg-apple-surface rounded-xl shadow-xl w-full max-w-md overflow-hidden">
        <div className="border-b border-apple-border bg-apple-surface/50 px-6 py-4">
          <h3 className="text-lg font-bold text-apple-text">Promote to EAR</h3>
          <p className="text-sm text-apple-muted mt-1">
            This will assign the current PR number to the EAR, and assign a new PR number for construction tracking.
          </p>
        </div>
        
        <form onSubmit={handleSubmit} className="p-6">
          {error && (
            <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-600">
              {error}
            </div>
          )}
          
          <div className="mb-6">
            <label htmlFor="new_pr_number" className="block text-sm font-semibold text-apple-text mb-2">
              New PR Number (Construction)
            </label>
            <input
              id="new_pr_number"
              type="text"
              value={newPrNumber}
              onChange={e => setNewPrNumber(e.target.value)}
              className="w-full rounded-md border border-apple-border px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="e.g. PR-2026-XYZ"
              disabled={loading}
              autoFocus
            />
          </div>
          
          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="rounded-md border border-apple-border px-4 py-2 text-sm font-medium text-apple-muted hover:bg-apple-surface/50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? 'Promoting...' : 'Promote'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

