"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type SystemAnalytics } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { AdminCard, AdminCardHeader, ErrorBanner, StatCard } from "@/components/admin/adminUi";
import { Segmented } from "@/components/ui";

type Period = "24h" | "7d" | "30d" | "90d";

export default function AdminAnalyticsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<SystemAnalytics | null>(null);
  const [period, setPeriod] = useState<Period>("7d");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await adminApi.get<SystemAnalytics>(`/admin/analytics/system?period=${period}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [period]);

  useEffect(() => {
    load();
  }, [load]);

  const maxViews = Math.max(1, ...(data?.views_per_day.map((d) => d.count) || [1]));

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}

      <div className="flex items-center justify-between">
        <Segmented
          value={period}
          onChange={(v) => setPeriod(v as Period)}
          options={[
            { value: "24h", label: "24h" },
            { value: "7d", label: "7d" },
            { value: "30d", label: "30d" },
            { value: "90d", label: "90d" },
          ]}
        />
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label={t("admin.analytics.activeAccounts")} value={data?.active_accounts ?? "—"} tone="emerald" />
        <StatCard label={t("admin.analytics.discovered")} value={data?.stories_discovered ?? "—"} />
        <StatCard label={t("admin.analytics.failedTasks")} value={data?.failed_tasks ?? "—"} tone="red" />
        <StatCard label={t("admin.analytics.floodWaits")} value={data?.flood_waits ?? "—"} tone="amber" />
        <StatCard label={t("admin.errors.title")} value={data?.errors ?? "—"} tone="red" />
        <StatCard label={t("admin.analytics.newUsers")} value={data?.new_users ?? "—"} tone="sky" />
      </div>

      <AdminCard>
        <AdminCardHeader title={t("admin.analytics.viewsPerDay")} />
        <div className="p-5">
          {!data || data.views_per_day.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-400">{t("admin.common.none")}</p>
          ) : (
            <div className="flex h-48 items-end gap-1.5">
              {data.views_per_day.map((d) => (
                <div key={d.day} className="group relative flex-1">
                  <div
                    className="w-full rounded-t-md bg-emerald-500/80 transition-colors group-hover:bg-emerald-600 dark:bg-emerald-500/60"
                    style={{ height: `${Math.max(4, (d.count / maxViews) * 176)}px` }}
                  />
                  <span className="pointer-events-none absolute -top-7 left-1/2 z-10 -translate-x-1/2 rounded-lg bg-slate-900 px-2 py-1 text-[10px] text-white opacity-0 transition-opacity group-hover:opacity-100">
                    {d.day.slice(5)}: {d.count}
                  </span>
                </div>
              ))}
            </div>
          )}
          {data && data.views_per_day.length > 0 && (
            <div className="mt-2 flex justify-between text-[10px] text-slate-400">
              <span>{data.views_per_day[0]?.day.slice(0, 10)}</span>
              <span>{data.views_per_day[data.views_per_day.length - 1]?.day.slice(0, 10)}</span>
            </div>
          )}
        </div>
      </AdminCard>
    </div>
  );
}
