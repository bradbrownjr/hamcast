// ========== TYPES ==========

export interface Heard {
  talker: string;
  gateway: string | null;
  mode: string;
  started: number;
  seconds: number;
  recording: string | null;
  transcript: string | null;
  transcript_status:
    | 'queued' | 'transcribing' | 'done' | 'no_speech' | 'too_short' | 'failed' | 'not_transcribed' | null;
}

export interface StreamStatus {
  id: string;
  name: string;
  description: string;
  type: 'ysf' | 'dmr';
  source: string;
  mount: string;
  listen_url: string | null;
  enabled: boolean;
  record: boolean;
  running: boolean;
  linked?: boolean;
  encoder_up?: boolean;
  listeners?: number;
  current?: Heard | null;
  heard?: Heard[];
}

export interface Status {
  callsign: string;
  now: number;
  streams: StreamStatus[];
  icecast_port: number | null;
  transcribing: number | null;
}

export interface StreamConfig {
  id: string;
  name: string;
  type: 'ysf' | 'dmr';
  host: string;
  port: number;
  mount: string;
  description: string;
  record: boolean;
  transcribe: boolean;
  enabled: boolean;
  password: string;
  talkgroup: number;
  slot: number;
  options: string | null;
}

export interface Settings {
  callsign: string;
  dmr_id: number | null;
  icecast: { bundled: boolean; public_url: string | null; port: number | null; bitrate: string };
  transcription: { enabled: boolean; backend: string; model: string; min_seconds: number };
}

export interface YsfHost { id: string; name: string; description: string; host: string; port: number }
export interface DmrHost { id: string; name: string; host: string; password: string; port: number }

// ========== CLIENT ==========

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  status: () => call<Status>('GET', '/api/status'),
  /** Older transmissions from disk, newest first, before the named recording. */
  history: (id: string, before?: string) =>
    call<{ heard: Heard[]; more: boolean }>(
      'GET',
      `/api/history/${id}` + (before ? `?before=${encodeURIComponent(before)}` : ''),
    ),
  me: () => call<{ admin: boolean }>('GET', '/api/me'),
  login: (password: string) => call<{ admin: boolean }>('POST', '/api/login', { password }),
  logout: () => call<{ admin: boolean }>('POST', '/api/logout'),
  streams: () => call<{ streams: StreamConfig[]; dmr_id: number | null }>('GET', '/api/streams'),
  createStream: (s: StreamConfig) => call<StreamConfig>('POST', '/api/streams', s),
  updateStream: (id: string, s: StreamConfig) => call<StreamConfig>('PUT', `/api/streams/${id}`, s),
  deleteStream: (id: string) => call<unknown>('DELETE', `/api/streams/${id}`),
  ysfHosts: () => call<{ hosts: YsfHost[] }>('GET', '/api/directory/ysf'),
  dmrHosts: () => call<{ hosts: DmrHost[] }>('GET', '/api/directory/dmr'),
  settings: () => call<Settings>('GET', '/api/settings'),
};

/** Where a listener plays a net: the public URL, or this host's Icecast port. */
export function listenUrl(s: StreamStatus, status: Status): string | null {
  if (s.listen_url) return s.listen_url;
  if (status.icecast_port == null) return null;
  return `${location.protocol}//${location.hostname}:${status.icecast_port}${s.mount}`;
}
