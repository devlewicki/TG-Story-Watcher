/**
 * Compute all system parameters from a single daily views limit.
 *
 * This is the single source of truth for the frontend.
 * The backend equivalent lives in app/services/settings_service.py.
 *
 * Any formula change MUST be mirrored in both places.
 */

export type SectionName = "limits" | "view" | "queue" | "monitoring";

export type DerivedValues = Record<SectionName, Record<string, number>>;

export function computeAllFromDaily(daily: number): DerivedValues {
  const d = Math.max(50, Math.min(12000, Math.round(daily)));

  // ── Limits ──────────────────────────────────────────────────────
  const viewsPerHour = Math.floor(d / 24);
  const viewsPerMinute = Math.ceil(d / 1440);
  const searchesPerHour = Math.max(1, Math.min(10, Math.floor(d / 1500)));
  const searchResultsMax = d <= 200 ? 20 : d <= 2000 ? 50 : d <= 5000 ? 100 : 200;
  const searchDelay = Math.max(60, Math.min(600, 900 - Math.floor(d / 20)));

  // ── View delays ─────────────────────────────────────────────────
  const avgDelay = 86400 / d;
  const minDelay = Math.max(3, Math.min(20, Math.round(avgDelay * 0.3)));
  const maxDelay = Math.max(10, Math.min(120, Math.round(avgDelay * 1.5)));

  // ── Queue ───────────────────────────────────────────────────────
  const parallel = d >= 8000 ? 3 : d >= 3000 ? 2 : 1;
  const maxTasks = d <= 2000 ? 50 : d <= 5000 ? 100 : 200;
  const backoffFactor = d >= 8000 ? 1.5 : 2.0;
  const processingTimeout = d <= 2000 ? 300 : 600;
  const maxAutoRetries = d <= 5000 ? 3 : 5;

  // ── Monitoring ──────────────────────────────────────────────────
  const checkInterval = Math.max(15, Math.min(60, 120 - Math.floor(d / 100)));

  return {
    limits: {
      views_per_day: d,
      views_per_hour: viewsPerHour,
      views_per_minute: viewsPerMinute,
      searches_per_hour: searchesPerHour,
      search_results_max: searchResultsMax,
      search_delay: searchDelay,
    },
    view: {
      min_delay: minDelay,
      max_delay: maxDelay,
    },
    queue: {
      max_tasks: maxTasks,
      parallel,
      backoff_factor: backoffFactor,
      processing_timeout: processingTimeout,
      max_auto_retries: maxAutoRetries,
    },
    monitoring: {
      check_interval: checkInterval,
    },
  };
}
