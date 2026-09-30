import type {
  AiAnswer,
  AiModelsResponse,
  Attachment,
  AuditEntry,
  BoqItem,
  CloseoutRecord,
  CloseoutSignoffInput,
  CloseoutUpdateInput,
  ConstructionDashboardKpis,
  ConstructionOut,
  ConstructionProjectSummary,
  ConstructionTeamMember,
  CorpusDoc,
  CreateProjectInput,
  CreateUserInput,
  EarAiFinding,
  EarRecord,
  EarTradeInput,
  IcrHandoff,
  MaterialTrackingItem,
  MaterialTrackingWithProject,
  MomAgendaItem,
  MomDetails,
  MomRecord,
  MomStatusUpdate,
  PrFormParseResult,
  ProjectDetail,
  ProjectFilters,
  ProjectSummary,
  PunchListItem,
  PunchListItemInput,
  SowRecord,
  UpdateUserInput,
  User,
  WorkPermit,
  WorkPermitWithProject,
  DashboardStats,
} from './types';

const TOKEN_KEY = 'ihp_access_token';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function redirectToLogin(): void {
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

/** Extract a human-readable message from a FastAPI error body. */
async function parseErrorMessage(res: Response): Promise<string> {
  try {
    const data: unknown = await res.json();
    if (data && typeof data === 'object' && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === 'string') return detail;
      // FastAPI 422 validation errors: detail is a list of {loc, msg, type}
      if (Array.isArray(detail)) {
        return detail
          .map((item: unknown) =>
            item && typeof item === 'object' && 'msg' in item
              ? String((item as { msg: unknown }).msg)
              : JSON.stringify(item),
          )
          .join('; ');
      }
      return JSON.stringify(detail);
    }
  } catch {
    // Body was not JSON; fall through to the generic message.
  }
  return `Request failed with status ${res.status}`;
}

async function request<T>(path: string, init: RequestInit = {}, jsonBody?: unknown): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let body = init.body;
  if (jsonBody !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(jsonBody);
  }

  const res = await fetch(path, { ...init, headers, body });

  if (res.status === 401) {
    clearToken();
    redirectToLogin();
    throw new ApiError(401, 'Your session has expired. Please log in again.');
  }
  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorMessage(res));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- Auth ---

export async function login(username: string, password: string): Promise<void> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username, password }).toString(),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorMessage(res));
  }
  const data = (await res.json()) as { access_token: string; token_type: string };
  setToken(data.access_token);
}

export function getMe(): Promise<User> {
  return request<User>('/api/auth/me');
}

// --- Profile self-service ---

export function updateProfile(patch: { full_name?: string; email?: string; title?: string }): Promise<User> {
  return request<User>('/api/auth/profile', { method: 'PATCH' }, patch);
}

