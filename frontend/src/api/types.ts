// Response shapes of the Eval Triage API (/api/v1). Derived from the backend
// serializers; every number shown in the UI travels as a MetricValue.

export type Envelope<T> = { data: T; meta: Record<string, unknown> }

export type Uncertainty = {
  method: string
  level: number
  lower: number | null
  upper: number | null
  label: string
  note: string
}

export type MetricValue = {
  name: string
  definition_version: string
  score_type: string
  value: number | null
  unit: string
  direction: 'higher_is_better' | 'lower_is_better' | 'neutral' | string
  numerator: number | null
  denominator: number | null
  eligible_count: number | null
  missing_count: number | null
  unavailable_reason: string | null
  uncertainty: Uncertainty | null
  contributing_trial_ids: string[]
  contributing_case_ids: string[]
  provenance: Record<string, unknown>
}

export type Capability = { state: 'supported' | 'unsupported' | 'unknown'; source: string; verified_at: string | null; note: string }

export type Project = {
  id: string
  name: string
  description: string
  is_demo: boolean
  source_identity: Record<string, unknown> | null
  created_at: string
}

export type Health = {
  api: { status: string; version: string; schema_version: number }
  database: { status: string; revision?: string; journal_mode?: string; error?: string }
  worker: { status: 'ok' | 'stale' | 'absent' | string; live_workers: number; last_heartbeat: string | null }
  plugins: Record<string, Plugin>
  memoryai: { source_path: string; source_available: boolean; python_available: boolean }
  data_dir: string
  testing: boolean
}

export type Plugin = { available: boolean; install: string; purpose: string; subprocess_available?: boolean; reason?: string }

export type PackInfo = { pack: string; title: string; summary: string; requires_episode: boolean; expected_schema: Record<string, unknown> }
export type Packs = {
  packs: PackInfo[]
  checks: { name: string; packs: string[] | null; description: string }[]
  invariants: { name: string; description: string }[]
}

export type AdapterInfo = {
  name: string
  title: string
  endpoint_types: string[]
  credential_default: string | null
  credential_default_status: 'not_required' | 'set' | 'missing'
  description: string
  parameter_capabilities: Record<string, string>
  capabilities?: Record<string, Capability>
}

export type Scenario = {
  id: string
  project_id: string
  logical_id: string
  version: number
  name: string
  pack: string
  contract: string
  slice_keys: string[]
  critical_invariants: string[]
  grader_refs: string[]
  hash: string
  parent_id: string | null
  reason: string
  is_demo: boolean
  created_at: string
  dataset_count?: number
  case_count?: number
  definition?: ScenarioDocument
}

export type ScenarioDetail = Scenario & {
  definition: ScenarioDocument
  graders: Grader[]
  datasets: Dataset[]
  versions: { id: string; version: number; created_at: string; reason: string }[]
}

export type GraderSpec = {
  name: string
  kind: 'deterministic' | 'structured' | 'model' | 'pairwise' | 'external'
  mandatory?: boolean | null
  checks?: string[]
  rubric?: string
  judge?: string | null
  config?: Record<string, unknown>
}

export type ScenarioDocument = {
  schema_version: 1
  name: string
  pack: string
  contract: string
  description?: string
  slice_keys?: string[]
  critical_invariants?: string[]
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
  allowed_labels?: string[]
  event_definition?: string | null
  tools?: Record<string, unknown>[]
  corpus?: Record<string, unknown>[]
  graders: GraderSpec[]
  dataset?: { name?: string; cases: Record<string, unknown>[] } | null
}

export type Issue = { path: string; message: string; code: string; row: number | null; external_id: string | null }
export type ValidationReport = { ok: boolean; errors: Issue[]; warnings: Issue[]; case_count: number }

export type Grader = {
  id: string
  project_id: string
  logical_id: string
  version: number
  name: string
  kind: string
  implementation_version: string
  config: Record<string, unknown>
  judge_config_id: string | null
  rubric: string
  output_schema: Record<string, unknown> | null
  hash: string
  is_demo: boolean
  created_at: string
}

export type SplitManifest = {
  splits: Record<string, { cases: number; clusters: number }>
  case_count: number
  cluster_count: number
  leaking_clusters: string[]
}

export type Dataset = {
  id: string
  project_id: string
  logical_id: string
  version: number
  name: string
  scenario_id: string
  pass_rule: { policy: string; mandatory_graders: string[] }
  split_manifest: SplitManifest
  provenance: Record<string, unknown>
  case_count: number
  hash: string
  parent_id: string | null
  reason: string
  is_demo: boolean
  created_at: string
}

