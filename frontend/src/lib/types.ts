export type Role = string;

// ---------------------------------------------------------------------------
// AI / Knowledge-base types
// ---------------------------------------------------------------------------

export interface AiSource {
  filename: string;
  snippet: string;
}

export interface AiAnswer {
  answer: string;
  /** live = exact database answer, llm = model answer, extractive = fallback. */
  mode: 'llm' | 'extractive' | 'live';
  sources: AiSource[];
}

export interface CorpusDoc {
  id: number;
  filename: string;
  source: string;
  project_id: number | null;
  chunk_count: number;
  created_at: string;
}


/** Standard roles (admins can also type any custom role in the user form). */
export const KNOWN_ROLES = ['admin', 'trade', 'planning', 'construction_manager', 'team_member'];

export interface User {
  id: number;
  username: string;
  full_name: string;
  email: string;
  role: Role;
  trade: string | null;
  title?: string;
  is_active?: boolean;
  /** Effective capabilities (role defaults or admin override), from /api/auth/me. */
  permissions?: string[];
}

export interface CreateUserInput {
  username: string;
  full_name: string;
  email: string;
  password: string;
  role: Role;
  trade?: string | null;
  title?: string;
  /** null/omitted = role defaults; a list = exact override. */
  permissions?: string[] | null;
}

export interface UpdateUserInput {
  full_name?: string;
  email?: string;
  title?: string;
  role?: Role;
  trade?: string | null;
  password?: string;
  is_active?: boolean;
  permissions?: string[] | null;
}

// ---------- capabilities (must match the backend) ----------

// ---------- capabilities (must match the backend) ----------

export const ALL_PERMISSIONS = [
  'projects.create',
  'projects.edit',
  'projects.delete',
  'attachments.upload',
  'attachments.delete',
  'mom.manage',
  'mom.agenda',
  'disposition.manage',
  'ear.input',
  'ear.manage',
  'sow.manage',
  'boq.manage',
  'permit.manage',
  'construction.manage',
  'closeout.manage',
  'users.manage',
] as const;

export type Permission = (typeof ALL_PERMISSIONS)[number];

export const ROLE_DEFAULT_PERMISSIONS: Record<Role, string[]> = {
  admin: [...ALL_PERMISSIONS],
  trade: ['mom.agenda', 'ear.input', 'boq.manage'],
  planning: ['disposition.manage', 'ear.manage', 'sow.manage', 'boq.manage', 'closeout.manage'],
  construction_manager: ['permit.manage', 'construction.manage', 'boq.manage', 'closeout.manage'],
  team_member: [],
};

export const PERMISSION_GROUPS: { label: string; caps: { value: Permission; label: string }[] }[] = [
  {
    label: 'Projects & Intake',
    caps: [
      { value: 'projects.create', label: 'Create PRs (incl. PR-form upload)' },
      { value: 'projects.edit', label: 'Edit project metadata' },
      { value: 'projects.delete', label: 'Delete projects' },
    ],
  },
  {
    label: 'Attachments',
    caps: [
      { value: 'attachments.upload', label: 'Upload attachments' },
      { value: 'attachments.delete', label: 'Delete attachments' },
    ],
  },
  {
    label: 'Stage 1: MOM',
    caps: [
      { value: 'mom.manage', label: 'Generate MOM, edit meeting details, set status' },
      { value: 'mom.agenda', label: 'Add / edit / delete agenda items (own trade)' },
    ],
  },
  {
    label: 'Stage 2 & 3: Disposition & EAR',
    caps: [
      { value: 'disposition.manage', label: 'Set PR disposition (ICR vs Project)' },
      { value: 'ear.input', label: 'Submit discipline proposal & conflict notes (own trade)' },
      { value: 'ear.manage', label: 'Manage EAR review, budget & docgen' },
    ],
  },
  {
    label: 'Stage 4: SOW & BOQ/MTO',
    caps: [
      { value: 'sow.manage', label: 'Manage SOW revisions & Procore comments' },
      { value: 'boq.manage', label: 'Add / edit / export BOQ line items' },
    ],
  },
  {
    label: 'Stages 5 & 6: Construction & Permits',
    caps: [
      { value: 'permit.manage', label: 'Generate & approve Work Permits (WCH/WCF)' },
      { value: 'construction.manage', label: 'Manage construction team & materials lead-time' },
    ],
  },
  {
    label: 'Stage 7: Closeout & Handover',
    caps: [
      { value: 'closeout.manage', label: 'Manage T&C checklist, defect punch lists, warranties & client signoff' },
    ],
  },
  {
    label: 'Administration',
    caps: [{ value: 'users.manage', label: 'Manage users and capability assignments' }],
  },
];

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Master / Admin',
  trade: 'Trade user',
  planning: 'Planning',
  construction_manager: 'Construction Manager',
  team_member: 'Team member',
};

