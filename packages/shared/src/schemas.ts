/**
 * Shared types and contracts for Job status, Result format, and API payloads.
 */

export const JOB_STATUS = {
  CREATED: 'CREATED',
  FETCHING: 'FETCHING',
  UPLOADING: 'UPLOADING',
  PREPROCESSING: 'PREPROCESSING',
  INFERENCING: 'INFERENCING',
  REPORTING: 'REPORTING',
  DONE: 'DONE',
  FAILED: 'FAILED',
  CANCELED: 'CANCELED',
} as const;

export type JobStatus = (typeof JOB_STATUS)[keyof typeof JOB_STATUS];

export const PROGRESS_STEPS: JobStatus[] = [
  'FETCHING',
  'PREPROCESSING',
  'INFERENCING',
  'REPORTING',
  'DONE',
];

export interface JobOptions {
  max_seconds?: number;
  single_face?: boolean;
}

export interface JobCreateRequest {
  input_type: 'link' | 'upload';
  input_url?: string;
  options?: JobOptions;
}

export interface JobCreateResponse {
  job_id: string;
  status: JobStatus;
}

export interface JobProgress {
  step: JobStatus;
  done: number;
  total: number;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  progress: JobProgress;
  error_code: string | null;
  error_message: string | null;
  result_id?: string | null;
}

export type ConfidenceLevel = 'high' | 'med' | 'low';

export interface ResultSegment {
  start: number;
  end: number;
  score: number;
}

export interface ResultSignals {
  face_coverage?: number;
  audio_present?: boolean;
  multi_face?: boolean;
  compression_hint?: string;
  duration_seconds?: number;
  frames_analyzed?: number;
}

export interface ResultModelMeta {
  model_name: string;
  version: string;
  checksum?: string;
}

export interface Result {
  id: string;
  job_id: string;
  score_overall: number;
  confidence: ConfidenceLevel;
  segments: ResultSegment[];
  signals: ResultSignals;
  model_meta: ResultModelMeta;
}

export interface ResultResponse {
  result: Result;
}
