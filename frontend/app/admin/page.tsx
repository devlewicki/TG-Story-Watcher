"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type DashboardData } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminCardHeader,
  AdminStatusBadge,
  HealthDot,
  StatCard,
} from "@/components/admin/adminUi";

const SERVICE_LABEL_KEYS: Record<string, string> = {
  backend: "admin.services.backend",
  worker: "admin.services.worker",
  postgres: "admin.services.postgres",
  redis: "admin.services.redis",
  frontend: "admin.services.frontend",
  nginx: "admin.services.nginx",
  vpn_proxy: "admin.services.vpnProxy",
};

export default function AdminDashboardPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      setData(await adminApi.get<DashboardData>("/admin/dashboard"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [load]);

  if (error && !data) return <p className="py-10 text-center text-sm text-red-500">{error}</p>;
  if (!data) return <p className="py-10 text-center text-sm text-slate-400">{t("common.loading")}</p>;

  return (
    <div className="space-y-6">
      {/* Key metrics */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label={t("admin.dashboard.users")} value={data.users} />
        <StatCard
          label={t("admin.dashboard.accounts")}
          value={data.accounts.total}
          sub={`${t("admin.dashboard.activeAccounts")}: ${data.accounts.active}`}
        />
        <StatCard label={t("admin.dashboard.stories")} value={data.stories} />
        <StatCard
          label={t("admin.dashboard.viewsToday")}
          value={data.views_today.toLocaleString()}
          tone="emerald"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Services */}
        <AdminCard>
          <AdminCardHeader title={t("admin.dashboard.services")} />
          <div className="space-y-3 p-5">
            {Object.entries(data.services).map(([name, svc]) => (
              <div key={name} className="flex items-center justify-between">
                <span className="text-sm text-slate-600 dark:text-slate-300">
                  {t(SERVICE_LABEL_KEYS[name] || `admin.services.${name}`)}
                </span>
                <HealthDot ok={svc.ok} label={svc.paused ? t("admin.common.paused") : undefined} />
              </div>
            ))}
          </div>
        </AdminCard>

        {/* Queue by status */}
        <AdminCard>
          <AdminCardHeader title={t("admin.dashboard.queueByStatus")} />
          <div className="space-y-2 p-5">
            {Object.entries(data.queue.by_status).length === 0 && (
              <p className="text-sm text-slate-400">{t("admin.common.none")}</p>
            )}
            {Object.entries(data.queue.by_status).map(([status, count]) => (
              <div key={status} className="flex items-center justify-between gap-2">
                <AdminStatusBadge status={status} />
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </AdminCard>

        {/* Accounts by status */}
        <AdminCard>
          <AdminCardHeader title={t("admin.dashboard.accountsByStatus")} />
          <div className="space-y-2 p-5">
            {Object.entries(data.accounts.by_status).length === 0 && (
              <p className="text-sm text-slate-400">{t("admin.common.none")}</p>
            )}
            {Object.entries(data.accounts.by_status).map(([status, count]) => (
              <div key={status} className="flex items-center justify-between gap-2">
                <AdminStatusBadge status={status} />
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </AdminCard>
      </div>

      {/* Recent events */}
      <AdminCard>
        <AdminCardHeader title={t("admin.dashboard.recentEvents")} />
        <ul className="divide-y divide-slate-50 dark:divide-slate-800/60">
          {data.recent_events.length === 0 && (
            <li className="px-5 py-8 text-center text-sm text-slate-400">{t("admin.common.none")}</li>
          )}
          {data.recent_events.map((ev) => (
            <li key={ev.id} className="flex items-start gap-3 px-5 py-3">
              <AdminStatusBadge status={ev.severity} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-slate-700 dark:text-slate-200">{ev.message}</p>
                <p className="text-xs text-slate-400">
                  {ev.component} · {ev.event_type} · {formatTime(ev.created_at)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </AdminCard>
    </div>
  );
}
