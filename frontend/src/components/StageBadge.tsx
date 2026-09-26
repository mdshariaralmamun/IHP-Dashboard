const STAGE_CLASSES: Record<string, string> = {
  INTAKE: 'bg-gray-100 text-gray-700 ring-gray-300',
  MOM_SENT: 'bg-amber-100 text-amber-800 ring-amber-300',
  MOM_CONFIRMED: 'bg-green-100 text-green-800 ring-green-300',
  PUNCH_LIST: 'bg-orange-100 text-orange-800 ring-orange-300',
};

const DEFAULT_CLASSES = 'bg-apple-surface text-apple-text ring-apple-muted';

export default function StageBadge({ stage }: { stage: string }) {
  const classes = STAGE_CLASSES[stage] ?? DEFAULT_CLASSES;
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${classes}`}
    >
      {stage.replace(/_/g, ' ')}
    </span>
  );
}