export function changePassword(currentPassword: string, newPassword: string): Promise<{ detail: string }> {
  return request<{ detail: string }>('/api/auth/change-password', { method: 'POST' }, {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export interface UserRbacRole {
  id: number;
  name: string;
  display_name: string;
  discipline: string | null;
  color: string;
}

export interface MyRolesResponse {
  user_id: number;
  roles: UserRbacRole[];
  effective_permissions: Record<string, Record<string, boolean>>;
}

export function getMyRoles(): Promise<MyRolesResponse> {
  return request<MyRolesResponse>('/api/auth/my-roles');
}

// --- Admin: user management ---

export function listUsers(): Promise<User[]> {
  return request<User[]>('/api/admin/users');
}

export function createUser(input: CreateUserInput): Promise<User> {
  return request<User>('/api/admin/users', { method: 'POST' }, input);
}

export function updateUser(id: number, patch: UpdateUserInput): Promise<User> {
  return request<User>(`/api/admin/users/${id}`, { method: 'PUT' }, patch);
}

export function deleteUser(id: number): Promise<void> {
  return request<void>(`/api/admin/users/${id}`, { method: 'DELETE' });
}

// --- Projects ---

export function listProjects(filters: ProjectFilters = {}): Promise<ProjectSummary[]> {
  const params = new URLSearchParams();
  if (filters.stage) params.set('stage', filters.stage);
  if (filters.disposition) params.set('disposition', filters.disposition);
  if (filters.search) params.set('search', filters.search);
  if (filters.bucket) params.set('bucket', filters.bucket);
  const qs = params.toString();
  return request<ProjectSummary[]>(`/api/projects${qs ? '?' + qs : ''}`);
}

export function createProject(input: CreateProjectInput): Promise<ProjectDetail> {
  return request<ProjectDetail>('/api/projects', { method: 'POST' }, input);
}

export function getProject(id: number): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${id}`);
}

export function updateProject(
  id: number,
  patch: Partial<CreateProjectInput>,
): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${id}`, { method: 'PUT' }, patch);
}

export function setProjectStage(
  id: number,
  stage: string,
  note?: string,
): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${id}/stage`, { method: 'POST' }, { stage, note });
}

/** Tracker files the backend currently resolves to (newest _DDMMYYYY). */
export interface TrackerSources {
  /** First searched folder; `trackers_dirs` lists all of them. */
  trackers_dir: string;
  trackers_dirs?: string[];
  /** Where admin uploads are published (on the persisted data volume). */
  upload_dir?: string;
  /** The Planner's own drop folder. */
  configured_dir?: string;
  planner_latest: string | null;
  planner_path?: string | null;
  planner_date?: string | null;
  planner_dir?: string | null;
  /** "upload" when the live version came from an upload, else "folder". */
  planner_source?: 'upload' | 'folder' | null;
  om_latest: string | null;
  om_path?: string | null;
  om_date?: string | null;
  om_dir?: string | null;
  om_source?: 'upload' | 'folder' | null;
  pr_request_count: number;
}

export function getTrackerSources(): Promise<TrackerSources> {
  return request<TrackerSources>('/api/admin/import/sources');
}

/** Import the newest dated planner tracker from the trackers folder. */
export function autoImportTrackers(dryRun = false): Promise<{
  ok: boolean;
  planner_file: string;
  planner_date: string | null;
  rows_processed: number;
  om_file: string | null;
  om_date: string | null;
  om_rows: number;
}> {
  const q = dryRun ? '?dry_run=true' : '';
  return request(`/api/admin/import/auto${q}`, { method: 'POST' });
}

/** Trade-wise SOW scope suggestions mined from similar archived SOWs. */
export interface SowSuggestion {
  text: string;
  source_pr: string | null;
  source_title: string | null;
}

export interface SowSuggestions {
  project: string;
  trades: { trade: string; suggestions: SowSuggestion[]; existing_count: number }[];
  total_suggestions: number;
}

export function getSowSuggestions(projectId: number): Promise<SowSuggestions> {
  return request<SowSuggestions>(`/api/projects/${projectId}/sow/suggestions`);
}

/** Suggested MOM meeting details, auto-filled from the project. */
export interface MomDefaults {
  meeting_title: string;
  meeting_location: string;
  meeting_number: string;
  meeting_date: string;
  meeting_time: string;
  project_pr: string;
  project_title: string;
  pi_name: string | null;
  pi_email: string | null;
  existing_moms: number;
}

export function getMomDefaults(projectId: number): Promise<MomDefaults> {
  return request<MomDefaults>(`/api/projects/${projectId}/mom/defaults`);
}

/** Project Summary (house format) as structured data for the web view. */
export interface SummarySectionTrade {
  trade: string;
  items: string[];
}

export interface ProjectSummaryData {
  date: string;
  to: string | null;
  info: {
    project_reference: string;
    division: string;
    customer: string;
    contact: string;
    location: string;
  };
  scope: SummarySectionTrade[];
  schedule: Record<string, number>;
}

export function getProjectSummaryData(projectId: number): Promise<ProjectSummaryData> {
  return request<ProjectSummaryData>(`/api/projects/${projectId}/summary`);
}

/** Download the Project Summary as Word or PDF (blob download). */
export async function downloadProjectSummary(
  projectId: number,
  format: 'docx' | 'pdf',
): Promise<void> {
  const res = await fetch(
    `/api/projects/${projectId}/generate/summary?format=${format}`,
    { headers: { Authorization: `Bearer ${getToken()}` } },
  );
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `Project-Summary.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Construction-division progress totals (started / finished / pending). */
export interface ConstructionOverview {
  today: string;
  started: number;
  finished: number;
  pending: number;
  total: number;
  planned_hours: number;
  remaining_hours: number;
  required_crew_now?: number;
  flexibility: {
    min_slack_days: number | null;
    max_slack_days: number | null;
    negative_slack: number;
  };
  projects: ScheduleItem[];
}

/** One person's allocation for a day. */
export interface CrewAssignment {
  id: number;
  project_id: number;
  pr_number: string | null;
  project_title: string | null;
  project_location: string | null;
  person_name: string;
  person_email: string | null;
  person_phone: string | null;
  work_date: string | null;
  shift: 'AM' | 'PM' | 'FULL' | string;
  shift_label: string;
  shift_hours: number;
  hours: number;
  task: string | null;
  notes: string | null;
  notified_at: string | null;
  notify_channel: string | null;
  notify_error: string | null;
}

/** Per-person load for one day, split into the AM and PM lanes. */
export interface CrewLoad {
  day: string;
  shifts: Record<string, { label: string; hours: number }>;
  capacity_hours: number;
  people: {
    person_name: string;
    person_email: string | null;
    person_phone: string | null;
    am_hours: number;
    pm_hours: number;
    total_hours: number;
    idle_hours: number;
    over_hours: number;
    status: 'over' | 'full' | 'partial' | 'idle';
    assignments: CrewAssignment[];
  }[];
  project_hours: { project_id: number; pr_number: string | null; title: string | null; hours: number }[];
  totals: { people: number; hours: number; over_allocated: number; idle_people: number };
}

export interface CrewAssignmentInput {
  project_id: number;
  person_name: string;
  person_email?: string | null;
  person_phone?: string | null;
  work_date: string;
  shift: 'AM' | 'PM' | 'FULL';
  hours?: number | null;
  task?: string | null;
  notes?: string | null;
}

export function getConstructionOverview(): Promise<ConstructionOverview> {
  return request<ConstructionOverview>('/api/construction/overview');
}

export function getCrewLoad(day: string): Promise<CrewLoad> {
  return request<CrewLoad>(`/api/construction/load?day=${encodeURIComponent(day)}`);
}

export function listCrew(dateFrom: string, dateTo: string): Promise<CrewAssignment[]> {
  return request<CrewAssignment[]>(
    `/api/construction/crew?date_from=${dateFrom}&date_to=${dateTo}`,
  );
}

export function createCrewAssignment(input: CrewAssignmentInput): Promise<CrewAssignment> {
  return request<CrewAssignment>('/api/construction/crew', { method: 'POST' }, input);
}

export function deleteCrewAssignment(id: number): Promise<void> {
  return request<void>(`/api/construction/crew/${id}`, { method: 'DELETE' });
}

export function notifyCrewAssignment(
  id: number,
  channel: 'auto' | 'email' | 'whatsapp' | 'sms' | 'copy' = 'auto',
): Promise<{
  sent: boolean;
  channel: string | null;
  configured: Record<string, boolean>;
  results: Record<string, unknown>;
  error: string | null;
  message: string;
  whatsapp_link: string | null;
  mailto_link: string | null;
}> {
  return request(`/api/construction/crew/${id}/notify?channel=${channel}`, { method: 'POST' });
}

/** One project on the Planner-driven construction schedule board. */
export interface ScheduleItem {
  id: number;
  pr_number: string;
  title: string;
  pi_name: string | null;
  location: string | null;
  phase: string | null;
  bucket: string | null;
  stage: string;
  next_gate: string | null;
  priority: string | null;
  trades: string[];
  flags: string[];
  start_date: string | null;
  finish_date: string | null;
  days_left: number | null;
  completion_pct: number | null;
  effort_hours: number | null;
  remaining_hours: number | null;
  required_hours_per_day: number | null;
  window: string | null;
  risks: string[];
  risk_level: 'high' | 'medium' | 'low';
}

export interface ConstructionLiveResponse {
  today: string;
  window_labels: Record<string, string>;
  summary: Record<string, number>;
  total_scheduled: number;
  unscheduled: number;
  risk: {
    high: number;
    medium: number;
    design_blockers: number;
    high_items: ScheduleItem[];
  };
  windows: Record<string, ScheduleItem[]>;
  design_blockers: ScheduleItem[];
}

/** Planner-driven construction board: finish windows, urgency, gates, risk. */
export function getConstructionLive(includeClosed = false): Promise<ConstructionLiveResponse> {
  return request<ConstructionLiveResponse>(
    `/api/projects/construction-live${includeClosed ? '?include_closed=true' : ''}`,
  );
}

/** Cross-tracker consistency report (Planner vs O&M). */
export interface ConsistencyIssue {
  code: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  pr_key: string | null;
  field: string | null;
  planner_value: string | null;
  om_value: string | null;
}

export interface ConsistencyResponse {
  ok: boolean;
  error?: string;
  planner_file?: string | null;
  planner_date?: string | null;
  om_file?: string | null;
  om_date?: string | null;
  summary: {
    total_checked?: number;
    errors?: number;
    warnings?: number;
    infos?: number;
    by_code?: Record<string, number>;
  };
  issues: ConsistencyIssue[];
}

export function getConsistency(refresh = false): Promise<ConsistencyResponse> {
  return request<ConsistencyResponse>(
    `/api/projects/consistency${refresh ? '?refresh=true' : ''}`,
  );
}

/** Active PRs from the O&M tracker, split by IHP classification. */
export interface OmActivePr {
  pr_key: string;
  source_tab: string;
  title: string | null;
  division: string | null;
  requestor: string | null;
  location: string | null;
  status: string | null;
  classification_raw: string | null;
  category: string;
  remarks: string | null;
  request_date: string | null;
}

export interface OmActiveResponse {
  ok: boolean;
  error?: string;
  source: string | null;
  source_date?: string | null;
  summary: {
    total?: number;
    ihp_active_count?: number;
    equipment_branch_count?: number;
    assessment_count?: number;
    unknown_count?: number;
    /** Assessment-stage O&M PRs not yet in the Planner register. */
    upcoming_ear_count?: number;
    by_tab?: Record<string, number>;
    by_category?: Record<string, number>;
  };
  items: OmActivePr[];
}

export function getOmActivePrs(): Promise<OmActiveResponse> {
  return request<OmActiveResponse>('/api/projects/om-active');
}

export function promoteToEar(id: number, new_pr_number: string): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${id}/promote-to-ear`, { method: 'POST' }, { new_pr_number });
}

export function deleteProject(id: number): Promise<void> {
  return request<void>(`/api/projects/${id}`, { method: 'DELETE' });
}

export function getAudit(id: number): Promise<AuditEntry[]> {
  return request<AuditEntry[]>(`/api/projects/${id}/audit`);
}

export async function getDashboardStats(): Promise<DashboardStats> {
  return request<DashboardStats>('/api/projects/stats', { method: 'GET' });
}

// --- Intake ---

export async function parsePrForm(file: File): Promise<PrFormParseResult> {
  const form = new FormData();
  form.append('file', file);
  return request<PrFormParseResult>('/api/intake/parse-pr-form', {
    method: 'POST',
    body: form,
  });
}

// --- AI assistant ---

export interface AiChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

export function askAi(
  question: string,
  projectId?: number,
  model?: string,
  history?: AiChatTurn[],
): Promise<AiAnswer> {
  return request<AiAnswer>('/api/ai/ask', { method: 'POST' }, {
    question,
    project_id: projectId ?? null,
    model: model ?? null,
    history: history?.length ? history : null,
  });
}

// --- Public access (no account) -------------------------------------------

export interface PublicDashboard {
  totals: { projects: number; scheduled: number; without_planner_date: number };
  by_division: Record<string, number>;
  by_stage: Record<string, number>;
  windows: {
    overdue: number;
    this_week: number;
    on_hold: number;
    high_risk: number;
    behind_plan: number;
    design_gate: number;
  };
  planner_sync: string | null;
  generated_at: string;
  requestable_roles: { value: string; label: string }[];
}

export interface AccessRequestRow {
  id: number;
  reference: string;
  full_name: string;
  email: string;
  phone: string | null;
  company: string | null;
  requested_role: string;
  requested_role_label: string;
  message: string | null;
  status: 'pending' | 'approved' | 'rejected';
  decision_note: string | null;
  created_at: string;
  decided_at: string | null;
  invite_token: string | null;
  invite_url: string | null;
  invite_expires_at: string | null;
  invite_used_at: string | null;
  user_id: number | null;
  source_ip: string | null;
}

export interface AccessRequestInbox {
  pending: number;
  approved: number;
  rejected: number;
  roles: { value: string; label: string }[];
  items: AccessRequestRow[];
}

/** Aggregate, anonymous portfolio metrics for the public dashboard. */
export function getPublicDashboard(): Promise<PublicDashboard> {
  return request<PublicDashboard>('/api/public/dashboard');
}

/** Ask for an account from the public form. */
export function requestAccess(input: {
  full_name: string;
  email: string;
  phone?: string;
  company?: string;
  requested_role: string;
  message?: string;
}): Promise<{ ok: boolean; reference: string; message: string }> {
  return request('/api/public/access-request', { method: 'POST' }, input);
}

export function listAccessRequests(status?: string): Promise<AccessRequestInbox> {
  const query = status ? '?status=' + encodeURIComponent(status) : '';
  return request<AccessRequestInbox>('/api/admin/access-requests' + query);
}

export function getAccessNotifications(): Promise<{
  pending_access_requests: number;
  latest: { id: number; full_name: string; email: string; requested_role: string; created_at: string }[];
}> {
  return request('/api/admin/access-requests/notifications');
}

export function approveAccessRequest(
  id: number,
  role?: string,
  note?: string,
): Promise<{ ok: boolean; username?: string; request: AccessRequestRow; already_approved?: boolean }> {
  return request('/api/admin/access-requests/' + id + '/approve', { method: 'POST' }, { role, note });
}

export function rejectAccessRequest(
  id: number,
  note?: string,
): Promise<{ ok: boolean; request: AccessRequestRow }> {
  return request('/api/admin/access-requests/' + id + '/reject', { method: 'POST' }, { note });
}

export function reissueAccessInvite(
  id: number,
): Promise<{ ok: boolean; request: AccessRequestRow }> {
  return request('/api/admin/access-requests/' + id + '/reissue', { method: 'POST' });
}

/** Invite link details (public: identifies who is being invited). */
export function getInvite(token: string): Promise<{
  valid: boolean;
  full_name: string;
  email: string;
  role: string;
  username: string;
  expires_at: string | null;
}> {
  return request('/api/auth/invite/' + encodeURIComponent(token), { method: 'GET' });
}

/** Finish an invite: set the password and receive a login token. */
export function acceptInvite(
  token: string,
  password: string,
): Promise<{ ok: boolean; username: string; access_token: string; token_type: string }> {
  return request('/api/auth/invite/' + encodeURIComponent(token), { method: 'POST' }, { password });
}

/** Local/remote models the assistant can switch between. */
export function listAiModels(): Promise<AiModelsResponse> {
  return request<AiModelsResponse>('/api/ai/models');
}

export interface AiProviderInfo {
  id: string;
  label: string;
  kind: string;
  local: boolean;
  docs: string;
  notes: string;
  default_models: string[];
  base_url: string;
  model: string;
  key_env: string;
  key_present: boolean;
  configured: boolean;
  selected: boolean;
  has_saved_key: boolean;
}

export interface AiProvidersResponse {
  selected: string;
  count: number;
  providers: AiProviderInfo[];
}

/** The provider catalogue: every market API the platform can talk to. */
export function listAiProviders(): Promise<AiProvidersResponse> {
  return request<AiProvidersResponse>('/api/ai/providers');
}

export interface AiProviderTestResult {
  ok: boolean;
  provider: string;
  label?: string;
  model?: string;
  seconds?: number;
  reply?: string;
  error?: string;
}

/** Probe one provider with credentials from the form (not stored). */
export function testAiProvider(input: {
  provider: string;
  model?: string;
  base_url?: string;
  api_key?: string;
}): Promise<AiProviderTestResult> {
  return request<AiProviderTestResult>('/api/ai/providers/test', { method: 'POST' }, input);
}

export interface AiFeedbackInput {
  question: string;
  answer: string;
  rating: 'up' | 'down';
  mode?: string;
  model?: string;
  project_id?: number;
  comment?: string;
  sources?: { filename: string; snippet: string }[];
}

/** Record a rating on an answer - this is the local training signal. */
export function sendAiFeedback(input: AiFeedbackInput): Promise<{ recorded: boolean }> {
  return request<{ recorded: boolean }>('/api/ai/feedback', { method: 'POST' }, input);
}

export interface AiCorpusStats {
  documents: number;
  chunks: number;
  embedded_chunks: number;
  by_source: Record<string, number>;
}

/** Document retrieval (no model) - shows what the knowledge base can cite. */
export function searchAiDocuments(
  query: string,
  k = 5,
): Promise<{
  count: number;
  corpus: AiCorpusStats;
  hits: { filename: string; snippet: string; score: number }[];
}> {
  const params = new URLSearchParams({ q: query, k: String(k) });
  return request('/api/ai/search?' + params.toString(), { method: 'GET' });
}

export function listCorpus(): Promise<CorpusDoc[]> {
  return request<CorpusDoc[]>('/api/ai/corpus');
}

export function uploadCorpusDoc(
  file: File,
): Promise<{ id: number; filename: string; chunk_count: number; embedded: boolean }> {
  const form = new FormData();
  form.append('file', file);
  return request('/api/ai/corpus/upload', { method: 'POST', body: form });
}

export function ingestAttachmentToCorpus(
  attachmentId: number,
): Promise<{ id: number; filename: string; chunk_count: number; embedded: boolean }> {
  return request(`/api/ai/corpus/ingest-attachment/${attachmentId}`, { method: 'POST' });
}

export function deleteCorpusDoc(id: number): Promise<void> {
  return request<void>(`/api/ai/corpus/${id}`, { method: 'DELETE' });
}

// --- Attachments ---

export function uploadAttachments(projectId: number, files: File[]): Promise<Attachment[]> {
  const form = new FormData();
  files.forEach((file) => form.append('files', file));
  // Content-Type is left unset so the browser adds the multipart boundary.
  return request<Attachment[]>(`/api/projects/${projectId}/attachments`, {
    method: 'POST',
    body: form,
  });
}

export function deleteAttachment(projectId: number, attachmentId: number): Promise<void> {
  return request<void>(`/api/projects/${projectId}/attachments/${attachmentId}`, {
    method: 'DELETE',
  });
}

// --- MOM ---

export function generateMom(projectId: number, details?: MomDetails): Promise<MomRecord> {
  return request<MomRecord>(`/api/projects/${projectId}/mom/generate`, { method: 'POST' }, details ?? {});
}

/** Append a scope item to the MOM agenda (trade users: own trade only). */
export function addMomAgendaItem(projectId: number, item: MomAgendaItem): Promise<MomRecord> {
  return request<MomRecord>(`/api/projects/${projectId}/mom/agenda`, { method: 'POST' }, item);
}

/** Edit an agenda item (trade users: own trade's items only). */
export function updateMomAgendaItem(
  projectId: number,
  index: number,
  item: MomAgendaItem,
): Promise<MomRecord> {
  return request<MomRecord>(`/api/projects/${projectId}/mom/agenda/${index}`, { method: 'PUT' }, item);
}

/** Delete an agenda item (trade users: own trade's items only). */
export function deleteMomAgendaItem(projectId: number, index: number): Promise<MomRecord> {
  return request<MomRecord>(`/api/projects/${projectId}/mom/agenda/${index}`, { method: 'DELETE' });
}

export function setMomStatus(
  projectId: number,
  status: MomStatusUpdate,
  note?: string,
): Promise<MomRecord> {
  const payload: { status: MomStatusUpdate; note?: string } = { status };
  if (note !== undefined) payload.note = note;
  return request<MomRecord>(`/api/projects/${projectId}/mom/status`, { method: 'POST' }, payload);
}

// --- Downloads (need the Authorization header, so fetch + blob instead of <a href>) ---

async function fetchBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const res = await fetch(path, { headers });
  if (res.status === 401) {
    clearToken();
    redirectToLogin();
    throw new ApiError(401, 'Your session has expired. Please log in again.');
  }
  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorMessage(res));
  }
  return res.blob();
}

function filenameFromDisposition(res: Response, fallback: string): string {
  const header = res.headers.get('Content-Disposition') ?? '';
  const match = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(header);
  if (!match) return fallback;
  return decodeURIComponent(match[1].replace(/"/g, '').trim());
}

async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const res = await fetch(path, { headers });
  if (res.status === 401) {
    clearToken();
    redirectToLogin();
    throw new ApiError(401, 'Your session has expired. Please log in again.');
  }
  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorMessage(res));
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filenameFromDisposition(res, fallbackName);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function downloadAttachment(
  projectId: number,
  attachmentId: number,
  filename: string,
): Promise<void> {
  return downloadFile(`/api/projects/${projectId}/attachments/${attachmentId}/download`, filename);
}

export function downloadMom(projectId: number, fmt: 'docx' | 'pdf'): Promise<void> {
  return downloadFile(`/api/projects/${projectId}/mom/download?fmt=${fmt}`, `mom.${fmt}`);
}

/**
 * Download the MOM as a ready-to-send email (.eml).
 *
 * Opening the file in Outlook gives a compose window with every participant in
 * "To", the subject and body filled in and the minute attached - it is sent from
 * the user's own mailbox, and no mail server credentials are involved.
 */
export function downloadMomEmail(
  projectId: number,
  to?: string,
  cc?: string,
  attach = true,
): Promise<void> {
  const params = new URLSearchParams();
  if (to?.trim()) params.set('to', to.trim());
  if (cc?.trim()) params.set('cc', cc.trim());
  params.set('attach', attach ? 'true' : 'false');
  return downloadFile(
    `/api/projects/${projectId}/mom/email.eml?${params.toString()}`,
    'MOM.eml',
  );
}

/**
 * The mailto: link that opens the MOM straight in the local mail client.
 *
 * Nothing is attached: the minute is inline, so the sender can add their own
 * images or files in Outlook. The body comes from the server so it matches the
 * stored draft exactly.
 */
export function getMomEmailLink(
  projectId: number,
  to?: string,
  cc?: string,
): Promise<{
  to: string[];
  cc: string[];
  subject: string;
  body: string;
  mailto: string;
  body_chars: number;
  note: string | null;
}> {
  const params = new URLSearchParams();
  if (to?.trim()) params.set('to', to.trim());
  if (cc?.trim()) params.set('cc', cc.trim());
  const query = params.toString();
  return request(
    `/api/projects/${projectId}/mom/email-link${query ? '?' + query : ''}`,
    { method: 'GET' },
  );
}

/**
 * Open the minute as a web page in a new tab.
 *
 * The document is fetched with the bearer token and handed to the browser as a
 * blob, so the app view, the print view and the email body are the same
 * artifact.
 */
export async function openMomWebView(projectId: number): Promise<void> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  const res = await fetch(
    `/api/projects/${projectId}/mom/view?base_url=${encodeURIComponent(origin)}`,
    { headers },
  );
  if (!res.ok) throw new ApiError(res.status, await parseErrorMessage(res));
  const html = await res.text();
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  window.open(url, '_blank', 'noopener');
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Let the AI agent draft the trade-wise agenda from the PR request. */
export function suggestMomAgenda(projectId: number): Promise<{
  items: { trade: string; scope: string; action: string; etc: string }[];
  count: number;
  raw: string;
}> {
  return request(`/api/projects/${projectId}/mom/suggest`, { method: 'POST' }, {});
}

/** Fetch the MOM DOCX as a blob for in-browser preview (docx-preview). */
export function getMomDocxBlob(projectId: number): Promise<Blob> {
  return fetchBlob(`/api/projects/${projectId}/mom/download?fmt=docx`);
}

// ---------- Stage 2: Disposition ----------

export function setDisposition(
  projectId: number,
  disposition: 'ICR' | 'PROJECT',
  justification?: string,
): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/api/projects/${projectId}/disposition`,
    { method: 'POST' },
    { disposition, justification: justification ?? '' },
  );
}