export type DatasetDetail = Dataset & {
  versions: { id: string; version: number; reason: string; case_count: number }[]
  duplicates: string[][]
  scenario: Scenario
}

export type EpisodeStep = { id: string; store: string; action: string; args: Record<string, unknown>; timeout_seconds: number | null }

export type Case = {
  id: string
  dataset_id: string
  ordinal: number
  external_id: string
  purpose: string
  input: Record<string, unknown>
  episode: EpisodeStep[]
  expected: Record<string, unknown>
  alternatives: unknown[]
  evidence: Record<string, unknown>[]
  tags: Record<string, unknown>
  severity: Severity
  cluster_id: string
  weight: number
  split: string
  fixture_options: Record<string, unknown>
  case_hash: string
}

export type Severity = 'critical' | 'high' | 'medium' | 'low'

export type TargetConfig = {
  id: string
  project_id: string
  logical_id: string
  version: number
  name: string
  adapter: string
  adapter_version: string
  endpoint_type: string
  model: string
  base_url: string | null
  credential_ref: string | null
  credential_status: 'not_required' | 'set' | 'missing'
  parameters: Record<string, unknown>
  prompt_template: string
  tools: Record<string, unknown>[]
  memory_config: Record<string, unknown>
  capabilities: Record<string, Capability>
  experimental: boolean
  hash: string
  parent_id: string | null
  is_demo: boolean
  created_at: string
}

export type ConnectionTest = {
  id: string
  target_config_id?: string
  status: string
  result: Record<string, unknown> | null
  created_at: string
  finished_at?: string | null
}

export type RunStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'completed_with_errors' | 'cancelled' | 'failed'

export type Run = {
  id: string
  project_id: string
  scenario_id: string
  dataset_id: string
  name: string
  status: RunStatus
  planned_trial_count: number
  terminal_trials: number
  trial_counts: Record<string, number>
  is_demo: boolean
  demo_notice: string | null
  manifest_hash: string
  parent_run_id: string | null
  usage: Record<string, unknown>
  error: Record<string, unknown> | null
  candidates: { key: string; target_config_id: string; name: string | null }[]
  grading_runs: { id: string; source: string; status: string; grader_ids: string[]; created_at: string; finished_at: string | null }[]
  created_at: string
  started_at: string | null
  finished_at: string | null
  cancel_requested_at: string | null
  repeats: number | null
  warnings: string[]
  manifest?: RunManifest
}

export type RunManifest = {
  demo: boolean
  demo_notice?: string
  scenario: { id: string; hash: string; name: string; pack: string; version: number }
  dataset: { id: string; hash: string; name: string; version: number; case_count: number; case_ids: string[]; pass_rule: Dataset['pass_rule'] }
  candidates: { key: string; ordinal: number; config: ManifestConfig }[]
  graders: { id: string; name: string; kind: string; hash: string; implementation_version: string; judge_config_id: string | null }[]
  execution: Record<string, unknown> & { repeats: number; repeat_mode: string }
  limits: Record<string, unknown>
  warnings: string[]
  environment: Record<string, unknown>
}

export type ManifestConfig = {
  id: string
  hash: string
  name: string
  adapter: string
  adapter_version: string
  endpoint_type: string
  requested_model: string
  base_url: string | null
  credential_ref: string | null
  parameters: Record<string, unknown>
  prompt_template: string
  tools: Record<string, unknown>[]
  memory_config: Record<string, unknown>
  capabilities: Record<string, Capability>
  experimental: boolean
}

export type RunPlan = {
  cases: number
  candidates: number
  repeats: number
  planned_trials: number
  stage_calls_per_episode: number
  target_calls_estimate: number
  judge_calls_estimate: number
  judge_calls_note: string
  cost_estimates: Record<string, unknown>
}

export type RunValidation = { ok: boolean; plan: RunPlan; warnings: string[]; manifest: RunManifest; manifest_hash: string; is_demo: boolean }
export type RunFieldError = { field: string; message: string; code: string }

export type TrialStrip = { id: string; repeat: number; status: string; outcome: string | null; grading_error: boolean }

export type CaseCounts = {
  trials: number
  passes: number
  fails: number
  unresolved: number
  errors: number
  grading_errors: number
  provider_errors: number
  invalid_outputs: number
  distinct_outputs: number
  ineligible_for_agreement: Record<string, number>
}

export type CaseFlags = {
  flaky: boolean
  stable_wrong: boolean
  all_pass: boolean
  invariant_failures: string[]
  changed?: boolean
  regression?: boolean
  grading_error?: boolean
  provider_error?: boolean
}

