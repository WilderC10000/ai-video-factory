// Mirrors the payload built by app/studio/service.py::build_snapshot.

export type AgentStatus = "idle" | "working" | "waiting_for_approval" | "blocked" | "failed" | "complete";
export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type StageStatus = "pending" | "started" | "complete" | "failed";
export type ApprovalState = "pending" | "approved" | "rejected";

export interface Stage {
  key: string;
  label: string;
  order: number;
  kind: "image_generate" | "video" | "image_edit" | "assembly";
  room_id: string;
  status: StageStatus;
  script_path: string | null;
  model: string | null;
  duration_seconds: number | null;
  planned_cost_usd: number | null;
  estimated_cost_usd: number | null;
  actual_cost_usd: number | null;
  completed_at: string | null;
  error_message: string | null;
  provider_job_id: string | null;
  storyboard_checkpoint_path: string | null;
  storyboard_checkpoint_url: string | null;
  target_frame_path: string | null;
  target_frame_url: string | null;
  previous_frame_path: string | null;
  previous_frame_exists: boolean | null;
  previous_frame_url: string | null;
  latest_output_path: string | null;
  latest_output_exists: boolean | null;
  latest_output_url: string | null;
  latest_output_name: string | null;
  approval_state: ApprovalState | null;
  continuity_severity: Severity | null;
  continuity_note: string | null;
  build_logic_severity: Severity | null;
  build_logic_note: string | null;
  requires_human_review: boolean;
  launchable: boolean;
  intent: StageIntent | null;
  next_stage_key: string | null;
  last_job: Job | null;
}

export interface StageIntent {
  title: string;
  prompt: string | null;
  checklist: string[];
  note: string | null;
}

export type JobStatus =
  | "queued"
  | "submitting"
  | "provider_queued"
  | "generating"
  | "downloading"
  | "syncing"
  | "succeeded"
  | "failed";

export interface Job {
  id: string;
  stage_key: string;
  mode: "continue" | "retry";
  action: string;
  execution_mode: "mock" | "live";
  is_paid: boolean;
  status: JobStatus;
  phase_label: string;
  active: boolean;
  expected_cost_usd: number | null;
  actual_cost_usd: number | null;
  provider_job_id: string | null;
  output_paths: string[];
  error: string | null;
  script_path: string | null;
  created_at: string | null;
  started_at: string | null;
  phase_changed_at: string | null;
  completed_at: string | null;
  log_tail: string[];
}

export interface Execution {
  mode: "disabled" | "mock" | "live";
  launch_enabled: boolean;
  problems: string[];
  sandbox: boolean;
  data_root: string;
}

export type LaunchMode = "continue" | "retry" | "generate";

export interface LaunchPlan {
  mode: LaunchMode;
  reviewed_stage: { key: string; label: string; status: string; approval_state: string | null };
  target_stage: { key: string; label: string; room_id: string; script_path: string | null } | null;
  action: string | null;
  paid: boolean;
  estimated_cost_usd: number;
  spent_usd: number;
  cap_usd: number | null;
  remaining_usd: number | null;
  remaining_after_usd: number | null;
  allowed: boolean;
  problems: string[];
  warnings: string[];
  execution: Execution;
}

export interface Agent {
  name: string;
  role: string;
  status: AgentStatus;
  status_reason: string | null;
  current_task: string | null;
  next_action: string | null;
  requires_human_review: boolean;
  job_phase: string | null;
}

export interface Room {
  id: string;
  name: string;
  floor: number;
  col: number;
  data_source: string | null;
  stage_keys: string[];
  warning_count: number;
  worst_severity: Severity | null;
  agent: Agent;
}

export interface Approval {
  id: string;
  title: string;
  status: ApprovalState;
  room_id: string | null;
  stage_key: string | null;
  estimated_cost_usd: number | null;
  requires_human_review: boolean;
  decided_via: string | null;
  note: string | null;
  decided_at: string | null;
}

export interface StudioEvent {
  id: string;
  type: string;
  severity: Severity;
  message: string;
  room_id: string | null;
  stage_key: string | null;
  requires_human_review: boolean;
  occurred_at: string;
}

export interface Budget {
  cap_usd: number | null;
  cap_source: string | null;
  spent_usd: number;
  remaining_usd: number | null;
  planned_remaining_spend_usd: number;
  over_cap: boolean;
  plan_exceeds_cap: boolean;
  next_stage_block: string | null;
}

export interface ProjectInfo {
  slug: string;
  name: string;
  source: string;
  is_demo: boolean;
  production_stage: string;
  current_stage_key: string | null;
  frontier_stage_key: string | null;
  manifest_path: string;
  last_imported_at: string | null;
  stages_complete: number;
  stages_total: number;
}

export interface AudioProbe {
  has_audio: boolean | null;
  codec: string | null;
  channels: number | null;
  sample_rate: number | null;
  error: string | null;
}

export interface AudioClip extends AudioProbe {
  stage_key: string;
  label: string;
  file: string;
}

export interface AudioReport {
  ffprobe_available: boolean;
  clips: AudioClip[];
  clips_total: number;
  clips_with_audio: number;
  clips_unknown: number;
  final: AudioClip | null;
  final_status: "not_assembled" | "preserved" | "discarded" | "no_source_audio" | "unknown";
  assembly_code_note: string;
  sound_design_implemented: boolean;
}

export interface Snapshot {
  projects: { slug: string; name: string; is_active: boolean; source: string }[];
  project: ProjectInfo | null;
  budget?: Budget | null;
  stages?: Stage[];
  rooms?: Room[];
  approvals?: Approval[];
  events?: StudioEvent[];
  jobs?: Job[];
  active_job?: Job | null;
  audio?: AudioReport;
  execution: Execution;
}

export interface Selection {
  roomId: string;
  stageKey?: string;
}
