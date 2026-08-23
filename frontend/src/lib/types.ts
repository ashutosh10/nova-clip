export type ClipStatus = "QUEUED" | "GENERATING" | "READY" | "FAILED";
export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";

export interface Clip {
  id: string;
  position: number;
  prompt: string | null;
  expanded_prompt: string | null;
  media_url: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  trim_start: number;
  trim_end: number | null;
  status: ClipStatus;
  error: string | null;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  width: number;
  height: number;
  fps: number;
  status: "DRAFT" | "PROCESSING" | "READY" | "FAILED";
  master_url: string | null;
  clips: Clip[];
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  project_id: string;
  clip_id: string | null;
  kind: "GENERATE" | "STITCH";
  status: JobStatus;
  progress: number;
  current_step: number | null;
  total_steps: number | null;
  message: string;
  eta_seconds: number | null;
  speed: number | null;
  result_url: string | null;
  error: string | null;
}

