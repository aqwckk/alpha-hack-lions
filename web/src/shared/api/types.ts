import type { components } from './schema';

type S = components['schemas'];

// Typed transport DTOs generated from docs/api/openapi.json.
export type UserInfo = S['UserInfo'];
export type Role = UserInfo['role'];
export type TokenResponse = S['TokenResponse'];
export type ClientApplication = S['ClientApplication'];
export type ClientApplicationListItem = S['ClientApplicationListItem'];
export type ClientStatus = ClientApplication['client_status'];
export type ProgressStep = S['ProgressStep'];
export type OfferView = S['OfferView'];
export type OptionView = S['OptionView'];
export type InfoItemView = S['InfoItemView'];
export type SigningView = S['SigningView'];
export type LoanView = S['LoanView'];
export type DocumentInfo = S['DocumentInfo'];
export type RequiredDocument = S['RequiredDocument'];
export type ConsentState = S['ConsentState'];
export type EarlyWarning = S['EarlyWarning'];
export type FieldWarning = S['FieldWarning'];
export type DraftUpdateRequest = S['DraftUpdateRequest'];
export type DraftResponse = S['DraftResponse'];
export type PrefillResponse = S['PrefillResponse'];
export type MatchRequest = S['MatchRequest'];
export type MatchResponse = S['MatchResponse'];
export type ProductCard = S['ProductCard'];
export type ScheduleResponse = S['ScheduleResponse'];
export type ScheduleRow = S['ScheduleRow'];
export type SigningCodeResponse = S['SigningCodeResponse'];
export type ExplanationResponse = S['ExplanationResponse'];
export type InfoAnswer = S['InfoAnswer'];
export type InfoItemInput = S['InfoItemInput'];
export type OptionInput = S['OptionInput'];
export type AiSummaryResponse = S['AiSummaryResponse'];
export type OutageRequest = S['OutageRequest'];
export type IntegrationSource = OutageRequest['source'];

/*
 * The endpoints below return free-form JSON objects in the OpenAPI contract
 * (dictionaries, staff card details, metrics, audit). Their shape is described in
 * docs/api/README.md; the interfaces document what the UI reads and stay tolerant
 * (optional/nullable) where the backend may omit values.
 */

export interface CodeTitle {
  code: string;
  title: string;
}

export interface ProductInfo {
  product_code: string;
  name: string;
  description: string;
  decision_speed: string;
  direct_application: boolean;
  applicant_types: string[];
  allowed_purposes: string[];
  amount_min: string;
  amount_max: string;
  amount_step: string;
  term_min_months: number;
  term_max_months: number;
  base_rate_percent: string;
  review_mode: string;
  min_business_age_months: number;
  requires_owner_guarantee_for: string[];
  requires_collateral: boolean;
  required_documents: string[];
  tranche_max_term_months: number | null;
  requirements: string[];
}

export interface ProductsResponse {
  policy_version: string;
  items: ProductInfo[];
}

export interface ConsentText {
  code: string;
  title: string;
  short_text: string;
  full_text: string;
  text_version: string;
  text_sha256: string;
  ttl_days: number | null;
  required: boolean;
}

export interface Dictionaries {
  purposes: { code: string; title: string; hint: string }[];
  document_types: { code: string; title: string; purpose: string }[];
  consents: ConsentText[];
  offer_decline_reasons: CodeTitle[];
  representative_roles: CodeTitle[];
  collateral_types: CodeTitle[];
  collateral_owners: CodeTitle[];
}

export interface BankDictionaries {
  decline_reason_codes: { code: string; employee_text: string; client_text: string | null }[];
  info_reason_codes: { code: string; client_text_template: string | null; employee_text: string }[];
  requestable_fields: { field_name: string; label: string }[];
  document_types: { code: string; title: string; purpose: string }[];
}

export interface NotificationItem {
  id: string;
  code: string;
  title: string;
  body: string;
  application_id: string | null;
  created_at: string | null;
  read: boolean;
}

export interface NotificationsPage {
  items: NotificationItem[];
  unread: number;
  page: number;
  page_size: number;
  total: number;
}