/** Display label for any role code, including custom free-text roles. */
export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export const TRADE_OPTIONS: { value: string; label: string }[] = [
  { value: 'civil_arch', label: 'Civil / Architectural' },
  { value: 'electrical', label: 'Electrical (Power / Lighting / Data)' },
  { value: 'low_current', label: 'Low Current (Data / TGM / Control / VESDA)' },
  { value: 'plumbing', label: 'Plumbing (Piping / Gas / UHP Gas)' },
  { value: 'fire_protection', label: 'Fire Protection' },
  { value: 'hvac', label: 'HVAC (incl. Chilled Water)' },
];

export interface ProjectSummary {
  id: number;
  pr_number: string;
  ear_number: string | null;
  tracking_token: string | null;
  title: string;
  pi_name: string | null;
  location: string | null;
  funding_source: string | null;
  stage: string;
  disposition: string | null;
  created_at: string;
  // Tracker-derived fields (present when the project was imported from
  // the planner xlsx; null/[] for manual or demo projects).
  project_type?: string | null;
  trades?: string[];
  division?: string | null;
  priority?: string | null;
  completion_pct?: number | null;
  source?: 'planner' | 'om' | 'manual' | 'demo' | null;
  /** Raw IHP planner Bucket (EAR, DESIGN, PTW/WICF, CONSTRUCTION, WCH, WCC...). */
  planner_bucket?: string | null;
  // ---- Notes/Labels analysis (backend services/planner_status.py) ----
  /** CURRENT status read from the LAST milestone in the Planner Notes log. */
  latest_status?: string | null;
  /** ISO date that status was reached. */
  latest_status_date?: string | null;
  /** Chronological milestone chain, oldest first. */
  status_timeline?: string[];
  /** Label flags: ON HOLD, FAST TRACK, RFI DONE, MTO, ... */
  flags?: string[];
  /** Checklist completion as "3/6". */
  checklist?: string | null;
  /** Lifecycle division: "EAR" | "Design" | "Construction" | "Close-up". */
  phase?: string | null;
  /** EAR-only funnel step read from the Planner notes. */
  ear_substatus?: string | null;
  /** Date the EAR was approved (from the "EAR approved on ..." note). */
  ear_approved_date?: string | null;
  /** Date of the Planner snapshot this row came from. */
  planner_sync_date?: string | null;
  /**
   * True when the row is present in the NEWEST Planner snapshot. Stale rows
   * (PRs removed from the tracker, e.g. moved to the O&M equipment branch)
   * are excluded from the live division counts.
   */
  in_latest_planner?: boolean;
}

/**
 * The four lifecycle divisions shown on the dashboard.
 *
 *   EAR          -> EAR (assessment / project summary)
 *   Design       -> Design + Procore + MTO
 *   Construction -> PTW/WICF + Construction + Shutdown + QA
 *   Close-up     -> WCC + WCH + As-Built / Technical Library
 *
 * Design and Construction are separate divisions on purpose: design work
 * (SOW/BOQ/MTO) is a different stage and team from field execution.
 */
