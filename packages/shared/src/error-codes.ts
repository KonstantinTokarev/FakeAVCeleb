/**
 * Productized error codes for the Deepfake Detector API.
 * Each maps to a user-friendly message and suggested fixes.
 */
export const ERROR_CODES = {
  URL_INVALID: 'URL_INVALID',
  URL_BLOCKED_SSRF: 'URL_BLOCKED_SSRF',
  DOWNLOAD_FAILED: 'DOWNLOAD_FAILED',
  FORMAT_UNSUPPORTED: 'FORMAT_UNSUPPORTED',
  TOO_LARGE: 'TOO_LARGE',
  TOO_LONG: 'TOO_LONG',
  NO_AUDIO: 'NO_AUDIO',
  NO_FACE_DETECTED: 'NO_FACE_DETECTED',
  MULTIPLE_FACES: 'MULTIPLE_FACES',
  INFERENCE_FAILED: 'INFERENCE_FAILED',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
  JOB_NOT_FOUND: 'JOB_NOT_FOUND',
  JOB_CANCELED: 'JOB_CANCELED',
} as const;

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

export interface ErrorMessage {
  title: string;
  suggestion: string;
}

export const ERROR_MESSAGES: Record<ErrorCode, ErrorMessage> = {
  URL_INVALID: {
    title: 'Invalid URL',
    suggestion: 'Use a valid http or https link to a public video.',
  },
  URL_BLOCKED_SSRF: {
    title: 'URL not allowed',
    suggestion: 'This host or IP is not allowed for security reasons.',
  },
  DOWNLOAD_FAILED: {
    title: 'Download failed',
    suggestion: 'Check that the link is public and the file is accessible. Try again later.',
  },
  FORMAT_UNSUPPORTED: {
    title: 'Unsupported format',
    suggestion: 'Use MP4, MOV, or WebM video.',
  },
  TOO_LARGE: {
    title: 'File too large',
    suggestion: 'Upload a smaller file (max 200 MB).',
  },
  TOO_LONG: {
    title: 'Video too long',
    suggestion: 'Use a video under 5 minutes or reduce "Analyze first N seconds".',
  },
  NO_AUDIO: {
    title: 'No audio track',
    suggestion: 'Video has no audio. Analysis will use visual-only mode with lower confidence.',
  },
  NO_FACE_DETECTED: {
    title: 'No face detected',
    suggestion: 'Ensure the video shows a clear, visible face (talking head).',
  },
  MULTIPLE_FACES: {
    title: 'Multiple faces detected',
    suggestion: 'Use a single-person talking head video for best results.',
  },
  INFERENCE_FAILED: {
    title: 'Analysis failed',
    suggestion: 'Something went wrong during analysis. Please try again.',
  },
  INTERNAL_ERROR: {
    title: 'Something went wrong',
    suggestion: 'Please try again. If the problem persists, contact support.',
  },
  JOB_NOT_FOUND: {
    title: 'Job not found',
    suggestion: 'The analysis job may have expired or the link is invalid.',
  },
  JOB_CANCELED: {
    title: 'Job canceled',
    suggestion: 'You can start a new analysis.',
  },
};