export interface CompanyInfo {
  source?: string | null;
  fetched_at?: string | null;
  applicant_type?: string | null;
  company_full_name?: string | null;
  company_short_name?: string | null;
  ogrn?: string | null;
  registration_date?: string | null;
  company_status?: string | null;
  okved_main_code?: string | null;
  okved_main_name?: string | null;
  legal_address_region?: string | null;
  director_full_name?: string | null;
  founders?: { name: string; share_percent?: string | null }[];
  guarantor_full_name?: string | null;
  sme_category?: string | null;
  tax_regime?: string | null;
  employees_count?: number | null;
}

export interface StaffReason {
  code: string;
  text?: string | null;
  employee_text?: string | null;
  client_text?: string | null;
  client_visibility?: string | null;
}

export interface StaffListItem {
  id: string;
  application_number: string;
  status: string;
  product_code: string;
  amount: string | null;
  version: number;
  company_short_name: string | null;
  applicant_inn: string | null;
  term_months: number | null;
  manual_review_reasons: StaffReason[];
  grade: string | null;
  score: number | null;
  queued_at: string | null;
  time_in_queue_sec: number | null;
  review_due_at: string | null;
  sla_breached: boolean;
  assignee: { id: string; full_name: string | null } | null;
  failed_stage: string | null;
  last_error_code: string | null;
  next_retry_at: string | null;
  is_history: boolean;
  submitted_at: string | null;
  updated_at: string | null;
}

export interface StaffPage {
  items: StaffListItem[];
  page: number;
  page_size: number;
  total: number;
  counters: Partial<Record<string, number>>;
}

export interface FactorContribution {
  factor_code: string;
  factor_name: string;
  value: unknown;
  bin_id?: string;
  bin_label?: string | null;
  points: number;
}

export interface ScoringInfo {
  score: number;
  grade: string;
  pd: string;
  factor_contributions: FactorContribution[];
  features?: Record<string, unknown>;
  scorecard_version: string;
  scorecard_sha256?: string;
  as_of_date?: string;
  calculated_at?: string;
}

export interface ProposedOption {
  option_type: string;
  product_code: string;
  amount: string;
  term_months: number;
  rate_percent: string;
  monthly_payment: string;
  total_payment?: string;
  overpayment?: string;
  recommended?: boolean;
  requires_collateral?: boolean;
  requires_owner_guarantee?: boolean;
  tranche_max_term_months?: number | null;
}

export interface PolicyRecommendation {
  outcome: string;
  options?: ProposedOption[];
  reason_codes?: string[];
  allowed_payment?: string | null;
  max_amount_requested_term?: string | null;
}

export interface RuleStep {
  rule: string;
  result: string;
  [key: string]: unknown;
}

export interface StaffDecision {
  id: string;
  outcome: string;
  mode: string;
  status: string;
  reasons: StaffReason[];
  reason_codes: string[];
  reason_details: Record<string, Record<string, unknown>>;
  rules_path: RuleStep[];
  values: Record<string, unknown> | null;
  recommendation: PolicyRecommendation | null;
  proposed_options: ProposedOption[] | null;
  override: boolean;
  four_eyes_trigger: string | null;
  comment: string | null;
  proposed_by: string | null;
  decided_by: string | null;
  confirmed_by: string | null;
  scorecard_version: string | null;
  policy_version: string | null;
  policy_sha256?: string | null;
  grade: string | null;
  created_at: string | null;
}

export interface SourceAttempt {
  attempt: number;
  stage: string;
  outcome: string;
  error_code: string | null;
  requested_at: string | null;
  duration_ms: number | null;
  external_request_id?: string | null;
}

export interface SourceInfo {
  source: string;
  attempts: SourceAttempt[];
  latest: { outcome: string; received_at: string | null; data: Record<string, unknown> | null } | null;
}

export interface StaffInfoItem extends InfoItemView {
  reason_code?: string;
  employee_text?: string | null;
}

export interface StaffInfoRequest {
  id: string;
  status: string;
  due_at: string | null;
  due_text?: string;
  created_at: string | null;
  answered_at: string | null;
  source?: string | null;
  items: StaffInfoItem[];
}

export interface HistoryEvent {
  event_id: string;
  event_type: string;
  occurred_at: string;
  actor_type: string;
  actor: string | null;
  application_version: number | null;
  payload: Record<string, unknown>;
}

export interface AuditEntry {
  id?: number;
  occurred_at: string;
  actor_login: string | null;
  actor_role: string | null;
  action: string;
  result: string;
  object_type?: string | null;
  object_id?: string | null;
  application_id?: string | null;
  ip_address: string | null;
  user_agent?: string | null;
  request_id?: string | null;
  details: Record<string, unknown>;
}

