export interface UnitRef {
  id: string;
  code: string;
  type: string;
  name: string;
  name_ar: string;
}

export interface UserLabel {
  id: string;
  name: string;
  name_ar: string | null;
}

export interface PipelineOverview {
  states: Record<string, number>;
  total: number;
  last_successful_ingestion_at: string | null;
  worker: { alive: boolean; last_beat_at: string | null };
  alerts: { pipeline: string; name: string; state: string; error: string | null }[];
}

export interface DashboardSummary {
  generated_at: string;
  window_days: number;
  totals: { reviewed_interactions: number; potential_findings: number; by_status: Record<string, number> };
  recurrence: { evaluated: number; recurred: number; rate: number | null };
  awareness: Record<string, number>;
  actions: { due_or_completed: number; completed: number; overdue: number; completion_rate: number | null };
  generations: { distribution: Record<string, number>; pending_approval: number };
  trend: {
    week_start: string;
    cases: number;
    confirmed: number;
    pending: number;
    rate_per_100: number | null;
    pending_per_100: number | null;
  }[];
  pipelines: PipelineOverview;
  models: Record<string, number>;
}

export interface CaseListItem {
  finding_id: string;
  case_id: string;
  occurred_at: string;
  flagged_at: string;
  case_type: string;
  interaction_type: string;
  status: string;
  severity: string;
  rule_code: string;
  confidence: number | null;
  detection_method: string;
  contributing_factor: string;
  employee: { id: string; pseudonym: string };
  org_unit: UnitRef;
}

export interface Paged<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface ActionItem {
  id: string;
  action_type: string;
  description: string;
  owner: UserLabel | null;
  due_at: string;
  status: string;
  overdue: boolean;
  completed_at: string | null;
  completion_evidence_ref: string | null;
}

/** A rule condition that held for a case, with the fact observed (labels supplied by the API). */
export interface MatchedCondition {
  field: string;
  op: string;
  value: unknown;
  actual: unknown;
  label: string;
  label_ar: string;
  op_label: string;
  op_label_ar: string;
  value_label: string | null;
  value_label_ar: string | null;
  actual_label: string | null;
  actual_label_ar: string | null;
}

export interface FindingDetail {
  id: string;
  status: string;
  severity: string;
  reason_code: string;
  explanation: string;
  explanation_ar: string;
  observed_action: string;
  observed_action_ar: string;
  detection_method: string;
  confidence: number | null;
  contributing_factor: string;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: UserLabel | null;
  matched_conditions: MatchedCondition[];
  rule: {
    id: string;
    code: string;
    version: string;
    category: string;
    name: string;
    name_ar: string;
    match: 'all' | 'any';
    description: string;
    description_ar: string;
    expected_action: string;
    expected_action_ar: string;
    severity: string;
  };
  policy: {
    id: string;
    code: string;
    version: string;
    title: string;
    title_ar: string;
    effective_from: string;
    effective_to: string | null;
  };
  model: { id: string; name: string; version: string; status: string; limitations: string } | null;
  decisions: {
    id: string;
    decision: string;
    rationale: string;
    policy_clear: boolean | null;
    evidence_supports: boolean | null;
    system_issue_contributed: boolean | null;
    contributing_factor: string;
    amended_severity: string | null;
    reviewer: UserLabel | null;
    decided_at: string;
  }[];
  responses: {
    id: string;
    stage: 'before_feedback' | 'after_feedback';
    awareness_state: string | null;
    understood_after_feedback: boolean | null;
    contextual_factors: string[];
    response_text: string | null;
    requested_review: boolean;
    submitted_at: string;
  }[];
  actions: ActionItem[];
  follow_up: {
    window_days: number;
    comparable_cases: number;
    recurrences: number;
    recurred: boolean;
    evaluated_at: string;
  } | null;
  can_review: boolean;
}

export interface CaseDetail {
  id: string;
  source_case_key: string;
  source_system: { id: string; code: string; name: string };
  occurred_at: string;
  case_type: string;
  interaction_type: string;
  complexity_band: string;
  data_quality_status: string;
  synthetic: boolean;
  employee: { id: string; pseudonym: string; role_title: string };
  org_path: UnitRef[];
  evidence: {
    id: string;
    type: string;
    access_class: string;
    secure_reference: string | null;
    content_hash: string | null;
    summary: string | null;
    restricted: boolean;
  }[];
  model_runs: {
    id: string;
    model: string;
    run_at: string;
    output_summary: string;
    confidence: number | null;
    latency_ms: number;
    review_status: string;
  }[];
  findings: FindingDetail[];
  viewer: { is_subject: boolean; can_respond: boolean; can_manage_actions: boolean };
}

