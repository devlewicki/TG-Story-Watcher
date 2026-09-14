"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { AdminCard, AdminCardHeader, ErrorBanner } from "@/components/admin/adminUi";

type SettingsData = {
  sections: Record<string, Record<string, unknown>>;
  environment: Record<string, { configured?: boolean; masked?: string; value?: unknown }>;
};

const SECTION_LABELS: Record<string, Record<string, string>> = {
  general: { language: "Language", theme: "Theme", autostart: "Autostart" },
  telegram: { api_id: "API ID", api_hash: "API hash", reconnect: "Reconnect" },
  monitoring: { check_interval: "Check interval (s)", realtime: "Realtime", resync: "Resync" },
  queue: { max_tasks: "Max tasks", parallel: "Parallel", backoff_factor: "Backoff factor", processing_timeout: "Timeout (s)", max_auto_retries: "Max retries" },
  limits: { views_per_day: "Views / day", views_per_hour: "Views / hour", views_per_minute: "Views / min", searches_per_hour: "Searches / hour", search_results_max: "Search results max", search_delay: "Search delay (s)" },
  view: { min_delay: "Min delay (s)", max_delay: "Max delay (s)", auto_like: "Auto like", like_emoji: "Like emoji", max_stories_per_user_per_day: "Max stories / user / day" },
  discovery: { enabled: "Enabled", hashtags: "Hashtags", locations: "Locations", hashtags_enabled: "Hashtags enabled" },
  filters: {},
};

const ENV_LABELS: Record<string, string> = {
  database_url: "PostgreSQL",
  redis_url: "Redis",
  telegram_api_id: "Telegram API ID",
  telegram_api_hash: "Telegram API hash",
  telegram_proxy_enabled: "Telegram proxy",
  sessions_dir: "Sessions directory",
  secret_key: "Application secret",
};

export default function AdminSettingsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<SettingsData | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [error, setError] = useState("");
  const [savedSection, setSavedSection] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const d = await adminApi.get<SettingsData>("/admin/settings");
      setData(d);
      setDrafts(JSON.parse(JSON.stringify(d.sections)));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function save(section: string) {
    try {
      await adminApi.put("/admin/settings", { section, values: drafts[section] || {} });
      setSavedSection(section);
      setTimeout(() => setSavedSection(""), 2000);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function renderValue(value: unknown): string {
    if (value === null || value === undefined) return "—";
    if (typeof value === "boolean") return value ? "ON" : "OFF";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
    return String(value);
  }

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}
      <p className="text-xs text-slate-400">{t("admin.settings.sectionHint")}</p>

      <div className="grid gap-4 md:grid-cols-2">
        {data &&
          Object.entries(data.sections).map(([section, values]) => (
            <AdminCard key={section}>
              <AdminCardHeader
                title={section}
                right={
                  <span className="text-xs text-emerald-600 opacity-0 transition-opacity dark:text-emerald-400" style={{ opacity: savedSection === section ? 1 : 0 }}>
                    {t("admin.common.saved")}
                  </span>
                }
              />
              <div className="space-y-2 p-4">
                {Object.entries(values).filter(([key]) => key !== "timezone").map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between gap-3 text-sm">
                    <span className="text-slate-500 dark:text-slate-400">{SECTION_LABELS[section]?.[key] || key}</span>
                    {typeof value === "boolean" ? (
                      <input
                        type="checkbox"
                        checked={value}
                        onChange={(e) =>
                          setDrafts((d) => ({ ...d, [section]: { ...d[section], [key]: e.target.checked } }))
                        }
                        className="h-4 w-4 accent-emerald-600"
                      />
                    ) : typeof value === "number" ? (
                      <input
                        type="number"
                        value={Number(value)}
                        onChange={(e) =>
                          setDrafts((d) => ({ ...d, [section]: { ...d[section], [key]: Number(e.target.value) } }))
                        }
                        className="w-28 rounded-xl border border-slate-300 px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                      />
                    ) : (
                      <input
                        value={renderValue(drafts[section]?.[key] ?? value)}
                        onChange={(e) =>
                          setDrafts((d) => ({ ...d, [section]: { ...d[section], [key]: e.target.value } }))
                        }
                        className="w-40 truncate rounded-xl border border-slate-300 px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                      />
                    )}
                  </div>
                ))}
                <div className="pt-2 text-right">
                  <button
                    onClick={() => save(section)}
                    className="rounded-xl bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
                  >
                    {t("admin.settings.save")}
                  </button>
                </div>
              </div>
            </AdminCard>
          ))}
      </div>

      <AdminCard>
        <AdminCardHeader title={t("admin.settings.environment")} subtitle={t("admin.settings.secretWarning")} />
        <div className="divide-y divide-slate-50 dark:divide-slate-800/60">
          {data &&
            Object.entries(data.environment).map(([key, info]) => (
              <div key={key} className="flex items-center justify-between px-5 py-3 text-sm">
                <span className="text-slate-600 dark:text-slate-300">{ENV_LABELS[key] || key}</span>
                <span className="text-xs">
                  {"configured" in info && info.configured !== undefined ? (
                    <span className={info.configured ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}>
                      {info.configured ? t("admin.settings.configured") : t("admin.settings.notConfigured")}
                    </span>
                  ) : "value" in info ? (
                    <span className="text-slate-500 dark:text-slate-400">{renderValue(info.value)}</span>
                  ) : info.masked ? (
                    <span className="font-mono text-slate-400">{t("admin.settings.masked")}: {info.masked}</span>
                  ) : (
                    "—"
                  )}
                </span>
              </div>
            ))}
        </div>
      </AdminCard>
    </div>
  );
}