// ---------- Stage 3: EAR ----------

export function getEar(projectId: number): Promise<EarRecord> {
  return request<EarRecord>(`/api/projects/${projectId}/ear`);
}

export function updateEar(
  projectId: number,
  update: { summary?: string; recommendations?: string; status?: 'draft' | 'under_review' | 'approved' },
): Promise<EarRecord> {
  return request<EarRecord>(`/api/projects/${projectId}/ear`, { method: 'PATCH' }, update);
}

export function submitEarTradeInput(
  projectId: number,
  input: {
    trade: string;
    proposal: string;
    comments?: string;
    missing_info?: string;
    has_conflict?: boolean;
    conflict_reason_code?: string | null;
    conflict_resolution_note?: string | null;
    estimated_materials_cost?: number;
    estimated_manpower_cost?: number;
  },
): Promise<EarTradeInput> {
  return request<EarTradeInput>(`/api/projects/${projectId}/ear/trade-input`, { method: 'POST' }, input);
}

export function updateEarBudget(
  projectId: number,
  budget: {
    rates?: Record<string, number>;
    trade_budgets?: Record<string, { materials: number; manpower: number }>;
    billing_type?: 'pi_baseline' | 'asepc_ihp';
  },
): Promise<EarRecord> {
  return request<EarRecord>(`/api/projects/${projectId}/ear/budget`, { method: 'POST' }, budget);
}

