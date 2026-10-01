/**
 * The workflow stages, in lifecycle order, with human labels and terminality.
 *
 * One list for the whole app: the stage dropdowns, the register's sort order
 * and the stage badge all read from here, so adding a stage shows up
 * everywhere at once instead of only in whichever arrays someone remembered.
 */

export interface StageOption {
  id: string;
  label: string;
  /** Finished — nothing flows out of it. */
  terminal?: boolean;
}

export const STAGES: StageOption[] = [
  { id: 'INTAKE', label: 'Intake' },
  { id: 'MOM_SENT', label: 'MOM Sent' },
  { id: 'MOM_CONFIRMED', label: 'MOM Confirmed' },
  { id: 'DISPOSITION', label: 'Disposition' },
  { id: 'EAR_DRAFT', label: 'EAR Draft' },
  { id: 'EAR_REVIEW', label: 'EAR Review' },
  { id: 'EAR_APPROVED', label: 'EAR Approved' },
  { id: 'SOW_DRAFT', label: 'SOW Draft' },
  { id: 'SOW_REVIEW', label: 'SOW Review' },
  { id: 'SOW_APPROVED', label: 'SOW Approved' },
  { id: 'MTO_DRAFT', label: 'MTO Draft' },
  { id: 'MTO_APPROVED', label: 'MTO Approved' },
  { id: 'PROCUREMENT', label: 'Procurement' },
  { id: 'WORK_PERMIT', label: 'Work Permit' },
  { id: 'CONSTRUCTION', label: 'Construction' },
  { id: 'CLOSEOUT', label: 'Closeout' },
  { id: 'PUNCH_LIST', label: 'Punch List', terminal: true },
  { id: 'ICR_DONE', label: 'ICR Done', terminal: true },
  { id: 'CANCELLED', label: 'Cancelled', terminal: true },
];

export const STAGE_IDS: string[] = STAGES.map((s) => s.id);

/** Display name for a stage id ("EAR_REVIEW" -> "EAR Review"). */
export function stageName(id: string | null | undefined): string {
  if (!id) return '—';
  return STAGES.find((s) => s.id === id)?.label ?? id.replace(/_/g, ' ');
}
