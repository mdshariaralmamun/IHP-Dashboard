'use client';

import { VisualCard } from '@/components/powerbi/PowerBI';

export type StepState = 'done' | 'active' | 'future';

export interface TrackStep {
  label: string;
  date?: string | null;
  state: StepState;
}

/** The ICR delivery sequence, in the order the work actually happens. */
export const ICR_STEPS: string[] = [
  'Intake',
  'MOM',
  'MTO & PTW',
  'Quotation Request',
  'Quotation Receive',
  'Quotation Approved',
  'PO Raise By PI',
  'PO Approved',
  'Materials Received',
  'Schedule Construction',
  'Project Finished',
];

const COLOURS: Record<StepState, { bg: string; fg: string }> = {
  done: { bg: '#2e7d32', fg: '#ffffff' },
  active: { bg: '#1565c0', fg: '#ffffff' },
  future: { bg: '#e5e7eb', fg: '#374151' },
};

/**
 * The horizontal chevron tracker.
 *
 * Each stage is an arrow pointing right, flush against the next one: green
 * behind us, blue where we are, grey ahead, with the date under the stages
 * that have happened. It scrolls sideways because eleven of them never fit.
 */
export default function LiveTrackingStepper({
  steps,
  title = 'Live Tracking',
}: {
  steps: TrackStep[];
  title?: string;
}) {
  return (
    <VisualCard title={title} subtitle="click-free overview of where the PR stands">
      <div className="overflow-x-auto pb-2">
        <div className="flex min-w-max items-stretch">
          {steps.map((step, index) => {
            const colour = COLOURS[step.state];
            return (
              <div
                key={step.label + index}
                className="relative flex h-16 w-[150px] flex-col items-center justify-center text-center"
                style={{
                  backgroundColor: colour.bg,
                  color: colour.fg,
                  clipPath:
                    index === 0
                      ? 'polygon(0 0, calc(100% - 16px) 0, 100% 50%, calc(100% - 16px) 100%, 0 100%)'
                      : 'polygon(0 0, calc(100% - 16px) 0, 100% 50%, calc(100% - 16px) 100%, 0 100%, 16px 50%)',
                  marginLeft: index === 0 ? 0 : -16,
                  zIndex: steps.length - index,
                }}
                title={step.label}
              >
                <span className="px-3 text-[11px] font-semibold leading-tight">
                  {step.label}
                </span>
                {step.state !== 'future' && (
                  <span className="mt-0.5 text-[10px] opacity-90">{step.date ?? '—'}</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </VisualCard>
  );
}

/**
 * Where an ICR project stands on that sequence.
 *
 * Read from what the app actually records: the MOM, the ICR hand-off
 * milestones and the project stage. Everything before the furthest signal is
 * complete, that step is current, the rest are ahead - so the tracker can
 * never show a later stage as done than the records support.
 */
export function icrSteps(input: {
  hasMom: boolean;
  milestones: string[];
  stage: string;
  date?: string | null;
}): TrackStep[] {
  const milestones = new Set(input.milestones.map((m) => m.toLowerCase()));
  const stage = (input.stage || '').toUpperCase();
  const reached = {
    intake: true,
    mom: input.hasMom || !['INTAKE'].includes(stage),
    mto: milestones.has('mto_to_project_control') || ['MTO_APPROVED', 'ICR_DONE'].includes(stage),
    quotation_request: milestones.has('materials_ordered'),
    quotation_receive: milestones.has('materials_received'),
    quotation_approved: milestones.has('materials_received'),
    po_raise: milestones.has('materials_ordered'),
    po_approved: milestones.has('materials_ordered'),
    materials: milestones.has('materials_received'),
    schedule: milestones.has('eat_install_scheduled') || milestones.has('eat_installed'),
    finished: milestones.has('closed') || stage === 'ICR_DONE',
  };
  const flags = Object.values(reached);
  const doneCount = flags.filter(Boolean).length;
  const today = input.date ?? new Date().toISOString().slice(0, 10);
  return ICR_STEPS.map((label, index) => ({
    label,
    state: index < doneCount ? 'done' : index === doneCount ? 'active' : 'future',
    date: index < doneCount ? today : index === doneCount ? today : null,
  }));
}