export function runEarAiReview(projectId: number): Promise<{ findings: EarAiFinding[]; count: number }> {
  return request<{ findings: EarAiFinding[]; count: number }>(`/api/projects/${projectId}/ear/ai-review`, {
    method: 'POST',
  });
}

export function generateEarDoc(projectId: number): Promise<EarRecord> {
  return request<EarRecord>(`/api/projects/${projectId}/ear/generate`, { method: 'POST' });
}

export function downloadEar(projectId: number, fmt: 'docx' | 'pdf'): Promise<void> {
  return downloadFile(`/api/projects/${projectId}/ear/download?fmt=${fmt}`, `EAR.${fmt}`);
}

export function getEarDocxBlob(projectId: number): Promise<Blob> {
  return fetchBlob(`/api/projects/${projectId}/ear/download?fmt=docx`);
}

// ---------- Stage 4: SOW & BOQ/MTO ----------

export function listSows(projectId: number): Promise<SowRecord[]> {
  return request<SowRecord[]>(`/api/projects/${projectId}/sow`);
}

export function createSowRevision(
  projectId: number,
  input: { revision_name?: string; scope_text?: string; procore_comments?: string | null },
): Promise<SowRecord> {
  return request<SowRecord>(`/api/projects/${projectId}/sow`, { method: 'POST' }, input);
}

