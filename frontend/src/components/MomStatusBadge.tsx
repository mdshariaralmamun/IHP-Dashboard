import type { MomStatus } from '@/lib/types';

const STATUS_CLASSES: Record<MomStatus, string> = {
  draft: 'bg-apple-surface text-apple-text ring-apple-muted',
  sent: 'bg-amber-100 text-amber-800 ring-amber-300',
  acknowledged: 'bg-green-100 text-green-800 ring-green-300',
  disputed: 'bg-red-100 text-red-800 ring-red-300',
};

const STATUS_LABELS: Record<MomStatus, string> = {
  draft: 'Draft',
  sent: 'Sent',
  acknowledged: 'Acknowledged',
  disputed: 'Disputed',
};

export default function MomStatusBadge({ status }: { status: MomStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_CLASSES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