export type CaseCandidateSummary = {
  counts: CaseCounts
  statuses: Record<string, number>
  metrics: Record<string, MetricValue>
  flags: CaseFlags
  trials: TrialStrip[]
}

export type ReviewState = { state: string; decisions: Record<string, number>; latest: Review | null }

export type SummaryCase = {
  case_id: string
  external_id: string
  severity: Severity
  cluster_id: string
  tags: Record<string, unknown>
  purpose: string
  case_hash: string
  candidates: Record<string, CaseCandidateSummary>
  delta_vs_baseline: Record<string, number | null>
  changed: boolean
  review: ReviewState
}

export type SlotRates = {
  scheduled: number
  generated: number
  graded: number
  passed: number
  failed: number
  unresolved: number
  target_completion: MetricValue
  grade_coverage: MetricValue
  conditional_pass: MetricValue
  observed_success_yield: MetricValue
  latency: { count: number; timeouts: number; p50_ms: number | null; p95_ms: number | null; method: string; reason: string | null }
  invariant_failures: Record<string, number>
}

export type RunSummary = {
  run_id: string
  grading_run_id: string | null
  representation: Representation
  is_demo: boolean
  status: RunStatus
  candidates: string[]
  baseline: string | null
  slot_rates: Record<string, SlotRates>
  cases: SummaryCase[]
  slices: { key: string; value: string; candidates: Record<string, MetricValue> }[]
  notes: string[]
}

export type Representation = 'raw' | 'json' | 'semantic'

export type TriageItem = {
  case_id: string
  external_id: string
  purpose: string
  severity: Severity
  tags: Record<string, unknown>
  candidate_key: string
  counts: CaseCounts
  flags: CaseFlags
  pass_rate: MetricValue
  agreement: MetricValue
  review: ReviewState
  priority: number
  priority_label: string
  representative_trial_id: string | null
  trials: TrialStrip[]
}

export type TriageQueue = {
  run_id: string
  grading_run_id: string | null
  items: TriageItem[]
  sort: string
  is_demo: boolean
  baseline: string | null
  candidates: string[]
}

export type Check = {
  name: string
  status: string
  applicable: boolean
  passed: boolean | null
  detail: string
  evidence: unknown[]
  metrics: Record<string, unknown>
  unavailable_reason: string | null
  invariants: Record<string, unknown>
}

export type Grade = {
  id: string
  grading_run_id: string
  trial_id: string
  grader_id: string
  grader_name: string | null
  grader_kind: string | null
  grader_version: number | null
  verdict: string
  reason: string | null
  metric: Record<string, unknown> | null
  checks: Check[]
  evidence_refs: Record<string, unknown>[]
  explanation: string
  error: Record<string, unknown> | null
  judge_attempts: Record<string, unknown>[]
  created_at: string
}

export type Attempt = {
  id: string
  stage: string
  attempt_index: number
  status: string
  request_id: string | null
  requested_model: string | null
  actual_model: string | null
  started_at: string | null
  finished_at: string | null
  latency_ms: number | null
  usage: Record<string, unknown>
  cost: Record<string, unknown>
  retry_reason: string | null
  mutation_outcome_known: boolean | null
  error: Record<string, unknown> | null
  request_artifact: string | null
  response_artifact: string | null
}

export type StepRecord = {
  step_id: string
  action: string
  store: string
  status: string
  output: Record<string, unknown> | null
  new_event_ids: number[]
  error: Record<string, unknown> | null
  skip_reason: string | null
  elapsed_ms: number | null
}

export type MemoryFact = { claim: string; state: string; source_step?: string | null; memory_id?: string | null; [k: string]: unknown }

export type StoreState = {
  backend: string
  store: string
  exhaustive: boolean
  facts: MemoryFact[]
  queue?: unknown[]
  events?: Record<string, unknown>[]
  counts?: Record<string, number>
  notes?: string[]
  [k: string]: unknown
}

export type TrialOutput = {
  text?: string | null
  parsed?: unknown
  parse_error?: string | null
  stores?: Record<string, StoreState>
  tool_calls?: Record<string, unknown>[]
  effects?: Record<string, unknown>[]
  retrieved_ids?: string[] | null
  probability?: number | null
  probability_unavailable_reason?: string | null
  [k: string]: unknown
}