export function updateSowStatus(
  projectId: number,
  sowId: number,
  status: 'draft' | 'in_review' | 'approved',
): Promise<SowRecord> {
  return request<SowRecord>(`/api/projects/${projectId}/sow/${sowId}?status_val=${status}`, { method: 'PATCH' });
}

export function listBoqItems(projectId: number): Promise<BoqItem[]> {
  return request<BoqItem[]>(`/api/projects/${projectId}/boq`);
}

export function addBoqItem(
  projectId: number,
  item: {
    trade: string;
    item_code: string;
    description: string;
    unit?: string;
    quantity?: number;
    unit_rate?: number;
    material_spec?: string | null;
    supplier_lead_time_days?: number | null;
  },
): Promise<BoqItem> {
  return request<BoqItem>(`/api/projects/${projectId}/boq`, { method: 'POST' }, item);
}

export function updateBoqItem(
  projectId: number,
  itemId: number,
  item: Partial<BoqItem>,
): Promise<BoqItem> {
  return request<BoqItem>(`/api/projects/${projectId}/boq/${itemId}`, { method: 'PATCH' }, item);
}

export function deleteBoqItem(projectId: number, itemId: number): Promise<void> {
  return request<void>(`/api/projects/${projectId}/boq/${itemId}`, { method: 'DELETE' });
}