export interface EmployeeListItem {
  id: string;
  pseudonym: string;
  role_title: string;
  org_unit: UnitRef;
  current_generation: string | null;
  current_score: number | null;
  current_coverage: number | null;
  pending_generation: string | null;
  confirmed: number;
  disputed: number;
  pending_review: number;
  dismissed: number;
}

export interface Indicator {
  value: number | null;
  n: number;
  weight: number;
}

export interface Snapshot {
  as_of: string;
  method_version: string;
  weights: Record<string, number>;
  indicators: Record<string, Indicator>;
  gates: { code: string; passed: boolean }[];
  gaps: string[];
  warnings: string[];
  no_open_cycle: boolean;
}

export interface GenerationVersion {
  id: string;
  version: number;
  generation_code: string;
  status: 'approved' | 'proposed' | 'rejected';
  effective_at: string;
  end_at: string | null;
  score: number | null;
  coverage: number;
  evidence_count: number;
  method_version: string;
  approved_at: string | null;
  indicator_snapshot: Snapshot;
}

export interface TimelineItem {
  type: string;
  at: string;
  id: string;
  [key: string]: unknown;
}

export interface LearningHistory {
  employee: { id: string; pseudonym: string; role_title: string; start_date: string; org_path: UnitRef[] };
  current: GenerationVersion | null;
  pending: GenerationVersion | null;
  versions: GenerationVersion[];
  live_evaluation: Snapshot & { generation_code: string; score: number | null; coverage: number; evidence_count: number };
  case_count: number;
  categories: Record<string, { confirmed: number; disputed: number; dismissed: number; pending: number; cases: number }>;
  open_actions: {
    id: string;
    action_type: string;
    description: string;
    status: string;
    due_at: string;
    overdue: boolean;
    finding_id: string;
    case_id: string | null;
  }[];
  timeline: TimelineItem[];
  viewer: { is_self: boolean; can_approve: boolean; can_record_coaching: boolean };
}

export interface InsightGroup {
  org_unit: UnitRef;
  suppressed: boolean;
  employees: number | null;
  cases?: number;
  confirmed?: number;
  disputed?: number;
  dismissed?: number;
  pending?: number;
  rate_per_100?: number | null;
  recurrence_rate?: number | null;
  action_completion?: number | null;
  systemic_share?: number | null;
  factors?: Record<string, number>;
  generation_mix?: Record<string, number>;
  avg_generation?: number | null;
}

export interface PipelineStatus {
  id: string;
  code: string;
  name: string;
  source: { code: string; name: string; approved: boolean; enabled: boolean };
  state: string;
  state_changed_at: string;
  last_run_at: string | null;
  last_success_at: string | null;
  next_run_at: string | null;
  schedule_seconds: number;
  freshness_sla_minutes: number;
  freshness_minutes: number | null;
  sla_breached: boolean;
  queue_lag_seconds: number;
  last_error: string | null;
  last_request_id: string | null;
  owner: string;
  runbook_url: string;
  last_run: {
    id: string;
    status: string;
    records_read: number;
    records_written: number;
    records_rejected: number;
    records_duplicated: number;
    duration_ms: number | null;
    request_id: string;
  } | null;
}

export interface ModelStatus {
  id: string;
  name: string;
  version: string;
  purpose: string;
  status: string;
  status_is_simulated: boolean;
  state_changed_at: string;
  owner: string;
  approved_at: string | null;
  last_validation_at: string | null;
  last_run_at: string | null;
  latency_ms_p50: number | null;
  missing_input_rate: number | null;
  drift_score: number | null;
  override_rate: number | null;
  runs_30d: number;
  limitations: string;
}

export interface SimulationOption {
  intervention: string;
  estimated_rate: number;
  interval_90: [number, number];
  risk_band: string;
  addressable_share: number;
  expected_cases_per_1000: number;
}

export interface SimulationResult {
  id: string;
  created_at: string;
  case_type: string;
  horizon_days: number;
  lookback_days: number;
  sample: { cases: number; confirmed_findings: number };
  contributing_factors: Record<string, number>;
  options: SimulationOption[];
  recommended_next_step: { intervention: string; note: string } | null;
  warnings: string[];
  limitations: string[];
  model?: { name: string; version: string; status: string };
}

export interface ReportResult {
  code: string;
  title: string;
  generated_at: string;
  window_days: number;
  columns: string[];
  rows: (string | number | null)[][];
}