export const PHASES: { key: string; label: string; hint: string; buckets: string[] }[] = [
  {
    key: 'EAR',
    label: 'EAR',
    hint: 'Assessment & project summary (EAR)',
    buckets: ['EAR', 'PROJECT ASSESSMENT', 'ASSESSMENT'],
  },
  {
    key: 'Design',
    label: 'Design',
    hint: 'Detail design, Procore & MTO',
    buckets: ['DESIGN', 'PROCORE', 'MTO'],
  },
  {
    key: 'Construction',
    label: 'Construction',
    hint: 'PTW/WICF, Construction, Shutdown & QA',
    buckets: ['PTW/WICF', 'PTW', 'WICF', 'CONSTRUCTION', 'SHUTDOWN', 'QUALITY INSPECTION'],
  },
  {
    key: 'Close-up',
    label: 'Close-up',
    hint: 'WCC, WCH, As-Built & Technical Library',
    buckets: ['WCC', 'WCH', 'AS-BUILT', 'TECHNICAL LIBRARY'],
  },
];

/**
 * EAR funnel steps, in the order they matter on the dashboard: blocked work
 * first, then the furthest milestones, then the waiting queue.
 */
/**
 * EAR funnel, in attention order. A project is cancelled when ASEPC does not
 * approve it; ASEPC-type projects sit in `asepc_pending` between EAR approval
 * and the start of construction.
 */
export const EAR_STATUS_ORDER: string[] = [
  'cancelled',
  'on_hold',
  'asepc_pending',
  'ear_approved',
  'ear_issued',
  'wbs_request',
  'awaiting_summary',
  'site_visit',
  'asepc_approved',
  'in_progress',
];

export const EAR_STATUS_LABELS: Record<string, string> = {
  cancelled: 'Cancelled (ASEPC not approved)',
  on_hold: 'On Hold',
  asepc_pending: 'Waiting for ASEPC Approval',
  ear_approved: 'EAR Approved',
  ear_issued: 'EAR Issued',
  wbs_request: 'WBS / Cost Center Request',
  awaiting_summary: 'Awaiting Summary Package',
  site_visit: 'Site Visit Done',
  asepc_approved: 'ASEPC Approved (to construction)',
  in_progress: 'In Progress',
};

/** Colour coding for the Planner priority column. */
export const PRIORITY_STYLES: Record<string, string> = {
  urgent: 'bg-red-100 text-red-800 ring-red-300',
  important: 'bg-orange-100 text-orange-800 ring-orange-300',
  high: 'bg-orange-100 text-orange-800 ring-orange-300',
  medium: 'bg-blue-100 text-blue-800 ring-blue-300',
  normal: 'bg-blue-100 text-blue-800 ring-blue-300',
  low: 'bg-gray-100 text-gray-700 ring-gray-300',
};

export interface ProjectFilters {
  stage?: string;
  disposition?: string;
  search?: string;
  bucket?: string;
}

export interface ProjectDetail extends ProjectSummary {
  description?: string | null;
  pi_email?: string | null;
  attachments: Attachment[];
  mom: MomRecord | null;
  ear?: EarRecord | null;
  sow_records?: SowRecord[];
  boq_items?: BoqItem[];
  construction?: ConstructionOut | null;
  closeout?: CloseoutRecord | null;
  icr_handoffs?: IcrHandoff[];
}

export interface CreateProjectInput {
  pr_number: string;
  title: string;
  description?: string;
  location?: string;
  pi_name?: string;
  pi_email?: string;
  funding_source?: string;
}

export interface Attachment {
  id: number;
  stage: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  version: number;
  created_at: string;
}

export type MomStatus = 'draft' | 'sent' | 'acknowledged' | 'disputed';

export type MomStatusUpdate = 'sent' | 'acknowledged' | 'disputed';

export interface MomAttendee {
  name: string;
  title: string;
  email: string;
}

export interface MomAgendaItem {
  scope: string;
  action: string;
  etc: string;
  trade?: string | null;
}

export interface MomDetails {
  meeting_title?: string | null;
  meeting_location?: string | null;
  meeting_number?: string | null;
  meeting_date?: string | null;
  meeting_time?: string | null;
  attendees?: MomAttendee[];
  agenda?: MomAgendaItem[];
}