export function exportBoqExcel(projectId: number, prNumber: string): Promise<void> {
  return downloadFile(`/api/projects/${projectId}/boq/export`, `BOQ_${prNumber}.xlsx`);
}

// ---------- Stage 5 & 6: Permits & Construction ----------

export function listPermits(projectId: number): Promise<WorkPermit[]> {
  return request<WorkPermit[]>(`/api/projects/${projectId}/permits`);
}

export function createPermit(
  projectId: number,
  permit: {
    permit_type: string;
    permit_number: string;
    location: string;
    contractor_name: string;
    valid_from?: string | null;
    valid_to?: string | null;
    safety_measures?: Record<string, boolean>;
  },
): Promise<WorkPermit> {
  return request<WorkPermit>(`/api/projects/${projectId}/permits`, { method: 'POST' }, permit);
}

export function updatePermitStatus(
  projectId: number,
  permitId: number,
  status: string,
): Promise<WorkPermit> {
  return request<WorkPermit>(
    `/api/projects/${projectId}/permits/${permitId}/status?status_val=${status}`,
    { method: 'PATCH' },
  );
}

export function listTeamMembers(projectId: number): Promise<ConstructionTeamMember[]> {
  return request<ConstructionTeamMember[]>(`/api/projects/${projectId}/team`);
}

