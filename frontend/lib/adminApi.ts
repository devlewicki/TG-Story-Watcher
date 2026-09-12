"use client";

/**
 * Admin API client — separate from the user API client.
 * - Different endpoint base (/admin/*)
 * - Different token header (X-Admin-Token) and storage key
 * - 401 clears the admin session and fires `storywatcher:admin-unauthorized`
 *   so the AdminShell can show the login gate.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000/api";

export const ADMIN_TOKEN_KEY = "storywatcher_admin_token";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ADMIN_TOKEN_KEY);
}

export function setAdminToken(token: string): void {
  window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
}

export function clearAdminToken(): void {
  window.localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export class AdminApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal
): Promise<T> {
  const token = getAdminToken();
  const headers: Record<string, string> = {};
  if (token) headers["X-Admin-Token"] = token;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    signal,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    clearAdminToken();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("storywatcher:admin-unauthorized"));
    }
    throw new AdminApiError(401, "Admin authentication required");
  }

  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const detail =
      (data as { detail?: string })?.detail || `Request failed (${res.status})`;
    throw new AdminApiError(res.status, detail);
  }
  return data as T;
}

export const adminApi = {
  get: <T>(path: string, signal?: AbortSignal) =>
    request<T>("GET", path, undefined, signal),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

// ------------------------------------------------------------------- types

export type AdminInfo = {
  id: number;
  username: string;
  email: string | null;
  role: "SUPER_ADMIN" | "ADMIN" | "READ_ONLY";
  enabled: boolean;
  last_login_at: string | null;
};

export type DashboardData = {
  users: number;
  accounts: {
    total: number;
    active: number;
    by_status: Record<string, number>;
  };
  stories: number;
  queue: {
    total: number;
    active: number;
    failed: number;
    by_status: Record<string, number>;
  };
  views_today: number;
  worker: {
    running: boolean;
    paused: boolean;
    heartbeat_age: number | null;
    status: Record<string, unknown>;
  };
  services: Record<string, { ok: boolean; paused?: boolean }>;
  recent_events: {
    id: number;
    component: string;
    event_type: string;
    severity: string;
    message: string;
    created_at: string | null;
  }[];
};

export type AdminUserRow = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  created_at: string | null;
  accounts: number;
  views_today: number;
  queue_active: number;
  last_activity: string | null;
  blocked: boolean;
};

export type AdminAccountRow = {
  id: number;
  phone_masked: string;
  telegram_user_id: number | null;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  status: string;
  monitoring: boolean;
  views_today: number;
  queue_active: number;
  last_seen_at: string | null;
  has_session: boolean;
  owner: { id: number; email: string; name: string } | null;
};

export type AdminStoryRow = {
  id: number;
  author_username: string | null;
  author_name: string | null;
  peer_id: number;
  telegram_story_id: number;
  source: string;
  published_at: string | null;
  discovered_at: string | null;
  account_id: number;
  account_username: string | null;
  owner: { id: number; email: string } | null;
  views: number;
};

export type AdminQueueRow = {
  id: number;
  status: string;
  priority: number;
  attempts: number;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  error: string | null;
  story: { id: number; author_username: string | null; author_name: string | null } | null;
  account: { id: number; username: string | null; user_id: number | null } | null;
};

export type QueueHealth = {
  by_status: Record<string, number>;
  active: number;
  stuck: number;
  failed: number;
  oldest_pending: string | null;
  avg_processing_seconds: number | null;
};

export type WorkerStatus = {
  running: boolean;
  paused: boolean;
  pid: number | null;
  uptime_seconds: number | null;
  heartbeat_age: number | null;
  views_today: number;
  queue_active: number;
  consecutive_errors: number;
  status: Record<string, unknown>;
};

export type ServiceRow = {
  name: string;
  ok: boolean | null;
  paused?: boolean;
  version?: string | null;
  uptime_seconds?: number;
  heartbeat_age?: number | null;
  last_check: string;
};

export type SystemAnalytics = {
  period: string;
  views_per_day: { day: string; count: number }[];
  active_accounts: number;
  stories_discovered: number;
  failed_tasks: number;
  errors: number;
  flood_waits: number;
  new_users: number;
};

export type ActivityRow = {
  id: number;
  account_id: number | null;
  level: string;
  event_type: string;
  message: string;
  metadata: string | null;
  created_at: string | null;
};

export type ErrorGroupRow = {
  message: string;
  count: number;
  first_seen: string | null;
  last_seen: string | null;
  level: string;
  event_type: string | null;
};

export type AdminSessionRow = {
  id: string;
  admin_username: string;
  ip: string | null;
  user_agent: string | null;
  created_at: string | null;
  last_activity_at: string | null;
  expires_at: string | null;
  expired: boolean;
};

export type AuditLogRow = {
  id: number;
  admin_id: number | null;
  admin_username: string | null;
  action: string;
  target: string | null;
  result: string;
  ip: string | null;
  error: string | null;
  metadata: string | null;
  created_at: string | null;
};

export type BackupRow = {
  id: string;
  filename: string;
  created_at: string | null;
  application_version: string | null;
  schema_version: string | null;
  size: number;
  checksum: string | null;
  encrypted: boolean;
  status: string;
  origin: string;
  users: number | null;
  accounts: number | null;
  sessions: number | null;
};

export type BackupOperation = {
  id: string;
  backup_id: string | null;
  type: string;
  status: "PENDING" | "RUNNING" | "SUCCESS" | "FAILED" | "CANCELLED";
  progress: number;
  stage: string | null;
  result: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_by: string | null;
};

export type Paged<T> = {
  total: number;
  page: number;
  page_size: number;
  items: T[];
};