export interface StaffConsent {
  consent_type: string;
  text_version: string;
  granted_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  ip_address: string | null;
  user_agent: string | null;
}

export interface StaffCard {
  id: string;
  application_number: string;
  version: number;
  status: string;
  client_status: string;
  client_status_title?: string;
  available_actions: string[];
  is_history?: boolean;
  product_code: string;
  product_name: string;
  purpose: string;
  purpose_title: string;
  applicant_inn: string | null;
  applicant_type: string | null;
  company_short_name: string | null;
  client: { id: string; full_name: string; representative_role: string | null } | null;
  form: Record<string, unknown>;
  company: CompanyInfo | null;
  submitted_snapshot: Record<string, unknown> | null;
  field_changes: {
    field_name: string;
    field_label: string | null;
    old_value: string | null;
    new_value: string | null;
    changed_at: string | null;
    info_request_id: string | null;
  }[];
  assignee: { id: string; full_name: string | null } | null;
  sla: { queued_at: string | null; review_due_at: string | null; sla_breached: boolean };
  processing: {
    failed_stage: string | null;
    last_error_code: string | null;
    enrichment_retry_count: number;
    next_retry_at: string | null;
    auto_info_request_count: number;
    info_request_count: number;
    manual_review_required: boolean;
    technical_reason: StaffReason | null;
  };
  manual_review_reasons: StaffReason[];
  discrepancies: { code: string; value: string | null; text: string }[];
  scoring: ScoringInfo | null;
  decisions: StaffDecision[];
  sources: SourceInfo[];
  offer: (OfferView & { status: string }) | null;
  final_terms: Record<string, unknown> | null;
  signing: SigningView | null;
  loan: LoanView | null;
  documents: DocumentInfo[];
  required_documents: RequiredDocument[];
  consents: StaffConsent[];
  info_requests: StaffInfoRequest[];
  comments: { id: string; kind: string; author: string | null; body: string; created_at: string | null }[];
  history: HistoryEvent[];
  audit?: AuditEntry[];
  created_at: string | null;
  submitted_at: string | null;
  decided_at: string | null;
  issued_at: string | null;
  updated_at: string | null;
}

export interface Metrics {
  period: { start: string; end: string; product_code: string | null; complete: boolean };
  applications_created: number;
  north_star: number | null;
  time_to_decision_median_sec: number | null;
  time_to_decision_auto_median_sec: number | null;
  time_to_decision_manual_median_sec: number | null;
  wizard_conversion: number | null;
  fill_conversion: number | null;
  fill_duration_median_sec: number | null;
  prefill_share: number | null;
  completeness_first_time: number | null;
  info_request_share: number | null;
  info_request_cycles_avg: number | null;
  auto_decision_share: number | null;
  manual_review_sla_share: number | null;
  queue_wait_median_sec: number | null;
  outcomes: Partial<Record<string, number>>;
  approval_rate: number | null;
  offer_acceptance: number | null;
  counter_offer_acceptance: number | null;
  credit_line_chosen: number | null;
  stop_factor_share: number | null;
  stop_factor_codes: Partial<Record<string, number>>;
  override_share: number | null;
  integration_failed_attempt_share: number | null;
  integration_failures_by_source: Partial<Record<string, number>>;
  enrichment_retries: number | null;
  processing_error_applications: number | null;
  end_to_end_conversion: number | null;
  grade_distribution: Partial<Record<string, number>>;
  grade_psi: number | null;
  expected_loss_issued: string | null;
  funnel: Partial<Record<string, number>>;
  targets: Partial<Record<string, number>>;
}

export interface ConfigVersion {
  config_type: string;
  version: string;
  sha256: string;
  author: string | null;
  effective_from: string | null;
  description?: string | null;
  file?: string | null;
  first_loaded_at?: string | null;
  last_loaded_at?: string | null;
}

export interface ConfigsResponse {
  active: ConfigVersion[];
  history: ConfigVersion[];
}

export interface AuditPage {
  items: AuditEntry[];
  page: number;
  page_size: number;
  total: number;
}

export interface DemoState {
  outages: Partial<Record<string, string>>;
  overrides: unknown[];
  counters: { source: string; inn: string; requests: number }[];
  requests_total: Partial<Record<string, number>>;
}

export interface MetaInfo {
  demo_mode: boolean;
  ai_enabled: boolean;
}