export function addTeamMember(
  projectId: number,
  member: { name: string; mobile?: string; email?: string; role_or_trade?: string },
): Promise<ConstructionTeamMember> {
  return request<ConstructionTeamMember>(`/api/projects/${projectId}/team`, { method: 'POST' }, member);
}

export function removeTeamMember(projectId: number, memberId: number): Promise<void> {
  return request<void>(`/api/projects/${projectId}/team/${memberId}`, { method: 'DELETE' });
}

export function listMaterials(projectId: number): Promise<MaterialTrackingItem[]> {
  return request<MaterialTrackingItem[]>(`/api/projects/${projectId}/materials`);
}

export function addMaterialItem(
  projectId: number,
  item: {
    trade: string;
    item_description: string;
    po_number?: string | null;
    contractor_or_supplier?: string | null;
    lead_time_days?: number;
    supply_type?: 'supply_only' | 'supply_and_install';
    expected_delivery?: string | null;
    actual_delivery?: string | null;
    installer_arrival_date?: string | null;
    status?: string;
    notes?: string | null;
  },
): Promise<MaterialTrackingItem> {
  return request<MaterialTrackingItem>(`/api/projects/${projectId}/materials`, { method: 'POST' }, item);
}

export function updateMaterialItem(
  projectId: number,
  itemId: number,
  item: Partial<MaterialTrackingItem>,
): Promise<MaterialTrackingItem> {
  return request<MaterialTrackingItem>(`/api/projects/${projectId}/materials/${itemId}`, { method: 'PATCH' }, item);
}

