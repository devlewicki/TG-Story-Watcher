"use client";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000/api";

export const TOKEN_KEY = "storywatcher_api_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
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
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["X-API-Token"] = token;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    signal,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    // Saved token is wrong/stale: drop it and let the shell show the token gate.
    clearToken();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("storywatcher:unauthorized"));
    }
    throw new ApiError(401, "Invalid or missing API token");
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
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>("GET", path, undefined, signal),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export type Account = {
  id: number;
  phone: string;
  telegram_user_id: number | null;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  status: string;
  monitoring: boolean;
  auto_view: boolean;
  is_premium: boolean;
  last_seen_at: string | null;
};

export type Story = {
  id: number;
  account_id: number;
  peer_id: number;
  telegram_story_id: number;
  author_username: string | null;
  author_name: string | null;
  source: string;
  published_at: string | null;
  expires_at: string | null;
  discovered_at: string | null;
  liked?: boolean;
  like_emoji?: string | null;
  last_viewed_at?: string | null;
  view_count?: number;
};

export type QueueItem = {
  id: number;
  account_id: number;
  story_id: number;
  status: string;
  priority: number;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  attempts: number;
  error: string | null;
  story: Story | null;
};

export type ListEntry = {
  id: number;
  account_id: number;
  peer_id: number | null;
  username: string | null;
  comment: string | null;
  created_at: string | null;
};

export type View = {
  id: number;
  account_id: number;
  peer_id: number;
  telegram_story_id: number;
  story_id: number | null;
  source: string | null;
  rule_id: number | null;
  viewed_at: string | null;
  status: string;
  error: string | null;
};

export type ActivityEvent = {
  id: number;
  account_id: number | null;
  level: string;
  event_type: string;
  message: string;
  metadata: unknown;
  created_at: string | null;
};

export type DashboardData = {
  accounts: { total: number; active: number; monitoring_on: number };
  cards: {
    accounts: number;
    monitoring: number;
    viewed_today: number;
    in_queue: number;
    stories: number;
    skipped: number;
    errors: number;
  };
  charts: {
    views_by_hour: { hour: number; count: number }[];
    views_by_day: { day: string; count: number }[];
  };
  recent: ActivityEvent[];
};