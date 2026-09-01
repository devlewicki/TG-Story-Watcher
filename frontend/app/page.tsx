"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type DashboardData } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTranslation, useLocale } from "@/lib/i18n";
import { Badge, Card, CardHeader, Empty, ErrorBanner, Spinner, StatCard } from "@/components/ui";
import { timeAgo } from "@/lib/format";

const AXIS_TICK = { fontSize: 11, fill: "#94a3b8" };

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
      <div className="mb-0.5 font-medium text-slate-500 dark:text-slate-400">{label}</div>
      <div className="text-sm font-semibold text-slate-900 dark:text-slate-50">{payload[0].value}</div>
    </div>
  );
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const locale = useLocale();
  const { data, loading, error, refresh } = useFetch<DashboardData>((s) =>
    api.get<DashboardData>("/dashboard", s)
  );

  if (loading) return <Spinner />;
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Empty label={t("dashboard.noData")} />;

  const cards = data.cards;
  const hourData = data.charts.views_by_hour.map((h) => ({
    label: `${String(h.hour).padStart(2, "0")}:00`,
    count: h.count,
  }));
  const dayData = data.charts.views_by_day.map((d) => ({
    label: new Date(d.day).toLocaleDateString(locale, { day: "numeric", month: "short" }),
    count: d.count,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{t("dashboard.title")}</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("dashboard.activeAccounts")}: {data.accounts.active} {t("dashboard.of")} {data.accounts.total}
          </p>
        </div>
        <button
          onClick={refresh}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {t("common.refresh")}
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <StatCard label={t("dashboard.accounts")} value={cards.accounts} icon={<UserIcon />} accentKey="indigo" />
        <StatCard label={t("dashboard.monitoring")} value={cards.monitoring > 0 ? t("dashboard.on") : t("dashboard.off")} accent={cards.monitoring > 0} icon={<PulseIcon />} />
        <StatCard label={t("dashboard.viewedToday")} value={cards.viewed_today} accent icon={<EyeIcon />} />
        <StatCard label={t("dashboard.inQueue")} value={cards.in_queue} icon={<ListIcon />} accentKey="sky" />
        <StatCard label={t("dashboard.skipped24h")} value={cards.skipped} icon={<FilterIcon />} accentKey="amber" />
        <StatCard label={t("dashboard.errors24h")} value={cards.errors} accent={cards.errors > 0} icon={<AlertIcon />} accentKey={cards.errors > 0 ? "red" : "default"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("dashboard.viewsByHour")} />
          <div className="p-4 pt-3">
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={hourData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <defs>
                  <linearGradient id="gradHour" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.9} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0.4} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.15} vertical={false} />
                <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} interval={3} />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={36} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(148,163,184,0.08)" }} />
                <Bar dataKey="count" fill="url(#gradHour)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <CardHeader title={t("dashboard.viewsByDay")} />
          <div className="p-4 pt-3">
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={dayData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <defs>
                  <linearGradient id="gradDay" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0ea5e9" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#0ea5e9" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.15} vertical={false} />
                <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={36} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ stroke: "#94a3b8", strokeOpacity: 0.3 }} />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#0ea5e9"
                  strokeWidth={2.5}
                  fill="url(#gradDay)"
                  activeDot={{ r: 4, strokeWidth: 2 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title={t("dashboard.recentActivity")} />
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {data.recent.length === 0 ? (
            <Empty label={t("dashboard.noActivity")} />
          ) : (
            data.recent.map((e) => (
              <li key={e.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <Badge status={e.event_type === "story_viewed" ? "VIEWED" : e.level} />
                <span className="flex-1 truncate text-slate-700 dark:text-slate-200">{e.message}</span>
                <span className="text-xs text-slate-400">{timeAgo(e.created_at)}</span>
              </li>
            ))
          )}
        </ul>
      </Card>
    </div>
  );
}

const iconProps = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className: "h-5 w-5",
};

function UserIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" />
    </svg>
  );
}
function PulseIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M3 12h4l3-8 4 16 3-8h4" />
    </svg>
  );
}
function EyeIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function ListIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01" strokeWidth="2.6" />
    </svg>
  );
}
function FilterIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M4 5h16l-6 7v6l-4 2v-8L4 5z" />
    </svg>
  );
}
function AlertIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M12 3 2 20h20L12 3z" />
      <path d="M12 10v4" />
      <path d="M12 17.5h.01" strokeWidth="2.6" />
    </svg>
  );
}