export function getConstructionDashboard(): Promise<ConstructionDashboardKpis> {
  return request<ConstructionDashboardKpis>('/api/construction/dashboard');
}

export function listConstructionProjects(): Promise<ConstructionProjectSummary[]> {
  return request<ConstructionProjectSummary[]>('/api/construction/projects');
}

export function listAllMaterialsAcrossProjects(): Promise<MaterialTrackingWithProject[]> {
  return request<MaterialTrackingWithProject[]>('/api/construction/materials');
}

export function listAllPermitsAcrossProjects(): Promise<WorkPermitWithProject[]> {
  return request<WorkPermitWithProject[]>('/api/construction/permits');
}

// ---------- Stage 6: Construction ----------

export function getConstruction(projectId: number): Promise<ConstructionOut> {
  return request<ConstructionOut>(`/api/projects/${projectId}/construction`);
}

export function updateConstruction(
  projectId: number,
  update: { status?: string; schedule_data?: Record<string, unknown> | null; wcf_data?: Record<string, unknown> | null },
): Promise<ConstructionOut> {
  return request<ConstructionOut>(`/api/projects/${projectId}/construction`, { method: 'PATCH' }, update);
}

export function recordWorkPermit(
  projectId: number,
  wcfData: Record<string, unknown>,
): Promise<ConstructionOut> {
  return request<ConstructionOut>(`/api/projects/${projectId}/construction/work-permit`, { method: 'POST' }, wcfData);
}

// ---------- ICR branch hand-offs ----------

export function listIcrHandoffs(projectId: number): Promise<IcrHandoff[]> {
  return request<IcrHandoff[]>(`/api/projects/${projectId}/icr/handoffs`);
}

export function recordIcrHandoff(
  projectId: number,
  input: { milestone: IcrHandoff['milestone']; status?: IcrHandoff['status']; note?: string | null },
): Promise<IcrHandoff> {
  return request<IcrHandoff>(`/api/projects/${projectId}/icr/handoffs`, { method: 'POST' }, input);
}

// ---------- Stage 7: Closeout & Handover ----------

export function getCloseout(projectId: number): Promise<CloseoutRecord> {
  return request<CloseoutRecord>(`/api/projects/${projectId}/closeout`);
}

export function updateCloseout(
  projectId: number,
  input: CloseoutUpdateInput,
): Promise<CloseoutRecord> {
  return request<CloseoutRecord>(`/api/projects/${projectId}/closeout`, { method: 'PATCH' }, input);
}

export function listPunchItems(projectId: number): Promise<PunchListItem[]> {
  return request<PunchListItem[]>(`/api/projects/${projectId}/closeout/punch-list`);
}

export function addPunchItem(
  projectId: number,
  item: PunchListItemInput,
): Promise<PunchListItem> {
  return request<PunchListItem>(`/api/projects/${projectId}/closeout/punch-list`, { method: 'POST' }, item);
}

export function updatePunchItem(
  projectId: number,
  itemId: number,
  item: Partial<PunchListItem>,
): Promise<PunchListItem> {
  return request<PunchListItem>(`/api/projects/${projectId}/closeout/punch-list/${itemId}`, { method: 'PATCH' }, item);
}

export function deletePunchItem(projectId: number, itemId: number): Promise<void> {
  return request<void>(`/api/projects/${projectId}/closeout/punch-list/${itemId}`, { method: 'DELETE' });
}

export function startPunchList(projectId: number): Promise<CloseoutRecord> {
  return request<CloseoutRecord>(`/api/projects/${projectId}/closeout/start-punch-list`, { method: 'POST' });
}

export function signoffCloseout(
  projectId: number,
  input: CloseoutSignoffInput,
): Promise<CloseoutRecord> {
  return request<CloseoutRecord>(`/api/projects/${projectId}/closeout/signoff`, { method: 'POST' }, input);
}