export type TrialDetail = {
  id: string
  run_id: string
  case_id: string
  external_id: string
  severity: Severity
  cluster_id: string
  tags: Record<string, unknown>
  candidate_key: string
  repeat_index: number
  status: string
  latency_ms: number | null
  error_code: string | null
  outcome: string | null
  outcome_reason: string | null
  invariant_failures: string[]
  case: Case
  scenario_contract: RunManifest['scenario']
  is_demo: boolean
  output: TrialOutput | null
  steps: StepRecord[]
  output_artifacts: string[]
  state_artifacts: string[]
  error: Record<string, unknown> | null
  selected_attempt_id: string | null
  started_at: string | null
  finished_at: string | null
  attempts: Attempt[]
  grades: Grade[]
  outcomes: { grading_run_id: string; outcome: string; reason: string | null; invariant_failures: string[] }[]
  siblings: { id: string; candidate_key: string; repeat_index: number; status: string }[]
}

export type TrialBrief = {
  id: string
  run_id: string
  case_id: string
  external_id: string
  severity: Severity
  cluster_id: string
  tags: Record<string, unknown>
  candidate_key: string
  repeat_index: number
  status: string
  latency_ms: number | null
  error_code: string | null
  outcome: string | null
  outcome_reason: string | null
  invariant_failures: string[]
}

export type ReviewDecision =
  | 'confirm_failure'
  | 'acceptable_variation'
  | 'ambiguous'
  | 'grader_incorrect'
  | 'request_more_trials'
  | 'promote_to_regression'

export type Review = {
  id: string
  trial_id: string
  decision: ReviewDecision
  reviewer: string
  explanation: string
  evidence_refs: Record<string, unknown>[]
  grade_ids: string[]
  supersedes_id: string | null
  superseded_by: string | null
  links: Record<string, string>
  created_at: string
}

export type Adjudicated = {
  trial_id: string
  machine_outcome: string | null
  machine_provenance: { grading_run_id: string; outcome: string; reason: string | null }[]
  human_review: Review | null
  adjudicated_outcome: string | null
  adjudication_source: string
  disagreement: boolean
  note: string
}

export type ProbabilityEvent = { event_definition: string; score_type: string; method: string; predictions: number; labels: number }

export type ReliabilityBin = { index: number; lower: number; upper: number; count: number; positives: number; prediction: number | null; outcome: number | null; members: string[] }

export type Selective = { threshold: number; accepted: number; review: number; total: number; coverage: number; risk: number | null; risk_unavailable_reason?: string | null }

export type QualityBlock = {
  brier: number | null
  log_loss_clipped: number | null
  log_loss_epsilon: number
  ece: number | null
  bins: ReliabilityBin[]
  bin_method: string
  selective: Selective
  risk_coverage: Selective[]
}

export type ProbabilityQuality = {
  n_records: number
  n_predictions: number
  n_labels: number
  label_coverage: number | null
  excluded: Record<string, number>
  clusters: number
  classes: { positive: number; negative: number }
  raw: QualityBlock | null
  raw_unavailable_reason: string | null
  calibrated: QualityBlock | null
  calibrated_unavailable_reason?: string | null
  threshold: number
  notes: string[]
  event_definition: string
  split: string | null
  score_types: string[]
  methods: string[]
  calibration_id: string | null
  is_demo: boolean
}

export type ProbabilityRecord = {
  id: string
  external_id: string
  cluster_id: string
  split: string
  probability: number | null
  raw_feature: number | null
  label: number | null
  label_source: string | null
  method: string
  source_version: string
  score_type: string
  predicted_at: string
  labeled_at: string | null
  trial_id: string | null
  case_id: string | null
  unavailable_reason: string | null
}

export type Calibration = {
  id: string
  project_id: string
  logical_id: string
  version: number
  event_definition: string
  features: Record<string, unknown>
  fit_method: string
  source: string
  split_hashes: Record<string, unknown>
  parameters: Record<string, unknown>
  validation: Record<string, unknown>
  hash: string
  created_at: string
}

export type Job = {
  id: string
  kind: string
  status: string
  attempts: number
  result: Record<string, unknown> | null
  error: Record<string, unknown> | null
  created_at: string
  finished_at: string | null
}

export type CompatibilityFinding = { check: string; ok: boolean; message: string; blocks_inference: boolean }

export type ComparisonMetric = {
  name: string
  definition: string
  unit: string
  direction: string
  baseline: number | { passes: number; graded: number; rate: number | null } | null
  candidate: number | { passes: number; graded: number; rate: number | null } | null
  delta?: number | null
  lower?: number | null
  upper?: number | null
  independent_clusters?: number
  paired_cases?: number
  method?: string
  resamples?: number
  seed?: number
  confidence?: number
  margin?: number | null
  warnings?: string[]
  degenerate?: boolean
  gate: string
  inferential: boolean
  note?: string
  reason?: string
}

