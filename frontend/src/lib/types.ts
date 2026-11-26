export type Role = "viewer" | "member" | "admin" | "owner";
export type MeetingStatus = "scheduled" | "queued" | "processing" | "completed" | "failed";
export type PipelineStage =
  | "queued"
  | "normalize"
  | "transcribe"
  | "diarize"
  | "merge"
  | "summarize"
  | "index"
  | "done"
  | "failed";
export type ActionStatus = "todo" | "in_progress" | "done";

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  has_password: boolean;
  google_connected: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: User;
}

export interface Workspace {
  id: string;
  name: string;
  role: Role;
  slack_configured: boolean;
  slack_auto_post: boolean;
  member_count: number;
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  name: string;
  role: Role;
}

export interface Speaker {
  id: string;
  label: string;
  display_name: string;
  talk_time_s: number;
  word_count: number;
}

export interface Decision {
  text: string;
  timestamp_s: number | null;
}

export interface ActionItemDraft {
  title: string;
  owner: string | null;
  due_date: string | null;
  due_text: string | null;
  timestamp_s: number | null;
}

export interface SpeakerSentiment {
  speaker: string;
  score: number;
  label: "positive" | "neutral" | "negative";
  rationale: string | null;
  talk_time_s: number;
  word_count: number;
}

export interface Insights {
  executive_summary: string;
  key_points: string[];
  decisions: Decision[];
  action_items: ActionItemDraft[];
  open_questions: Decision[];
  sentiment: SpeakerSentiment[];
  topics: string[];
  strategy: "single_pass" | "map_reduce";
  chunks_processed: number;
  engine: string;
}

export interface MeetingSummary {
  id: string;
  workspace_id: string;
  title: string;
  source: "upload" | "recording" | "calendar" | "seed";
  status: MeetingStatus;
  stage: PipelineStage;
  progress: number;
  status_message: string | null;
  error: string | null;
  duration_s: number | null;
  scheduled_at: string | null;
  created_at: string;
  processing_started_at: string | null;
  processing_finished_at: string | null;
  attendees: string[];
  action_item_count: number;
  speaker_count: number;
}

export interface MeetingDetail extends MeetingSummary {
  original_filename: string | null;
  audio_url: string | null;
  waveform_peaks: number[] | null;
  stage_timings: Record<string, number>;
  stt_backend: string | null;
  diarizer_backend: string | null;
  llm_provider: string | null;
  insights: Insights | null;
  speakers: Speaker[];
  share_url: string | null;
}

export interface MeetingPage {
  items: MeetingSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface Segment {
  id: string;
  idx: number;
  start_s: number;
  end_s: number;
  text: string;
  speaker_id: string | null;
  speaker_name: string | null;
  confidence: number | null;
}

export interface ProgressEvent {
  meeting_id: string;
  workspace_id: string;
  status: MeetingStatus;
  stage: PipelineStage;
  progress: number;
  message: string | null;
  error: string | null;
}

export interface ActionItem {
  id: string;
  workspace_id: string;
  meeting_id: string | null;
  meeting_title: string | null;
  title: string;
  description: string | null;
  owner_name: string | null;
  assignee_id: string | null;
  assignee_name: string | null;
  due_date: string | null;
  status: ActionStatus;
  position: number;
  source_start_s: number | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  index: number;
  meeting_id: string;
  meeting_title: string;
  start_s: number;
  end_s: number;
  speakers: string[];
  text: string;
  score: number;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  engine: string;
}

export interface UsageReport {
  days: number;
  totals: {
    meetings_processed: number;
    minutes_transcribed: number;
    avg_processing_seconds: number;
    avg_realtime_factor: number;
    llm_input_tokens: number;
    llm_output_tokens: number;
    cost_usd: number;
    projected_hosted_cost_usd: number;
    cost_per_meeting_usd: number;
  };
  daily: { date: string; minutes: number; cost_usd: number; projected_cost_usd: number; meetings: number }[];
  by_provider: {
    kind: string;
    provider: string;
    events: number;
    input_tokens: number;
    output_tokens: number;
    audio_minutes: number;
    cost_usd: number;
  }[];
  stage_seconds: Record<string, number>;
}

export interface IntegrationStatus {
  google_oauth_enabled: boolean;
  google_calendar_connected: boolean;
  slack_configured: boolean;
  llm_provider: string;
  stt_backend: string;
  diarizer_backend: string;
  embedding_backend: string;
}

export interface PublicMeeting {
  title: string;
  created_at: string;
  scheduled_at: string | null;
  duration_s: number | null;
  insights: Insights | null;
  action_items: { title: string; owner_name: string | null; due_date: string | null; status: ActionStatus }[];
  speakers: string[];
}