export interface MomRecord {
  id: number;
  version: number;
  status: MomStatus;
  email_subject: string;
  email_body: string;
  note: string | null;
  details?: MomDetails | null;
  updated_at: string;
}

export interface PrFormParseResult {
  project: Partial<CreateProjectInput>;
  fields: Record<string, string | string[]>;
  carried_files?: { filename: string; content_base64: string }[];
}

// ---------- Stage 3: EAR Models ----------

export interface EarTradeInput {
  id: number;
  ear_id: number;
  trade: string;
  proposal: string;
  comments: string;
  missing_info: string;
  has_conflict: boolean;
  conflict_reason_code: string | null;
  conflict_resolution_note: string | null;
  estimated_materials_cost: number;
  estimated_manpower_cost: number;
  updated_by_id: number;
  updated_at: string;
}

export interface EarAiFinding {
  trade: string;
  type: 'conflict' | 'omission' | 'code_reference' | 'suggestion';
  description: string;
  citation?: string;
  resolution?: string;
}

export interface EarRecord {
  id: number;
  project_id: number;
  version: number;
  status: 'draft' | 'under_review' | 'approved';
  summary: string;
  recommendations: string;
  docx_filename: string | null;
  pdf_filename: string | null;
  budget_data: {
    rates?: Record<string, number>;
    trade_budgets?: Record<string, { materials: number; manpower: number }>;
    billing_type?: 'pi_baseline' | 'asepc_ihp';
  } | null;
  ai_review_findings: EarAiFinding[] | null;
  trade_inputs: EarTradeInput[];
  updated_by_id: number;
  updated_at: string;
}

// ---------- Stage 4: SOW & BOQ/MTO Models ----------

export interface SowRecord {
  id: number;
  project_id: number;
  revision_name: string;
  status: 'draft' | 'in_review' | 'approved';
  scope_text: string;
  trade_sections?: Record<string, unknown> | null;
  procore_comments: string | null;
  docx_filename: string | null;
  pdf_filename: string | null;
  created_by_id: number;
  created_at: string;
  updated_at: string;
}

export interface BoqItem {
  id: number;
  project_id: number;
  mto_kind: 'design' | 'construction';
  trade: string;
  item_code: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total_rate: number;
  material_spec: string | null;
  supplier_lead_time_days: number | null;
  delivery_status: 'pending' | 'ordered' | 'in_transit' | 'delivered' | 'cancelled';
  created_at: string;
  updated_at: string;
}

// ---------- Stage 5 & 6: Permits & Construction Models ----------

export interface WorkPermit {
  id: number;
  project_id: number;
  permit_type: 'WCH' | 'WCF' | string;
  permit_number: string;
  location: string;
  contractor_name: string;
  valid_from: string | null;
  valid_to: string | null;
  safety_measures: Record<string, boolean> | null;
  status: 'draft' | 'submitted' | 'approved' | 'active' | 'closed';
  approved_by_id: number | null;
  created_at: string;
}

export interface ConstructionTeamMember {
  id: number;
  project_id: number;
  name: string;
  mobile: string;
  email: string;
  role_or_trade: string;
  created_at: string;
}

