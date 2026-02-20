/**
 * Shared constants (limits, defaults).
 */

export const DEFAULTS = {
  MAX_SECONDS: 60,
  SINGLE_FACE: true,
} as const;

export const LIMITS = {
  MAX_UPLOAD_BYTES: 200 * 1024 * 1024, // 200 MB
  MAX_VIDEO_SECONDS: 5 * 60, // 5 min
  JOB_TTL_HOURS: 24,
} as const;

export const ALLOWED_VIDEO_EXTENSIONS = ['mp4', 'mov', 'webm'] as const;
export const ALLOWED_VIDEO_MIMES = [
  'video/mp4',
  'video/quicktime',
  'video/webm',
] as const;