export type CaseChange = {
  external_id: string
  baseline: number | null
  candidate: number | null
  cluster: string
  severity: Severity
  baseline_trials: string[]
  candidate_trials: string[]
  delta: number | null
}

export type GateCheck = {
  check: string
  direction?: string
  margin?: number
  required?: boolean
  adjusted_lower?: number | null
  adjusted_upper?: number | null
  delta?: number | null
  status: string
  reason: string
}

export type Comparison = {
  id?: string
  project_id?: string
  baseline_run_id?: string
  candidate_run_id?: string
  baseline_key?: string
  candidate_key?: string
  grading_run_ids?: string[]
  policy_id?: string | null
  compatibility: { compatible: boolean; findings: CompatibilityFinding[]; paired_coverage: number | null; paired_cases: number; union_cases: number }
  pairing: { method: string; pairs: string[] }
  method: Record<string, unknown>
  metrics: ComparisonMetric[]
  exclusions: { external_id: string; reason: string; side?: string }[]
  case_changes: { improved: CaseChange[]; regressed: CaseChange[]; unchanged: CaseChange[]; unresolved: CaseChange[]; critical: CaseChange[] }
  decision: {
    verdict: 'ready' | 'blocked' | 'inconclusive'
    reasons: string[]
    checks: GateCheck[]
    multiplicity_note: string | null
    note: string
    invariant_failures: Record<string, unknown>
    demo?: boolean
  }
  preview?: boolean
  created_at?: string
}

export type ReleasePolicy = { id: string; name: string; version: number; policy: Record<string, unknown>; hash: string; created_at: string }

export type SettingsInfo = {
  paths: Record<string, string>
  api: { host: string; port: number; loopback_only: boolean }
  worker: Health['worker'] & { lease_seconds: number; heartbeat_seconds: number; slots: number }
  limits: Record<string, number>
  plugins: Record<string, Plugin>
  memoryai: {
    source_path: string
    python: string
    source_available: boolean
    python_available: boolean
    isolated_stores: Record<string, number>
    recorded_store_bytes: number
    stores_dir_bytes: number
    cleanup: string
  }
  redaction: { version: string; policy: string }
  retention: { policy: string; orphans: Record<string, number> }
  pricing: { entries: Record<string, unknown>[]; sources: { as_of: string; description: string }[] }
  reviewer_name: string
}

export type ExportRecord = {
  id: string
  project_id: string
  status: string
  options: Record<string, unknown>
  archive_hash: string | null
  summary: Record<string, unknown> | null
  error: Record<string, unknown> | null
  download_url: string | null
  created_at: string
  finished_at: string | null
}

export type ImportRecord = {
  id: string
  status: string
  project_id: string | null
  source_identity: Record<string, unknown>
  report: Record<string, unknown> | null
  error: Record<string, unknown> | null
  created_at: string
  finished_at: string | null
}

export type RunEvent = { id: number; type: string; timestamp: string; run_id: string; entity_id: string | null; payload: Record<string, unknown> }

export type ExternalAssertion = {
  type: string
  status: 'pass' | 'fail' | 'error' | 'skipped'
  reason: string
  value: unknown
  score: number | null
  provenance: Record<string, unknown>
}

export type ExternalScore = {
  name: string
  value: number | string | boolean | null
  kind: 'numeric' | 'binary' | 'label' | 'text'
  definition: string
  implementation_version: string
  judge: Record<string, unknown> | null
  is_probability: false
  note: string
}

export type ExternalResult = {
  id: string
  ordinal: number
  upstream_id: string
  case_external_id: string | null
  epoch: number | null
  provider: string | null
  input: Record<string, unknown>
  expected: Record<string, unknown> | null
  output: Record<string, unknown> | null
  status: 'pass' | 'fail' | 'error' | 'unscored'
  assertions: ExternalAssertion[]
  scores: ExternalScore[]
  error: Record<string, unknown> | null
  extra: Record<string, unknown>
}

export type ExternalImport = {
  id: string
  project_id: string
  plugin: string
  plugin_version: string
  source_version: string | null
  source_identity: Record<string, unknown>
  artifact_hash: string
  filename: string | null
  summary: Record<string, unknown>
  warnings: string[]
  is_demo: boolean
  created_at: string
  result_count: number | null
  results?: ExternalResult[]
}

export type PluginCapability = { available: boolean; reason?: string | null; version?: string | null; [key: string]: unknown }

export type IntegrationPlugin = {
  id: string
  version: string
  title: string
  purpose: string
  supported_packs: string[]
  input: string
  input_schema: Record<string, unknown>
  result_schema: Record<string, unknown>
  operations: string[]
  install: string
  capabilities: Record<string, PluginCapability>
}