export interface MaterialTrackingItem {
  id: number;
  project_id: number;
  trade: string;
  item_description: string;
  po_number: string | null;
  contractor_or_supplier: string | null;
  lead_time_days: number;
  supply_type: 'supply_only' | 'supply_and_install';
  expected_delivery: string | null;
  actual_delivery: string | null;
  installer_arrival_date: string | null;
  status: 'order_pending' | 'order_placed' | 'in_transit' | 'delivered' | 'installed';
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConstructionDashboardKpis {
  total_projects: number;
  active_construction_projects: number;
  total_materials_tracked: number;
  materials_delivered: number;
  active_work_permits: number;
  delivery_rate: number;
}

export interface ConstructionProjectSummary {
  id: number;
  pr_number: string;
  title: string;
  stage: string;
  location: string | null;
  pi_name: string | null;
  disposition: string | null;
  created_at: string;
  permits_count: number;
  active_permits_count: number;
  materials_count: number;
  materials_delivered_count: number;
  team_count: number;
}

export interface MaterialTrackingWithProject extends MaterialTrackingItem {
  project_pr_number: string;
  project_title: string;
}

export interface WorkPermitWithProject extends WorkPermit {
  project_pr_number: string;
  project_title: string;
}

// ---------- AI assistant ----------

/** One model the configured AI provider can run (local Ollama: pulled models). */
export interface AiModel {
  name: string;
  active: boolean;
  size: number | null;
  family?: string | null;
  params?: string | null;
}

export interface AiModelsResponse {
  provider: string;
  active: string;
  models: AiModel[];
}

export interface AiSource {
  filename: string;
  chunk_index: number;
  snippet: string;
}

export interface AiAnswer {
  answer: string;
  /** live = exact database answer, llm = model answer, extractive = fallback. */
  mode: 'llm' | 'extractive' | 'live';
  sources: AiSource[];
}

export interface CorpusDoc {
  id: number;
  filename: string;
  source: string;
  project_id: number | null;
  chunk_count: number;
  created_at: string;
}

// ---------- Stage 6: Construction ----------

export interface ConstructionOut {
  id: number;
  project_id: number;
  status: 'planned' | 'in_progress' | 'completed' | 'on_hold' | string;
  schedule_data: Record<string, unknown> | null;
  wcf_data: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  updated_by_id: number;
  created_at: string;
  updated_at: string;
}

// ---------- ICR branch ----------

export interface IcrHandoff {
  id: number;
  project_id: number;
  milestone:
    | 'mto_to_project_control'
    | 'materials_ordered'
    | 'materials_received'
    | 'eat_install_scheduled'
    | 'eat_installed'
    | 'follow_up'
    | 'closed';
  status: 'pending' | 'in_progress' | 'done' | 'blocked';
  note: string | null;
  recorded_by_id: number;
  recorded_at: string;
}

// ---------- Stage 7: Closeout & Handover ----------

export interface PunchListItem {
  id: number;
  project_id: number;
  closeout_id: number;
  trade: string;
  description: string;
  location: string;
  severity: 'minor' | 'major' | 'critical';
  status: 'open' | 'in_progress' | 'resolved' | 'verified';
  assigned_to: string | null;
  due_date: string | null;
  resolved_at: string | null;
  resolution_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PunchListItemInput {
  trade: string;
  description: string;
  location?: string;
  severity?: 'minor' | 'major' | 'critical';
  assigned_to?: string | null;
  due_date?: string | null;
}

export interface CloseoutUpdateInput {
  status?: string;
  testing_commissioning_notes?: string;
  as_built_drawings_submitted?: boolean;
  o_and_m_manuals_submitted?: boolean;
  warranty_start_date?: string | null;
  warranty_end_date?: string | null;
  warranty_provider?: string | null;
  warranty_notes?: string | null;
  client_signoff_by?: string | null;
  client_signoff_date?: string | null;
  client_feedback?: string | null;
}

export interface CloseoutSignoffInput {
  client_signoff_by: string;
  client_feedback?: string | null;
}

export interface CloseoutRecord {
  id: number;
  project_id: number;
  status: 'in_progress' | 'punch_list_review' | 'completed' | 'signed_off';
  testing_commissioning_notes: string;
  as_built_drawings_submitted: boolean;
  o_and_m_manuals_submitted: boolean;
  warranty_start_date: string | null;
  warranty_end_date: string | null;
  warranty_provider: string | null;
  warranty_notes: string | null;
  client_signoff_by: string | null;
  client_signoff_date: string | null;
  client_feedback: string | null;
  updated_by_id: number;
  created_at: string;
  updated_at: string;
  punch_items: PunchListItem[];
}

export interface AuditEntry {
  id: number;
  user: string;
  action: string;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface DashboardStats {
  totals: {
    projects: number;
    ear: number;
    design: number;
    procore: number;
  };
  by_stage: Record<string, number>;
  by_disposition: Record<string, number>;
}

